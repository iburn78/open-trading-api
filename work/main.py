import kis_auth as ka
from tools import *
import asyncio

# ---------------------------------
# 인증 and Set-up
# ---------------------------------
svr = 'vps' # prod, auto, vps
ka.auth(svr)  # renew_token=True
ka.auth_ws(svr)
trenv = ka.getTREnv()
order_list = OrderList()

# ---------------------------------
# Response handling logic
# ---------------------------------
def on_result(ws, tr_id, result, data_info):
    if get_tr(trenv, tr_id) == 'TradeNotice':
        tn = TradeNotice.from_response(result)
        order_list.process_notice(tn)
                    
# ---------------------------------
# Order creation
# ---------------------------------
def create_order(order_list):
    for i in range(10):
        code = "018000"
        quantity = i*3 + 1 
        price = 1100+10*i
        order = Order(code, "buy", quantity, "limit", price)
        order_list.register(order)

# ---------------------------------
# async main
# ---------------------------------
the_account = Account().acc_load(trenv)
print(the_account)

async def main():
    # Websocket
    kws = ka.KISWebSocket(api_url="/tryitout")

    # subscriptions
    kws.subscribe(request=ccnl_notice, data=[trenv.my_htsid])

    # run websocket until cancelled
    start_task = asyncio.create_task(kws.start_async(on_result=on_result))

    # submit order
    for order in order_list.get_new_orders():
        await asyncio.to_thread(order.submit, trenv)
        await asyncio.sleep(0.5)

    # wait forever
    await asyncio.gather(start_task)


if __name__ == "__main__":
    asyncio.run(main())

