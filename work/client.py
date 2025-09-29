from gen_tools import *
get_logger("client", "log/client.log")

from kis_tools import *
from local_comm import *
from agent import *

def create_order():
    new_orders = []
    code = '005930'
    for i in range(3):
        quantity = 9 + 3*i
        price = 82000
        order = Order(code, "buy", quantity, ORD_DVSN.LIMIT, price)
        new_orders.append(order)
    return new_orders

new_orders = create_order()

# toc = new_orders[0]
# a = ReviseCancelOrder(toc.code, toc.side, toc.quantity, toc.ord_dvsn, toc.price, rc=RCtype.CANCEL, all_yn=AllYN.ALL, original_order=toc)

# asyncio.run(send_command('submit_orders', {'data': new_orders}))   
# time.sleep(15)

# a = asyncio.run(send_command('get_account', None))
# print(a['data'])

# a = asyncio.run(send_command('get_orderlist')) 
# print(a['data'])

code = '001440' 
response = asyncio.run(send_command('get_agent', code))

print(response.get('response_status'))
print(response.get('response_data'))



