import asyncio

from core.base.settings import Service
from core.base.logger import LogSetup
from core.model.agent import Agent
from core.strategy.brute_rand import BruteForceRandStrategy
from core.strategy.double_up import DoubleUpStrategy
from core.strategy.null_str import NullStr

async def agent_runner(logger):
    AGENT_RUNTIME = 1000 # sec
    # A = Agent(id = 'A1', code = '000660', service=service, dp = 8001, logger=logger, strategy=BruteForceRandStrategy())
    A = Agent(id = 'A3', code = '005930', service=service, dp = 8003, logger=logger, strategy=DoubleUpStrategy())
    A.initialize(init_cash_allocated=100_000_000, init_holding_qty=0, init_avg_price=0, sync_start_date='2026-01-01')

    run_task = asyncio.create_task(A.run())
    await asyncio.sleep(AGENT_RUNTIME)
    A.hardstop_event.set()

    await run_task

if __name__ == "__main__":
    service = Service.DEMO
    logger = LogSetup(service).logger
    try:
        asyncio.run(agent_runner(logger))
    except KeyboardInterrupt:
        logger.info("[AgentRunner] stopped by user (Ctrl+C)\n\n")