from gen_tools import *
get_logger("main", "log/main.log")

import kis_auth as ka
from kis_tools import *
from local_comm import *

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
# the_account = Account().acc_load(trenv)
# optlog.info(the_account)

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
# Process orders through the websocket
# ---------------------------------
async def process_commands():
    await ws_ready.wait()
    while True:
        command = await command_queue.get()
        if command is CANCEL:
            await main_orderlist.cancel_all_outstanding(trenv)
            await main_orderlist.closing_check()
        elif isinstance(command, list):
            if command: 
                # in case command is a list of orders
                if all(isinstance(item, Order) for item in command): 
                    optlog.info(f"Trading main got: {command}")
                    await main_orderlist.submit_orders_and_register(command, trenv)
                else: 
                    pass 
        else:
            log_raise("Undefined:", command)
        command_queue.task_done()

# ---------------------------------
# Local comm handlers, server 
# ---------------------------------
async def handler(reader, writer):
    await handle_client(reader, writer, 
        # kwargs ------
        command_queue=command_queue, 
        main_orderlist=main_orderlist, 
        trenv=trenv
        )

async def start_server():
    await ws_ready.wait()
    server = await asyncio.start_server(handler, HOST, PORT)  # initializing and running in the background
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
