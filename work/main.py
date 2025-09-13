import kis_auth as ka
from tools import *
import sys
import pickle

# ---------------------------------
# 인증 and Set-up
# ---------------------------------
svr = 'vps' # prod, auto, vps
ka.auth(svr)  # renew_token=True
ka.auth_ws(svr)
trenv = ka.getTREnv()
main_orderlist = OrderList()

# ---------------------------------
# Account
# ---------------------------------
# the_account = Account().acc_load(trenv)
# print(the_account)

# ---------------------------------
# Order creation
# ---------------------------------

with open('data.pkl', 'rb') as f:
    data_dict = pickle.load(f)
to_order = data_dict['codelist_summary']['price'].astype(int)
to_order = to_order.loc[to_order > 1200]

def create_order():
    new_orders = []
    code = '001440'
    for i in range(3):
        quantity = 10+i*3
        price = 16000+i*20
        order = Order(code, "buy", quantity, "limit", price)
        new_orders.append(order)
    return new_orders

new_orders = create_order()

# ---------------------------------
# Response handling logic
# ---------------------------------
async def async_on_result(ws, tr_id, result, data_info):
    if get_tr(trenv, tr_id) == 'TradeNotice': # Domestic stocks
        tn = TradeNotice.from_response(result)
        await main_orderlist.process_notice(tn)
        print(tn)
    else:
        log_raise(f"Unexpected tr_id {tr_id} delivered")

def on_result(ws, tr_id, result, data_info):
    asyncio.create_task(async_on_result(ws, tr_id, result, data_info))

code = '001440'
o = Order(code, 'buy', 10, ORD_DVSN.LIMIT, 10)
o.order_no = '0000007247'
o.org_no = '00950'
a = ReviseCancelOrder(code, 'buy', 0, 'limit', 10, rc = RCtype.CANCEL, all_yn=AllYN.ALL, original_order=o)
# ---------------------------------
# async main
# ---------------------------------
async def main():
    # Websocket
    kws = ka.KISWebSocket(api_url="/tryitout")

    # subscriptions
    kws.subscribe(request=ccnl_notice, data=[trenv.my_htsid])

    # run websocket until cancelled
    start_task = asyncio.create_task(kws.start_async(on_result=on_result))
    await async_sleep(trenv)

    # submit order
    await main_orderlist.submit_orders_and_register(trenv, new_orders)

    # revise-cancel logic
    rc_orders = [a]

    await main_orderlist.submit_orders_and_register(trenv, rc_orders)
    await main_orderlist.cancel_all_outstanding(trenv)

    # closing 
    await main_orderlist.closing_check()

    print(main_orderlist)

    # wait forever
    await asyncio.gather(start_task)

if __name__ == "__main__":
    asyncio.run(main())
