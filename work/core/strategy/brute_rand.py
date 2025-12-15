import asyncio
import random

from ..model.strategy_base import StrategyBase
from ..model.strategy_util import UpdateEvent
from ..kis.ws_data import SIDE, ORD_DVSN 

class BruteForceRandStrategy(StrategyBase):
    """
    Buy / sell shares at a random time
    """
    def __init__(self):
        super().__init__() 
    
    async def on_update(self, update_event: UpdateEvent):
        q = random.randint(1, 5)
        x = random.randint(0, 1)    
        # if x == 0:
            # sc = (side=SIDE.BUY, ord_dvsn=ORD_DVSN.MARKET, quantity=q)
        # else:
            # sc = (side=SIDE.SELL, ord_dvsn=ORD_DVSN.MARKET, quantity=q)
        sent = await self.execute(sc)
        await asyncio.sleep(random.randint(0, 5))
        return
