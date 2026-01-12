import asyncio

from core.base.settings import Service
from core.base.logger import LogSetup
from core.model.agent import Agent
from core.strategy.brute_rand import BruteForceRandStrategy
from core.strategy.double_up import DoubleUpStrategy
from core.strategy.null_str import NullStr

async def agent_runner(logger):
    A = Agent(id = 'A7', code = '000660', service=service, dp = 8002, logger=logger, strategy=BruteForceRandStrategy())
    A.initialize(init_cash_allocated=100_000_000, init_holding_qty=0, init_avg_price=0, sync_start_date='2026-01-01')

    async with asyncio.TaskGroup() as tg:
        tg.create_task(A.run())

    await asyncio.sleep(1000)
    A.hardstop_event.set()

if __name__ == "__main__":
    service = Service.DEMO
    logger = LogSetup(service).logger
    try:
        asyncio.run(agent_runner(logger))
    except KeyboardInterrupt:
        logger.info("[AgentRunner] stopped by user (Ctrl+C)\n\n")