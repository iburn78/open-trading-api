from gen_tools import *
get_logger("main", "log/main.log")

import kis_auth as ka
from kis_tools import *
from local_comm import *
from strategy import *
from agent import *

# main.py -----------------------------------------------------------
# KIS와의 Communication
# - REST: 1회성 request/response
# - WS: tradenotice 수신
# Localhost Server
# - local client의 request handle
# Account 정보 관리
# - the_account
# - Server에서 정보 읽어옴
# - Update (not yet implemented)
# AgentManager 
# - TradeTarget으로 trade_target 수신
# - trade_target 및 the_account 감안해서 book 생성
# - agents의 보관: agents 
# - agents의 active 여부, 행동 관리 
# - agents의 성과관리 (not yet implemented)

# ---------------------------------
# auth and Set-up
# ---------------------------------
svr = 'vps' # prod, auto, vps
if svr != 'vps':
    cfm = input("Running real trading mode, sure? (Enter svr name): ")
    if cfm != svr:
        log_raise("Check svr ---")

ka.auth(svr)
ka.auth_ws(svr)
trenv = ka.getTREnv()
main_orderlist = OrderList()
ws_ready = asyncio.Event()
command_queue = asyncio.Queue()

# ---------------------------------
# Account
# ---------------------------------
the_account = Account().acc_load(trenv)
optlog.info(the_account)

# ---------------------------------
# Target setting and agent creation
# ---------------------------------
trade_target = TradeTarget(the_account=the_account) # trade_target never changes while running
agent_manager = AgentManager(trade_target=trade_target)

# ---------------------------------
# Variables to share with clients
# ---------------------------------
server_data_dict ={
    'command_queue' : command_queue, 
    'main_orderlist' : main_orderlist, 
    'the_account' : the_account,
    'agent_manager' : agent_manager,
}

# ---------------------------------
# Process orders through the websocket
# ---------------------------------
async def process_commands():
    await ws_ready.wait()
    while True:
        (request_command, request_data) = await command_queue.get()
        if request_command == "cancel_orders":
            await main_orderlist.cancel_all_outstanding(trenv)
            await main_orderlist.closing_check()
        
        elif request_command == "submit_orders":
            if request_data: # list [order, order, ... ]
                optlog.info(f"Trading main got: {request_data}")
                await main_orderlist.submit_orders_and_register(request_data, trenv)

        else:
            log_raise("Undefined:", request_command)
        command_queue.task_done()

# ---------------------------------
# Websocket and response handling logic
# ---------------------------------
async def async_on_result(ws, tr_id, result, data_info):
    if get_tr(trenv, tr_id) == 'TradeNotice': # Domestic stocks
        tn = TradeNotice.from_response(result)
        await main_orderlist.process_notice(tn, trenv)
        optlog.info(tn)
    # to add more tr_id ...
    
    else:
        log_raise(f"Unexpected tr_id {tr_id} delivered")

def on_result(ws, tr_id, result, data_info):
    asyncio.create_task(async_on_result(ws, tr_id, result, data_info))

async def websocket_loop():
    # Websocket
    kws = ka.KISWebSocket(api_url="/tryitout")

    # subscriptions
    kws.subscribe(request=ccnl_notice, data=[trenv.my_htsid])
    # to add more ....

    # run websocket 
    asyncio.create_task(kws.start_async(on_result=on_result))
    ws_ready.set()

# ---------------------------------
# Local comm handlers, server 
# ---------------------------------
async def handler_shell(reader, writer):
    await handle_client(reader, writer, **server_data_dict)

async def start_server():
    await ws_ready.wait()
    server = await asyncio.start_server(handler_shell, HOST, PORT)  # initializing and running in the background
    optlog.info(f"Server listening on {HOST}:{PORT}")
    async with server:  # catches server and manage with closing
        await server.serve_forever() 

async def main():
    await asyncio.gather(
        websocket_loop(),
        process_commands(),
        start_server()
    )

if __name__ == "__main__":
    asyncio.run(main())
