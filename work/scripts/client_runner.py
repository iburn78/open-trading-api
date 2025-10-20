from core.common.optlog import set_logger
set_logger()

import asyncio
import sys

from core.common.optlog import optlog
from core.model.agent import Agent

async def main(sw=None): # switch
    if sw == "1":
        A = Agent(id = 'A1', code = '000660')
        task1 = asyncio.create_task(A.run())  

        B = Agent(id = 'B1', code = '001440')
        task2 = asyncio.create_task(B.run())  

        async def wait_and_run(agent: Agent):
            await agent.ready_event.wait()
            await agent.enact_strategy()

        asyncio.create_task(wait_and_run(A))
        asyncio.create_task(wait_and_run(B))

        await asyncio.sleep(1000)

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
    