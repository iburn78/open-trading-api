import asyncio
import sys

from core.base.settings import Service
from core.base.logger import LogSetup
from core.model.agent import Agent
from core.strategy.brute_rand import BruteForceRandStrategy
from core.strategy.double_up import DoubleUpStrategy
from core.strategy.null_str import NullStr

async def main(logger, sw=None): # switch
    if sw == "1":
        # A = Agent(id = 'A4', code = '000660', dp = 8001, strategy=DoubleUpStrategy())
        # A = Agent(id = 'A1', code = '000660', dp = 8001, strategy=NullStr())
        A = Agent(id = 'A5', code = '000660', service=service, dp = 8001, logger=logger, strategy=DoubleUpStrategy())

        A.initialize(init_cash_allocated=100_000_000, init_holding_qty=0, init_avg_price=0, sync_start_date='2025-12-21')
        task1 = asyncio.create_task(A.run())

        try:
            await asyncio.sleep(1000)
        finally:
            A.hardstop_event.set()
            await asyncio.gather(task1)

    elif sw == "2":
        B = Agent(id = 'B2_', code = '000660', service=service, dp = 8002, logger=logger, strategy=BruteForceRandStrategy())
        B.initialize(init_cash_allocated=100000000, sync_start_date=None)
        task2 = asyncio.create_task(B.run())

        try:
            await asyncio.sleep(1000)
        finally:
            B.hardstop_event.set()
            await asyncio.gather(task2)
    

if __name__ == "__main__":
    service = Service.DEMO
    logger = LogSetup(service).logger
    try:
        asyncio.run(main(logger, sys.argv[1]))
    except KeyboardInterrupt:
        logger.info("[AgentRunner] stopped by user (Ctrl+C).\n")
    