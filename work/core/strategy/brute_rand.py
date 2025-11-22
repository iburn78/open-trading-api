import asyncio
import random

from .strategy import StrategyBase
from ..model.strategy_util import StrategyCommand, UpdateEvent
from ..common.optlog import optlog
from ..kis.ws_data import SIDE, ORD_DVSN 

class BruteForceRandStrategy(StrategyBase):
    """
    Buy / sell shares at a random time
    Test purpose strategy
    """
    def __init__(self):
        super().__init__() 
    
    ###_ strategy should check if this is mock str or not 
    async def on_update(self, update_event: UpdateEvent):

        q = random.randint(1, 5)
        x = random.randint(0, 1)    
        if x == 0:
            sc = StrategyCommand(side=SIDE.BUY, ord_dvsn=ORD_DVSN.MARKET, quantity=q)
        else:
            sc = StrategyCommand(side=SIDE.SELL, ord_dvsn=ORD_DVSN.MARKET, quantity=q)
        sent = await self.order_submit(sc)
        await asyncio.sleep(random.randint(0, 5))
        optlog.info(self.pm.order_book, name=self.agent_id)
        optlog.debug(self.pm.order_book.get_listings_str(), name=self.agent_id)
        return
