from abc import ABC, abstractmethod
import asyncio

from ..common.optlog import log_raise
from ..common.tools import excel_round
from ..kis.ws_data import SIDE, ORD_DVSN
from .price import MarketPrices
from .perf_metric import PerformanceMetric
from .strategy_util import StrategyRequest, StrategyCommand, UpdateEvent, StrategyResponse

class StrategyBase(ABC):
    """
    Subclasses should call:
    def __init__(self): or __post_init__
        super().__init__()

    """
    def __init__(self):
        self.agent_id = None
        self.code = None

        # snapshot data to use in making strategy
        # -----------------------------------------------------------------
        self.mprice: MarketPrices | None = None
        # - can safely assume market price is initialized
        self.pm: PerformanceMetric | None = None 
        # - through pm, access to initial data of the agent possible
        # - self.update_pm() is called on every on_update through on_update_shell
        # -----------------------------------------------------------------

        # Strategy - Agent communication channel (only used in StrategyBase and Agent, internal for both)
        self._command_queue: asyncio.Queue[StrategyCommand | bool] = asyncio.Queue() 
        self._response_queue: asyncio.Queue[StrategyCommand | bool] = asyncio.Queue() 
        self._order_receipt_event: asyncio.Event = asyncio.Event()
        self._price_update_event: asyncio.Event = asyncio.Event()
        self._trn_receive_event: asyncio.Event = asyncio.Event()

        # order history data: ever increasing
        self.failed_to_sent_strategy_command: list = []
        self.sent_strategy_command: list = [] # successfully sent ones 

        # others
        self.strict_API_check_required: bool = False 
        self.str_name = self.__class__.__name__ # subclass name
        self._on_update_lock: asyncio.Lock = asyncio.Lock()

    def link_agent_data(self, agent_id, code, market_prices: MarketPrices, perf_metric: PerformanceMetric, str_API: bool = False):
        self.agent_id = agent_id
        self.code = code
        self.mprice = market_prices  
        self.pm = perf_metric
        self.strict_API_check_required: bool = str_API 

    async def logic_run(self):
        # initial run
        await self.on_update_shell(UpdateEvent.INITIATE)

        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.on_price_update())
            tg.create_task(self.on_trn_receive())
            tg.create_task(self.on_order_receive())

    async def on_price_update(self):
        while True:
            await self._price_update_event.wait()
            await self.on_update_shell(UpdateEvent.PRICE_UPDATE)
            self._price_update_event.clear()

    async def on_trn_receive(self):
        while True:
            await self._trn_receive_event.wait()
            await self.on_update_shell(UpdateEvent.TRN_RECEIVE)
            self._trn_receive_event.clear()

    async def on_order_receive(self):
        while True:
            # submission result already reflected in OrderBook
            await self._order_receipt_event.wait()
            await self.on_update_shell(UpdateEvent.ORDER_RECEIVE)
            self._order_receipt_event.clear()

    async def on_update_shell(self, update_event: UpdateEvent):
        async with self._on_update_lock:
            self.pm.update() # for market price update and corresponding data
            await self.on_update(update_event)

    @abstractmethod
    async def on_update(self, update_event: UpdateEvent):
        '''
        ----------------------------------------------------------------------------------------------------------------
        this runs on events: initiate / price / trn / order_receive
        - however, this does not run on every single event 
        - this is intended behavior as update only needs to be called once
            * if two trns received almost same time (e.g., 011, 022), event/wait/clear mechanism may not trigger twice
            * on_update runs frequently anyway
        ----------------------------------------------------------------------------------------------------------------
        - strategy should be based on the snapshot(states) of the agent: pm and mprice
            * pm.cur_price can be an (weighted) average price (if trp sends multiple lines of transaction records)
        ----------------------------------------------------------------------------------------------------------------
        - on_update should not await inside; fast deterministic decisions should be made 
            * if it takes time, pm could not be correct anymore (outdated)
        ----------------------------------------------------------------------------------------------------------------
        - on_update is called at the last stage after processing all the price / notice / order etc
            * so there can be some time gap 
            * locks may delay further the on_update call
        '''
        pass

    async def _send_str_command(self, str_command: StrategyCommand) -> StrategyResponse:
        await self._command_queue.put(str_command)
        response: StrategyResponse = await self._response_queue.get()
        if response.request != str_command.request:
            log_raise(f'StretegyResponse request type {response.request} not match with orignial command {str_command.request}', name=self.agent_id)
        return response.response_data

    # True if order submitted, False if not (either at the validation level, or from the API level)
    # failed to sent orders are saved too
    async def order_submit(self, str_command: StrategyCommand):
        if str_command.request != StrategyRequest.ORDER:
            log_raise(f'[Strategy] StrategyRequest type not correctly set as {str_command.request}, reset to ORDER necessary', name=self.agent_id)
        valid: bool = await self.validate_strategy_order(str_command)
        if not valid:
            self.failed_to_sent_strategy_command.append(str_command)
            return False
        else:
            sent: bool = await self._send_str_command(str_command) 
            if sent:
                self.sent_strategy_command.append(str_command)
            else:
                self.failed_to_sent_strategy_command.append(str_command)
            return sent

    # -----------------------------------------------------------------
    # validators
    # -----------------------------------------------------------------
    # internal logic checking before sending strategy command to the API server
    async def validate_strategy_order(self, str_cmd: StrategyCommand) -> bool:
        """
        Validates a strategy order command before execution.
    
        Checks:
        - Sufficient cash for buy orders
        - Sufficient holdings for sell orders  
        - Market price availability for market orders
        """
        self.pm.update() # final check, so update
        if str_cmd.side == SIDE.BUY:
            if str_cmd.ord_dvsn == ORD_DVSN.MARKET:
                # [check 1] check if agent has enough cash (stricter cond-check)
                exp_amount = excel_round(str_cmd.quantity*self.mprice.current_price) # best guess with current price, and approach conservatively with margin
                if exp_amount > self.pm.max_market_buy_amt:
                    return False

                # [check 2] check if the account API allows it 
                if self.strict_API_check_required:
                    check_command = StrategyCommand(request=StrategyRequest.PSBL_QUANTITY, ord_dvsn=str_cmd.ord_dvsn, price=str_cmd.price)
                    q_ = await self._send_str_command(str_command=check_command)
                    if str_cmd.quantity > q_:
                        return False

            else: # LIMIT buy
                if str_cmd.quantity*str_cmd.price > self.pm.max_limit_buy_amt:
                    return False
        else: # str_cmd.side == SIDE.SELL:
            if str_cmd.quantity > self.pm.max_sell_qty:
                return False

        return True
        
