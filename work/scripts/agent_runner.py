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
        A = Agent(id = 'A1', code = '000660', dp = 8001, strategy=DoubleUpStrategy())
        # A = Agent(id = 'A1', code = '000660', dp = 8001, strategy=NullStr())

        A.initial_value_setup(init_cash_allocated=100_000_000, init_holding_qty=72, init_avg_price=586629, sync_start_date='2025-12-15')
        task1 = asyncio.create_task(A.run())  

        await asyncio.sleep(1000)

        A.hardstop_event.set()
        await asyncio.gather(task1)

    elif sw == "2":
        B = Agent(id = 'B1', code = '099440', dp = 8002, strategy=DoubleUpStrategy())
        B.initial_value_setup(init_cash_allocated=100000000)
        task2 = asyncio.create_task(B.run())  

        await asyncio.sleep(1000)

        B.hardstop_event.set()
        await asyncio.gather(task2)
    

if __name__ == "__main__":
    try:
        asyncio.run(main(sys.argv[1]))
    except KeyboardInterrupt:
        optlog.info("[ClientRunner] Clients stopped by user (Ctrl+C).\n")
    