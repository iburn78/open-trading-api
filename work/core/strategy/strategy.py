from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import asyncio

from ..model.order_book import OrderBook
from ..model.price import PriceRecords
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


class StrategyBase(ABC):
    def __init__(self):
        self.signal_queue: asyncio.Queue[StrategyCommand] = asyncio.Queue() 
        self._price_update_event: asyncio.Event = asyncio.Event()
        self._order_update_event: asyncio.Event = asyncio.Event()

        self.order_book: OrderBook | None = None
        self.price_book: PriceRecords | None = None

    def agent_data_setup(self, order_book: OrderBook, price_book: PriceRecords):
        self.order_book = order_book
        self.price_book = price_book  

    ##### FIGURE OUT WHO TRIGGERS THIS EVENT #####

    # TransactionPrices received event
    def price_updated(self):
        self._price_update_event.set()

    # TransactionNotice received event
    def order_updated(self):
        self._price_update_event.set()

    async def logic_run(self):
        while True:
            await self._update_event.wait()
            self._update_event.clear()
            self.strategy_logic()

    @abstractmethod
    async def strategy_logic(self):
        pass



