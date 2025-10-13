from gen_tools import logging, optlog, get_logger
get_logger("client", "log/client.log", level=logging.DEBUG)

# from kis_tools import *
# from local_comm import *
from agent import *

# def create_order():
#     new_orders = []
#     code = '001440'
#     for i in range(3):
#         quantity = 9 + 3*i
#         price = 15700
#         order = Order(code, "buy", quantity, ORD_DVSN.LIMIT, price)
#         new_orders.append(order)
#     return new_orders

# new_orders = create_order()

# toc = new_orders[0]
# a = ReviseCancelOrder(toc.code, toc.side, toc.quantity, toc.ord_dvsn, toc.price, rc=RCtype.CANCEL, all_yn=AllYN.ALL, original_order=toc)

# asyncio.run(send_command('submit_orders', {'data': new_orders}))   
# time.sleep(15)

# a = asyncio.run(send_command('get_account', None))
# print(a['data'])

# a = asyncio.run(send_command('get_orderlist')) 
# print(a['data'])


# async def main():

    # client = PersistentClient()
    # await client.connect()

    # # send a command
    # code = '000661' 
    # # code = '000330' 
    # id = 'agent_'+code
    # agent1 = AgentCard(id, code)
    # print(agent1)
    # resp = await client.send_command("register_agent_card", request_data=agent1)
    # # resp = await client.send_command("remove_agent_card", request_data=agent1)
    # print("Response:", resp)

    # # resp = await client.send_command("subscribe_trp_by_agent_id", request_data=id)
    # resp = await client.send_command("unsubscribe_trp_by_agent_id", request_data=id)
    # print("Response:", resp)

    # # The client continues to receive server pushes asynchronously
    # await asyncio.sleep(500)  # keep running to receive server pushes
    # await client.close()

async def main():
    A = Agent(id = 'A1', code = '000660')
    task = asyncio.create_task(A.run())  

    await asyncio.sleep(100)
    A._stop_event.set()
    await task # necessary

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        optlog.info("Client stopped by user (Ctrl+C).\n")
    