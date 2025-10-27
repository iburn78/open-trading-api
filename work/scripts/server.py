from core.common.optlog import set_logger
set_logger()

import asyncio
import datetime
from core.common.optlog import optlog, log_raise
from core.common.setup import HOST, PORT
import core.kis.kis_auth as ka
from core.kis.domestic_stock_functions_ws import ccnl_notice
from core.kis.ws_data import get_tr, TransactionNotice, TransactionPrices
from app.comm.comm_handler import handle_client, dispatch
from app.comm.conn_agents import ConnectedAgents
from app.comm.subs_manager import SubscriptionManager
from app.comm.order_manager import OrderManager

# server.py -----------------------------------------------------------
# KIS와의 Communication
# - REST: 1 time request/response
# - WS: tradenotice 등 수신
# Localhost Server
# - local client의 request handle

# ---------------------------------
# auth and set-up
# ---------------------------------
svr = 'vps' # prod, auto, vps
if svr != 'vps':
    cfm_message = input("Running real trading mode, sure? (Enter svr name): ")
    if cfm_message != svr:
        log_raise("Check svr ---")

ka.auth(svr)
ka.auth_ws(svr)
trenv = ka.getTREnv()
ws_ready = asyncio.Event()
command_queue = asyncio.Queue() # to process submit and cancel orders
connected_agents = ConnectedAgents() 
subs_manager = SubscriptionManager()
order_manager = OrderManager()

# ---------------------------------
# Variables to share with clients
# ---------------------------------
server_data_dict ={
    'trenv' : trenv,
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
        # Only agents can submit commands, and agents should be registered already.
        port = writer.get_extra_info("peername")[1] 
        agent = connected_agents.get_agent_card_by_port(port)

        if request_command == "CANCEL_orders":  # agent specific cancel
            await order_manager.cancel_all_outstanding(agent, trenv)
            await order_manager.closing_checker(agent)
        
        elif request_command == "submit_orders":
            if request_data: # list [order, order, ... ] (checked in comm_handler)
                await order_manager.submit_orders_and_register(agent, request_data, trenv)

        else:
            log_raise(f"Undefined: {request_command} ---", name=agent.id)
        command_queue.task_done()

# ---------------------------------
# Websocket and response handling logic
# ---------------------------------
async def async_on_result(ws, tr_id, result, data_info):
    if tr_id is None or tr_id == '':
        log_raise(f"tr_id is None or '': {tr_id} ---")

    if get_tr(trenv, tr_id) == 'TransactionNotice': # Notices to the trade orders
        trn = TransactionNotice.create_object_from_response(result)
        # At this time, an agent who sent the order should already be initially registered in connected_agents.
        # But agent could already dropped out and removed from connected_agents.
        # So need to use order_manager, not the connected_agents directly.
        await order_manager.process_tr_notice(trn, connected_agents, trenv)
        optlog.info(trn) # agent unknown yet
        
    elif get_tr(trenv, tr_id) in ('TransactionPrices_KRX',  'TransactionPrices_Total'): # 실시간 체결가
        trp = TransactionPrices(trprices=result, trenv_env_dv=trenv.env_dv)
        await dispatch(connected_agents.get_target_agents_by_trp(trp), trp)

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
        optlog.info(f"Response: {msg}", name=target.id)  

        # remove from connected_agents/clien
        msg = await connected_agents.remove(target)
        optlog.info(f"Client disconnected {addr} | {msg}", name=target.id)  

async def start_server():
    await ws_ready.wait()
    server = await asyncio.start_server(handler_shell, HOST, PORT)  
    optlog.info(f"Server listening on {HOST}:{PORT}")
    async with server:  # ensures graceful shutdown
        await server.serve_forever()

async def broadcast():
    INTERVAL = 15
    while True:
        await asyncio.sleep(INTERVAL)
        message = datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S")
        message += ' ping from the server --- '

        optlog.info(message)
        await dispatch(connected_agents.get_all_agents(), message)
        # _status_check()

def _status_check():
    # status print possible here
    optlog.debug(connected_agents)
    optlog.debug(subs_manager.map)
    optlog.debug(ka.open_map)
    optlog.debug(ka.data_map)
    optlog.debug(order_manager)

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


