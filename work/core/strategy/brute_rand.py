from dataclasses import dataclass, field
import asyncio
import random

@dataclass
class BruteForceRandStrategy():
    """
    Buy shares at a random time
    Sell it when the price up a certain percentage
    """
    current_price: int = 0
    purchase_price: int = 0
    num_holding: int = 0
    target_return: float = 0.00

    # ('buy', q) or ('sell', None)
    signal_queue = asyncio.Queue() 
    _update_event: asyncio.Event = field(default_factory=asyncio.Event)

    # prevents multiple same kind of alerts to be fired
    # ready_event: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self):
        # self.ready_event.set()
        pass 

    def get_purchase_quantity(self):
        # not initalized yet
        if self.current_price == 0: return 0
        
        # decide quantity
        q = 10 if self.current_price < 20_000 else 1

        return q
    
    async def buy_alert(self):
        while True:
            print('running-----------')
            # await self.ready_event.wait()
            if self.num_holding == 0: 
                q = self.get_purchase_quantity()

                if q > 0:
                    await self.signal_queue.put(('buy', q))

            await asyncio.sleep(random.randint(1, 2))
            
    async def sell_alert(self):
        while True: 
            print('selling-----------')
            print(self.num_holding, self.purchase_price, self.current_price)
            # await self.ready_event.wait()
            await self._update_event.wait() 
            self._update_event.clear()

            if self.num_holding > 0 and self.purchase_price > 0:
                # if (self.current_price - self.purchase_price) / self.purchase_price >= self.target_return:
                await self.signal_queue.put(('sell', 0))
    
    def update(self, price):
        # consider using asyncio._lock if multiple coroutines uses update
        print('strategy update called -----')
        self.current_price = price
        self._update_event.set()

    def holding_update(self, quantity_holding, purchase_price):
        print('strategy holding update called -----')
        self.num_holding = quantity_holding
        self.purchase_price = purchase_price



