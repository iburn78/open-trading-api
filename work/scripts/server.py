from core.common.optlog import set_logger
set_logger()

import asyncio
from core.common.optlog import optlog, log_raise
from core.common.setup import HOST, PORT
import core.kis.kis_auth as ka
from core.kis.domestic_stock_functions_ws import ccnl_notice
from core.kis.ws_data import get_tr, TransactionNotice, TransactionPrices
from core.model.order import OrderList
from core.model.agent import ConnectedAgents, AgentCard
from app.comm.comm_handler import handle_client, dispatch
from app.comm.subs_manager import SubscriptionManager
from app.comm.order_manager import OrderManager

# server.py -----------------------------------------------------------
# KIS와의 Communication
# - REST: 1 time request/response
# - WS: tradenotice 등 수신
# Localhost Server
# - local client의 request handle

# ---------------------------------
# auth and Set-up
# ---------------------------------
svr = 'vps' # prod, auto, vps
if svr != 'vps':
    cfm_message = input("Running real trading mode, sure? (Enter svr name): ")
    if cfm_message != svr:
        log_raise("Check svr ---")

ka.auth(svr)
ka.auth_ws(svr)
trenv = ka.getTREnv()
# master_orderlist = OrderList() # to keep a record in the server / and to cancel all (breaker) 
ws_ready = asyncio.Event()
command_queue = asyncio.Queue() # to process submit and cancel orders
connected_agents = ConnectedAgents() 
subs_manager = SubscriptionManager()
order_manager = OrderManager()

#### ASSURE INDENPENDENCE OF EACH AGENT #####################################
### MAY ASSIGN ORDERLIST FOR EACH 

# ---------------------------------
# Variables to share with clients
# ---------------------------------
server_data_dict ={
    'trenv' : trenv,
    # 'master_orderlist' : master_orderlist, 
    'command_queue' : command_queue, 
    'connected_agents' : connected_agents,
    'subs_manager' : subs_manager, 
}

# ---------------------------------
# Process orders through the websocket
# ---------------------------------
async def process_commands():
    await ws_ready.wait()
    while True:
        (writer, request_command, request_data) = await command_queue.get()
        # only agents can submit commands, and agents should be registered already
        port = writer.get_extra_info("peername")[1] 
        agent = connected_agents.get_agent_card_by_port(port)

        if request_command == "CANCEL_orders":  # agent specific cancel per its orderlist
            cancelled_orders = await agent.orderlist.cancel_all_outstanding(trenv)
            # revise-cancel orders are also new orders, so need to register to the order_manager
            # 
            ##########################
            ##########################
            # make sure there is no time gap between order submission and order registration
            ##########################
            ##########################
            await order_manager.add_agent_orders(agent, cancelled_orders)

            await agent.orderlist.closing_checker()

            # await master_orderlist.cancel_all_outstanding(trenv)
            # await master_orderlist.closing_checker()
        
        elif request_command == "submit_orders":
            if request_data: # list [order, order, ... ]
                optlog.debug(f"Trading server got: {request_data}")
                await agent.orderlist.submit_orders_and_register(request_data, trenv)

                ##########################
                ##########################
                # make sure there is no time gap between order submission and order registration
                ##########################
                ##########################
                await order_manager.add_agent_orders(agent, request_data) # request_data: submission completed orders
                # await master_orderlist.submit_orders_and_register(request_data, trenv)

        else:
            log_raise(f"Undefined: {request_command} ---")
        command_queue.task_done()

# ---------------------------------
# Websocket and response handling logic
# ---------------------------------
async def async_on_result(ws, tr_id, result, data_info):
    if tr_id is None or tr_id == '':
        log_raise(f"tr_id is None or '': {tr_id} ---")

    if get_tr(trenv, tr_id) == 'TransactionNotice': # Notices to the trade orders
        trn = TransactionNotice.create_object_from_response(result)
        # at this time, an agent who sent the order should already be registered in connected_agents
        # 1) agent in connected_agents and in order_manager
        # 2) agent in connected_agents but not in order_manager yet
        # 3) agent already dropped out, so removed from connected_agents 
        # 4) agent already dropped out, so removed from connected_agents 
        ############### revise connected_agents behavior ###############
        agent_id = order_manager.get_agent_id_from_trn(trn)
        if agent_id:
            agent: AgentCard = connected_agents.get_agent_card_by_id(agent_id) if agent_id else None
        else:
            # trn arrived earlier than order registration




        # orderlist update in the agent_card (server side)
        await agent.orderlist.process_tr_notice(trn, trenv) 

        # await master_orderlist.process_tr_notice(trn, trenv) 

        # also send trn to agent (client side) to follow its order status
        await dispatch(agent, trn)

        optlog.debug(trn)
        
    elif get_tr(trenv, tr_id) in ('TransactionPrices_KRX',  'TransactionPrices_Total'): # 실시간 체결가
        trp = TransactionPrices(trprices=result)
        await dispatch(connected_agents.get_target_agents(trp), trp)

    # to add more tr_id ...
    else:
        log_raise(f"Unexpected tr_id {tr_id} received ---")

def on_result(ws, tr_id, result, data_info):
    asyncio.create_task(async_on_result(ws, tr_id, result, data_info))

async def websocket_loop():
    kws = ka.KISWebSocket(api_url="/tryitout")
    subs_manager.kws = kws

    # default subscriptions
    kws.subscribe(request=ccnl_notice, data=[trenv.my_htsid])

    # run websocket 
    asyncio.create_task(kws.start_async(on_result=on_result))
    ws_ready.set()

# ---------------------------------
# Local comm handlers, server 
# ---------------------------------
async def handler_shell(reader, writer):
    addr = writer.get_extra_info("peername") # peername: network term / unique in a session
    optlog.info(f"Client connected {addr}")
    try:
        await handle_client(reader, writer, **server_data_dict)
    finally:
        writer.close() # marks the stream as closed.
        await writer.wait_closed() # actual close
        # agent is registered by request (not automatically on connect)
        target = connected_agents.get_agent_card_by_port(addr[1])
        # unsusbcribe everything 
        msg = await subs_manager.remove_agent(target)
        optlog.info(msg)  

        # remove from connected_agents/clien
        msg = await connected_agents.remove(target)
        optlog.info(f"Client disconnected {addr} | {msg}")  

async def start_server():
    await ws_ready.wait()
    server = await asyncio.start_server(handler_shell, HOST, PORT)  
    optlog.info(f"Server listening on {HOST}:{PORT}")
    async with server:  # ensures graceful shutdown
        await server.serve_forever()

import datetime
async def broadcast():
    while True:
        message = datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S")
        message += ' ping from the server --- '
        # print(connected_agents)
        # print(subs_manager.map)
        # print(ka.open_map)
        # print(ka.data_map)
        # print(master_orderlist)
        await dispatch(connected_agents.get_all_agents(), message)
        await asyncio.sleep(15)

async def server():
    async with asyncio.TaskGroup() as tg: 
        tg.create_task(websocket_loop())
        tg.create_task(process_commands())
        tg.create_task(start_server())
        tg.create_task(broadcast())

if __name__ == "__main__":
    try:
        asyncio.run(server())
    except KeyboardInterrupt:
        optlog.info("Server stopped by user (Ctrl+C).\n")


