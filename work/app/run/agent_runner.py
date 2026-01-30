import asyncio

from core.base.settings import Service
from core.base.logger import LogSetup
from core.model.agent import Agent
from core.strategy.brute_rand import BruteForceRandStrategy
from core.strategy.double_up import DoubleUpStrategy
from core.strategy.null_str import NullStr
from core.strategy.vol_purchase import VolumePurchase

async def agent_runner(logger):
    AGENT_RUNTIME = 2000 # sec
    ###_ check for code if vaild
    A = Agent(id = 'A1', code = '005930', service=service, dp = 8001, logger=logger, strategy=VolumePurchase())
    B = Agent(id = 'B1', code = '000660', service=service, dp = 8002, logger=logger, strategy=VolumePurchase())

    A.initialize(init_cash_allocated=100_000_000, init_holding_qty=0, init_avg_price=0, sync_start_date='2026-01-30')
    B.initialize(init_cash_allocated=100_000_000, init_holding_qty=0, init_avg_price=0, sync_start_date='2026-01-30')

    agents = [A, B]
    async with asyncio.TaskGroup() as tg:
        for agent in agents:
            tg.create_task(agent.run())

        await asyncio.sleep(AGENT_RUNTIME)

        A.hardstop_event.set()
        B.hardstop_event.set()

if __name__ == "__main__":
    service = Service.DEMO
    logger = LogSetup(service).logger
    try:
        asyncio.run(agent_runner(logger))
    except KeyboardInterrupt:
        logger.info("[AgentRunner] stopped by user (Ctrl+C)\n\n")