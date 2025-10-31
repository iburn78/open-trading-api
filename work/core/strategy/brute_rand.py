import asyncio
import random

from .strategy import StrategyBase, StrategyCommand, UpdateEvent, StrategyFeedback
from ..common.optlog import optlog
from ..kis.ws_data import SIDE, ORD_DVSN 

class BruteForceRandStrategy(StrategyBase):
    """
    Buy shares at a random time
    Sell it when the price up a certain percentage
    """
    def __init__(self):
        super().__init__() 
        asyncio.create_task(self.initiate_strategy())
    
    async def on_update(self, update_event: UpdateEvent, str_feedback: StrategyFeedback = None):
        if str_feedback:
            print(str_feedback)
        q = random.randint(1, 5)
        x = random.randint(0, 1)    
        if x == 0:
            sc = StrategyCommand(side=SIDE.BUY, ord_dvsn=ORD_DVSN.MARKET, quantity=q)
        else:
            sc = StrategyCommand(side=SIDE.SELL, ord_dvsn=ORD_DVSN.MARKET, quantity=q)
        await self.command_signal_queue.put(sc)
        # await asyncio.sleep(random.randint(0, 1))
        optlog.info(self.order_book, name=self.agent_id)
        optlog.debug(self.order_book.get_listings_str(), name=self.agent_id)
        return
