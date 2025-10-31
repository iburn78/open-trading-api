from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import asyncio

from ..model.order_book import OrderBook
from ..model.price import MarketPrices
from ..model.perf_metric import PerformanceMetric
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

class FeedbackKind(Enum):
    ORDER = 'order'
    STR_COMMAND = 'str_command'

@dataclass
class StrategyFeedback:
    kind: FeedbackKind | None = None # specifies the object type
    obj: object | None = None
    message: str | None = None

    # additional data
    data: dict = field(default_factory=dict)

class UpdateEvent(Enum):   
    INITIATE = 'initiate'
    PRICE_UPDATE = 'price_update'
    ORDER_UPDATE = 'order_update'
    FEEDBACK = 'feedback'

class StrategyBase(ABC):
    """
    Subclasses should implement:

    def __init__(self): or __post_init__
        super().__init__()
        asyncio.create_task(self.initiate_strategy())

    Subclasses should implement in on_update()
    - logic for each UpdateEvent variables: Price update, Order update, Feedback         
    - Feedback is received only when the order isn't processed

    """
    def __init__(self):
        self.command_signal_queue: asyncio.Queue[StrategyCommand] = asyncio.Queue() 
        self.command_feedback_queue: asyncio.Queue[StrategyFeedback] = asyncio.Queue() 
        self.price_update_event: asyncio.Event = asyncio.Event()
        self.order_update_event: asyncio.Event = asyncio.Event()

        self.agent_id = None
        self.code = None
        self.order_book: OrderBook | None = None
        self.market_prices: MarketPrices | None = None
        self.agent_pm: PerformanceMetric | None = None # through pm, strategy itself can access initial data of the agent

    def agent_data_setup(self, agent_id, code, order_book: OrderBook, market_prices: MarketPrices, perf_metric: PerformanceMetric):
        self.agent_id = agent_id
        self.code = code
        self.order_book = order_book
        self.market_prices = market_prices  
        self.agent_pm = perf_metric

    async def logic_run(self):
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.on_price_update())
            tg.create_task(self.on_order_update())
            tg.create_task(self.on_feedback())

    async def on_price_update(self):
        while True:
            await self.price_update_event.wait()
            await self.on_update(UpdateEvent.PRICE_UPDATE)
            self.price_update_event.clear()

    async def on_order_update(self): # order update signal can be lost... only here... 
        while True:
            await self.order_update_event.wait()
            await self.on_update(UpdateEvent.ORDER_UPDATE)
            self.order_update_event.clear()

    async def on_feedback(self):
        while True:
            str_feedback = await self.command_feedback_queue.get()
            self.command_feedback_queue.task_done()
            await self.on_update(UpdateEvent.FEEDBACK, str_feedback=str_feedback)

    async def initiate_strategy(self):
        await self.on_update(UpdateEvent.INITIATE)

    @abstractmethod
    async def on_update(self, update_event: UpdateEvent, str_feedback: StrategyFeedback = None):
        pass


