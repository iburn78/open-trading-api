from gen_tools import logging, optlog, get_logger, log_raise, HOST, PORT
get_logger("server", "log/server.log", level=logging.DEBUG)

import asyncio
import kis_auth as ka
from domestic_stock_functions_ws import ccnl_notice
from kis_tools import get_tr, OrderList, TransactionNotice, TransactionPrices
from command_handlers import handle_client, broadcast
from strategy import *
from agent import ConnectedAgents

# server.py -----------------------------------------------------------
# KIS와의 Communication
# - REST: 1회성 request/response
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
master_orderlist = OrderList()
ws_ready = asyncio.Event()
command_queue = asyncio.Queue() # to process submit and cancel orders
connected_agents = ConnectedAgents() 

# ---------------------------------
# Variables to share with clients
# ---------------------------------
server_data_dict ={
    'trenv' : trenv,
    'connected_agents' : connected_agents,
    'master_orderlist' : master_orderlist, 
    'command_queue' : command_queue, 
    '_kws': None, # later assigned dynamically
}

# ---------------------------------
# Process orders through the websocket
# ---------------------------------
async def process_commands():
    await ws_ready.wait()
    while True:
        (request_command, request_data) = await command_queue.get()
        if request_command == "CANCEL_orders":
            await master_orderlist.cancel_all_outstanding(trenv)
            await master_orderlist.closing_checker()
        
        elif request_command == "submit_orders":
            if request_data: # list [order, order, ... ]
                optlog.debug(f"Trading server got: {request_data}")
                await master_orderlist.submit_orders_and_register(request_data, trenv)

        else:
            log_raise(f"Undefined: {request_command} ---")
        command_queue.task_done()

# ---------------------------------
# Websocket and response handling logic
# ---------------------------------

async def async_on_result(ws, tr_id, result, data_info):
    if tr_id is None or tr_id == '':
        log_raise(f"tr_id is None or '': {tr_id} ---")

    if get_tr(trenv, tr_id) == 'TransactionNotice': # Notices to my trade orders
        trn = TransactionNotice.from_response(result)
        await master_orderlist.process_tr_notice(trn, trenv)
        optlog.debug(trn)
    elif get_tr(trenv, tr_id) in ('TransactionPrices_KRX',  'TransactionPrices_Total'): # 실시간 체결가
        trp = TransactionPrices(trprices=result)
        await connected_agents.process_tr_prices(trp)
        ###################### NEED REVIEW 
        code = trp.trprices['MKSC_SHRN_ISCD'].iat[0]
        optlog.debug(trp.trprices.to_string())
        await broadcast(clients, trp)
    # to add more tr_id ...
    else:
        log_raise(f"Unexpected tr_id {tr_id} received ---")

def on_result(ws, tr_id, result, data_info):
    asyncio.create_task(async_on_result(ws, tr_id, result, data_info))

async def websocket_loop():
    kws = ka.KISWebSocket(api_url="/tryitout")
    server_data_dict['_kws'] = kws

    # default subscriptions
    kws.subscribe(request=ccnl_notice, data=[trenv.my_htsid])

    # run websocket 
    asyncio.create_task(kws.start_async(on_result=on_result))
    ws_ready.set()

# ---------------------------------
# Local comm handlers, server 
# ---------------------------------
clients = set() # treats duplicates automatically

async def handler_shell(reader, writer):
    clients.add(writer)
    addr = writer.get_extra_info("peername") # peername: network term / unique in a session
    optlog.info(f"Connected by {addr}")
    try:
        await handle_client(reader, writer, **server_data_dict)
    finally:
        clients.discard(writer)
        writer.close() # marks the stream as closed.
        await writer.wait_closed() # actual close
        #### Assign name #### 
        optlog.info(f"Client {addr} disconnected")  # intentional

async def start_server():
    await ws_ready.wait()
    server = await asyncio.start_server(handler_shell, HOST, PORT)  
    optlog.info(f"Server listening on {HOST}:{PORT}")
    async with server:  # ensures graceful shutdown
        await server.serve_forever()

import datetime
async def broadcast_simul():
    while True:
        message = datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S")
        message += ' some random broadcast --- '
        print('to broadcast: ', message)
        print('agent connected')
        print(connected_agents)
        print('open map')
        print(ka.open_map)
        print('data map')
        print(ka.data_map)
        await broadcast(clients, message)
        await asyncio.sleep(30)

async def server():
    async with asyncio.TaskGroup() as tg: 
        tg.create_task(websocket_loop())
        tg.create_task(process_commands())
        tg.create_task(start_server())
        tg.create_task(broadcast_simul())

if __name__ == "__main__":
    try:
        asyncio.run(server())
    except KeyboardInterrupt:
        optlog.info("Server stopped by user (Ctrl+C).\n")
