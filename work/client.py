from common.optlog import set_logger
set_logger()

import asyncio

from common.optlog import optlog
from model.agent import Agent

import sys
async def main(sw=None):
    if sw == "1":
        A = Agent(id = 'A1', code = '000660')
        task1 = asyncio.create_task(A.run())  

        B = Agent(id = 'B1', code = '001440')
        task2 = asyncio.create_task(B.run())  


        await A._ready_event.wait()  # wait until .close() is called
        order = A.make_order()
        print(order)
        resp = await A.client.send_command("submit_orders", request_data=[order])
        optlog.info(resp.get('response_status'))


        await asyncio.sleep(100)

        A._stop_event.set()
        B._stop_event.set()

        await asyncio.gather(task1, task2)

    else: 
        C = Agent(id = 'C1', code = '006400')
        task3 = asyncio.create_task(C.run())  

        await asyncio.sleep(100)

        C._stop_event.set()
        await asyncio.gather(task3)


if __name__ == "__main__":
    try:
        asyncio.run(main(sys.argv[1]))
    except KeyboardInterrupt:
        optlog.info("Client stopped by user (Ctrl+C).\n")
    