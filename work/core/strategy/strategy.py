from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import asyncio

from ..model.order_book import OrderBook
from ..model.price import MarketPrices
from ..kis.ws_data import SIDE, ORD_DVSN, EXCHANGE

@dataclass
class StrategyCommand:
    side: SIDE | None = None
    ord_dvsn: ORD_DVSN | None = None
    quantity: int = 0
    price: int = 0 

    # optional
    exchange: EXCHANGE = EXCHANGE.SOR
    
    # additional data
    data: dict = field(default_factory=dict)

class UpdateEvent(Enum):   
    PRICE_UPDATE = 'price_update'
    ORDER_UPDATE = 'order_update'
    INITIATE = 'initiate'

class StrategyBase(ABC):
    """
    normal subclasses need: 
        def __init__(self):
            super().__init__()

    dataclass subclases need: 
        def __post_init__(self):
            super().__init__() 
    """
    def __init__(self):
        self.signal_queue: asyncio.Queue[StrategyCommand] = asyncio.Queue() 
        self.price_update_event: asyncio.Event = asyncio.Event()
        self.order_update_event: asyncio.Event = asyncio.Event()

        self.agent_id = None
        self.order_book: OrderBook | None = None
        self.market_prices: MarketPrices | None = None

    def agent_data_setup(self, agent_id, order_book: OrderBook, market_prices: MarketPrices):
        self.agent_id = agent_id
        self.order_book = order_book
        self.market_prices = market_prices  

    async def logic_run(self):
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.on_price_update())
            tg.create_task(self.on_order_update())

    async def on_price_update(self):
        while True:
            await self.price_update_event.wait()
            await self.on_update(UpdateEvent.PRICE_UPDATE)
            self.price_update_event.clear()

    async def on_order_update(self):
        while True:
            await self.order_update_event.wait()
            await self.on_update(UpdateEvent.ORDER_UPDATE)
            self.order_update_event.clear()

    async def initiate_strategy(self):
        # may add this to __init__ if needed
        await self.on_update(UpdateEvent.INITIATE)

    @abstractmethod
    async def on_update(self, update_event: UpdateEvent):
        pass


