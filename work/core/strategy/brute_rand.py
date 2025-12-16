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
        self.fresh_start_over = True
    
    async def on_update(self, update_event: UpdateEvent):
        if update_event != UpdateEvent.PRICE_UPDATE:
            optlog.debug(f"{self.code}-{update_event.name}", name=self.agent_id)

        q = random.randint(1, 5)
        # choice = random.randint(0, 1)    
        # if choice == 0:
        sc = self.create_an_order(side=SIDE.BUY, ord_dvsn=ORD_DVSN.LIMIT, price=14500, quantity=q)
        # else:
        #     sc = self.create_an_order(side=SIDE.SELL, ord_dvsn=ORD_DVSN.LIMIT, price=580_000, quantity=q)

        sc =await self.execute(sc)
        optlog.info(f'{sc}:, {sc.org_no}')
        await asyncio.sleep(random.randint(5, 10))
        # # cancel test
        # optlog.info(f'cancel order')
        # co = sc.make_a_cancel_order()
        # res = await self.execute(co)
        # optlog.info(f'cancel {co.order_no} {co.original_order}: {res}')


        ###_ study logs... why not complaining on the lost connection etc... 
        return
