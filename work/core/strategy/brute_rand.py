import asyncio
import random

from ..model.strategy_base import StrategyBase
from ..model.strategy_util import UpdateEvent

class BruteForceRandStrategy(StrategyBase):
    """
    Buy / sell shares at a random time
    """
    def __init__(self):
        super().__init__() 
        self.run_once = False
    
    async def on_update(self, update_event: UpdateEvent):
        if update_event != UpdateEvent.PRICE_UPDATE:
            self.logger.info(f"{self.code}-{update_event.name}", extra={"owner": self.agent_id})

        if self.run_once:
            return
        self.run_once=True

        sc1 = self.market_buy(10)
        sc2 = self.market_buy(20)
        sc3 = self.limit_buy(price=750000, quantity=5) 
        sc4 = self.limit_buy(price=730000, quantity=10) 

        [sc1, sc2, sc3, sc4] = await self.execute_rebind([sc1, sc2, sc3, sc4])
        await asyncio.sleep(random.randint(1, 2))

        # cancel test (example)
        co3 = sc3.make_a_cancel_order(partial=True, to_cancel_qty=5)
        co4 = sc4.make_a_cancel_order(partial=True, to_cancel_qty=3)

        if co3.creation_success and co4.creation_success:
            [co3, co4] = await self.execute_rebind([co3, co4])
        else: 
            self.logger.info(co3.creation_msg, extra={"owner": self.agent_id})
            self.logger.info(co4.creation_msg, extra={"owner": self.agent_id})
