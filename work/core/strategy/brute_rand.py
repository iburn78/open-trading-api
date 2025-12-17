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

        sc1 = self.create_an_order(side=SIDE.BUY, ord_dvsn=ORD_DVSN.LIMIT, price=560000, quantity=q)
        sc2 = self.create_an_order(side=SIDE.BUY, ord_dvsn=ORD_DVSN.LIMIT, price=565000, quantity=q)
        sc3 = self.create_an_order(side=SIDE.BUY, ord_dvsn=ORD_DVSN.LIMIT, price=515000, quantity=q)
        sc4 = sc3.make_a_cancel_order()

        sc =await self.execute([sc1, sc2, sc3, sc4])
        await asyncio.sleep(random.randint(5, 10))
        # cancel test
        optlog.info(f'cancel order')
        co = sc1.make_a_cancel_order(partial=True, new_qty=sc1.quantity-1)
        res = await self.execute(co)
        optlog.info(f'cancel {co.order_no} {co.original_order}: {res}')


        ###_ in case of partial cancel
        ###_ how trn is arrived
        ###_ how to reflect to the order manager and order book: both has to be updated
        return
