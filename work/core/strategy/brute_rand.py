import asyncio
import random

from ..common.optlog import optlog
from ..model.strategy_base import StrategyBase
from ..model.strategy_util import UpdateEvent
from ..kis.ws_data import SIDE, ORD_DVSN 

class BruteForceRandStrategy(StrategyBase):
    """
    Buy / sell shares at a random time
    """
    def __init__(self):
        super().__init__() 
        self.run_once = False
    
    async def on_update(self, update_event: UpdateEvent):
        if update_event != UpdateEvent.PRICE_UPDATE:
            optlog.debug(f"{self.code}-{update_event.name}", name=self.agent_id)

        # q = random.randint(1, 5)
        if self.run_once:
            return
        self.run_once=True

        sc1 = self.create_an_order(side=SIDE.BUY, ord_dvsn=ORD_DVSN.MARKET, price=0, quantity=10)
        sc2 = self.create_an_order(side=SIDE.BUY, ord_dvsn=ORD_DVSN.MARKET, price=0, quantity=10)
        sc3 = self.create_an_order(side=SIDE.BUY, ord_dvsn=ORD_DVSN.LIMIT, price=505000, quantity=5)
        sc4 = self.create_an_order(side=SIDE.BUY, ord_dvsn=ORD_DVSN.LIMIT, price=505000, quantity=5)

        [sc1, sc2, sc3, sc4] = await self.execute_rebind([sc1, sc2, sc3, sc4])
        await asyncio.sleep(random.randint(1, 2))

        # cancel test
        optlog.info(f'cancel order')
        # co1 = sc1.make_a_cancel_order(partial=True, to_cancel_qty=7)
        # co2 = sc2.make_a_cancel_order(partial=True, to_cancel_qty=12)
        co3 = sc3.make_a_cancel_order(partial=True, to_cancel_qty=5)
        co4 = sc4.make_a_cancel_order(partial=True, to_cancel_qty=3)
        [co3, co4] = await self.execute_rebind([co3, co4])

        return
    

    ###_ no agents to dispatch 이후에 시스템 먹통... 