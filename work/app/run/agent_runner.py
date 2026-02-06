import asyncio

from core.base.settings import Service
from core.base.logger import LogSetup
from core.model.agent import Agent
from core.strategy.brute_rand import BruteForceRandStrategy
from core.strategy.double_up import DoubleUpStrategy
from core.strategy.null_str import NullStr
from core.strategy.vol_purchase import VolumePurchase

async def agent_runner(logger):
    AGENT_RUNTIME = 10000 # sec

    param = {'pl': 0.3, 'ps': 0.1, 'vl': 1.3, 'vs': 1.1}

    A1 = Agent(id = 'A1', code = '005930', service=service, dp = 8001, logger=logger, strategy=VolumePurchase(aggr_delta_sec=1, **param))
    A2 = Agent(id = 'A2', code = '005930', service=service, dp = 8002, logger=logger, strategy=VolumePurchase(aggr_delta_sec=5, **param))
    B1 = Agent(id = 'B1', code = '000660', service=service, dp = 8003, logger=logger, strategy=VolumePurchase(aggr_delta_sec=1, **param))
    B2 = Agent(id = 'B2', code = '000660', service=service, dp = 8004, logger=logger, strategy=VolumePurchase(aggr_delta_sec=5, **param))

    A1.initialize(init_cash_allocated=100_000_000, init_holding_qty=0, init_avg_price=0, sync_start_date='2026-01-30')
    A2.initialize(init_cash_allocated=100_000_000, init_holding_qty=0, init_avg_price=0, sync_start_date='2026-01-30')
    B1.initialize(init_cash_allocated=100_000_000, init_holding_qty=0, init_avg_price=0, sync_start_date='2026-01-30')
    B2.initialize(init_cash_allocated=100_000_000, init_holding_qty=0, init_avg_price=0, sync_start_date='2026-01-30')

    agents = [A1, A2, B1, B2]
    async with asyncio.TaskGroup() as tg:
        for agent in agents:
            tg.create_task(agent.run())

        await asyncio.sleep(AGENT_RUNTIME)

        A1.hardstop_event.set()
        A2.hardstop_event.set()
        B1.hardstop_event.set()
        B2.hardstop_event.set()

if __name__ == "__main__":
    service = Service.DEMO
    logger = LogSetup(service).logger
    try:
        asyncio.run(agent_runner(logger))
    except KeyboardInterrupt:
        logger.info("[AgentRunner] stopped by user (Ctrl+C)\n\n")