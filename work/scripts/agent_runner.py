from core.common.optlog import set_logger
set_logger()

import asyncio
import sys

from core.common.optlog import optlog
from core.model.agent import Agent
from core.strategy.brute_rand import BruteForceRandStrategy
from core.strategy.double_up import DoubleUpStrategy
from core.strategy.null_str import NullStr

async def main(sw=None): # switch
    if sw == "1":
        # A = Agent(id = 'A4', code = '000660', dp = 8001, strategy=DoubleUpStrategy())
        # A = Agent(id = 'A1', code = '000660', dp = 8001, strategy=NullStr())
        A = Agent(id = 'A5', code = '000660', dp = 8001, strategy=DoubleUpStrategy())

        A.initialize(init_cash_allocated=100_000_000, init_holding_qty=0, init_avg_price=0, sync_start_date='2025-12-15')
        task1 = asyncio.create_task(A.run(), name="str_run_task")  

        await asyncio.sleep(1000)

        A.hardstop_event.set()
        await asyncio.gather(task1)

    elif sw == "2":
        B = Agent(id = 'B2_', code = '000660', dp = 8002, strategy=BruteForceRandStrategy())
        B.initialize(init_cash_allocated=100000000, sync_start_date=None)
        task2 = asyncio.create_task(B.run(), name="str_run_task")  

        await asyncio.sleep(1000)

        B.hardstop_event.set()
        await asyncio.gather(task2)
    

if __name__ == "__main__":
    try:
        asyncio.run(main(sys.argv[1]))
    except KeyboardInterrupt:
        optlog.info("[ClientRunner] Clients stopped by user (Ctrl+C).\n")
    