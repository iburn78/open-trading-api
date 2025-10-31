from core.common.optlog import set_logger
set_logger()

import asyncio
import sys

from core.common.optlog import optlog
from core.model.agent import Agent
from core.strategy.brute_rand import BruteForceRandStrategy

async def main(sw=None): # switch
    if sw == "1":
        A = Agent(id = 'A1', code = '000660', strategy=BruteForceRandStrategy())
        A.define_initial_state(total_allocated_cash=10000000)
        task1 = asyncio.create_task(A.run())  

        B = Agent(id = 'B1', code = '001440', strategy=BruteForceRandStrategy())
        B.define_initial_state(total_allocated_cash=10000000)
        task2 = asyncio.create_task(B.run())  

        await asyncio.sleep(1000)

        A.hardstop_event.set()
        B.hardstop_event.set()

        await asyncio.gather(task1, task2)

    else: 
        C = Agent(id = 'Ci', code = '055490')
        task3 = asyncio.create_task(C.run())  

        await asyncio.sleep(500)

        C.hardstop_event.set()
        await asyncio.gather(task3)


if __name__ == "__main__":
    try:
        asyncio.run(main(sys.argv[1]))
    except KeyboardInterrupt:
        optlog.info("Clients stopped by user (Ctrl+C).\n")
    