from dataclasses import dataclass, field
import asyncio
import random

from .strategy import StrategyBase

@dataclass
class SteadyPurchase(StrategyBase):
    """
    Purchase strategy to reach target quantity steadily over time.

    """
    # refer back to agent to acess the data 
    target_quantity: int = 0
    purchase_interval_sec: int = 60
    max_purchase_quantity: int = 20

    num_holding: int = 0
    purchase_price: int = 0

    # ('buy', q) or ('sell', None)
    signal_queue = asyncio.Queue()

    def _get_purchase_quantity(self):
        q = random.randint(1, self.max_purchase_quantity)

        return q

    async def buy_alert(self):
        while True:
            print('running SP-----------')
            # await self.ready_event.wait()
            if self.num_holding == 0: 
                q = self._get_purchase_quantity()

                if q > 0:
                    await self.signal_queue.put(('buy', q))

            await asyncio.sleep(random.randint(1, 2))
            
    async def sell_alert(self):
        return 

    def update(self, price):
        self.current_price = price

    def holding_update(self, quantity_holding, purchase_price):
        self.num_holding = quantity_holding
        self.purchase_price = purchase_price