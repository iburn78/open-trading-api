from abc import ABC, abstractmethod
import asyncio

from .perf_metric import PerformanceMetric
from .strategy_util import UpdateEvent
from .order import Order, CancelOrder
from .bar import BarAggregator, BarSeries, Bar
from .bar_analysis import MarketEvent, BarAnalyzer
from .dashboard import DashBoard
from ..base.tools import excel_round
from ..kis.kis_tools import SIDE, MTYPE, EXG

class StrategyBase(ABC):
    """
    Subclasses should call:
    def __init__(self): or __post_init__
        super().__init__()

    """
    def __init__(self): 
        self.agent_id = None
        self.code = None
        self.logger = None
        self.dashboard: DashBoard = None
        self.submit_order = None # callback assigned by agent

        # snapshot data to use in making strategy
        # -----------------------------------------------------------------
        self.pm: PerformanceMetric | None = None 
        # - through pm, access to initial data of the agent possible
        # -----------------------------------------------------------------
        self.pending_strategy_orders: dict[str, asyncio.Future] = {}
        self.lazy_run: bool = True

        # Strategy - Agent communication channel (only used in StrategyBase and Agent - internal for both)
        self._price_update_event: asyncio.Event = asyncio.Event()
        self._trn_receive_event: asyncio.Event = asyncio.Event()

        # market price event channel
        self.market_signals: asyncio.Queue = asyncio.Queue()
        self.last_market_signal: MarketEvent | None = None
        self.bar_series = BarSeries() # default 1 sec
        self.bar_aggr = BarAggregator(bar_series=self.bar_series) # default 10 sec, but adjustable through reset()
        self.bar_analyzer = BarAnalyzer(self.bar_aggr, self.market_signals)
        self.bar_analyzer.on_bar_update = self.on_bar_update # strategy-as-callback

        # others
        self.str_name = self.__class__.__name__ # subclass name
        self._on_update_lock: asyncio.Lock = asyncio.Lock()

    async def logic_run(self):
        # initial run
        await self.on_update_shell(UpdateEvent.INITIATE)

        while True:
            self._price_update_event.clear() # does not run on every price change
            # choose which to start fresh waiting 
            if self.lazy_run: # if True, strategy does not run on every trn: only reacts to new trns
                self._trn_receive_event.clear() 

            price_task = asyncio.create_task(self._price_update_event.wait())
            trn_task   = asyncio.create_task(self._trn_receive_event.wait())
            market_signals_task = asyncio.create_task(self.market_signals.get())

            done, pending = await asyncio.wait(
                {price_task, trn_task, market_signals_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()

            if self._price_update_event.is_set():
                self._price_update_event.clear()
                await self.on_update_shell(UpdateEvent.PRICE_UPDATE)

            if self._trn_receive_event.is_set():
                self._trn_receive_event.clear()
                self.logger.info(self.pm, extra={"owner": self.agent_id})
                await self.on_update_shell(UpdateEvent.TRN_RECEIVE)
            
            if market_signals_task in done: 
                self.last_market_signal: MarketEvent = market_signals_task.result()
                self.logger.info(self.last_market_signal, extra={"owner": self.agent_id})
                await self.on_update_shell(UpdateEvent.MARKET_EVENT)

    async def on_update_shell(self, update_event: UpdateEvent):
        try:
            async with self._on_update_lock:
                await self.on_update(update_event)
        except Exception as e:
            self.logger.error(f"[Strategy] on_update failed ({update_event.name}): {e}", extra={"owner": self.agent_id}, exc_info=True)
            raise asyncio.CancelledError

    def on_bar_update(self):
        # - to be defined in subclasses
        # - not an abstractmethod, cause it is not required to be used
        # 1) do analysis
        # 2) create MarketEvent instance
        # 3) call self.send_if_event(MarketEvent)
        if self.dashboard: 
            self.dashboard.send_bars(self.bar_analyzer.bars)

    @abstractmethod
    async def on_update(self, update_event: UpdateEvent):
        '''
        ----------------------------------------------------------------------------------------------------------------
        this runs on events: initiate / price / trn / order_receive
        - important: this does run on every trn and order receipt event, but not on price (default, but can choose)
        - this is intended behavior as update only needs to be called once
            * if two trns received almost same time (e.g., 011, 022), event/wait/clear mechanism may not trigger twice
            * on_update runs frequently anyway
        ----------------------------------------------------------------------------------------------------------------
        - strategy should be based on the snapshot(states) of the agent: pm 
        ----------------------------------------------------------------------------------------------------------------
        - on_update should not await inside; fast deterministic decisions should be made 
            * if it takes time, pm could not be correct anymore (outdated)
        ----------------------------------------------------------------------------------------------------------------
        - on_update is called at the last stage after processing all the price / notice / order etc
            * so there can be some time gap 
            * locks may delay further the on_update call
        '''
        pass

    # ---------------------------------------------------------------
    # should use returned orders for further operation on the orders
    # returned orders are the same orders as saved in the order_book
    # ---------------------------------------------------------------
    async def execute_rebind(self, orders: list[Order | CancelOrder] | Order | CancelOrder):
        if not isinstance(orders, list):
            orders = [orders]

        results: list[Order | CancelOrder | None] = [None] * len(orders)

        # Validate first
        for order in orders:
            if order.creation_success:
                    self.logger.error(
                        f"[Strategy] invalid cancellation order is included: {order}",
                        extra={"owner": self.agent_id},
                    )
                    return results  # [None, None, ...]

            if order.is_regular_order:
                self._validate_strategy_order(order) ###_ cancels the agent run for now
                # if not self._validate_strategy_order(order):
                #     self.logger.error(
                #         f"[Strategy] order validation failed: {order}",
                #         extra={"owner": self.agent_id},
                #     )
                #     return results  # [None, None, ...]

        # this ensures furture exists in pending strategy order dict as the dispatch_order could arrive faster
        loop = asyncio.get_running_loop()

        futures: list[asyncio.Future] = [] # needed to process only orders in the input argument
        uid_to_index: dict[str, int] = {} # stable ordering

        for idx, order in enumerate(orders):
            fut = loop.create_future()
            futures.append(fut)

            uid_to_index[order.unique_id] = idx
            self.pending_strategy_orders[order.unique_id] = fut

        submitted = await self.submit_order(orders)

        if not submitted: # none submitted
            for order in orders:
                self.pending_strategy_orders.pop(order.unique_id, None)
                self.logger.error(
                    f"[Strategy] order submission failed: no {order.order_no} uid {order.unique_id}",
                    extra={"owner": self.agent_id},
                )
            return results 

        try:
            for fut in asyncio.as_completed(futures):
                processed: Order | CancelOrder = await fut # prepare placeholders
                idx = uid_to_index[processed.unique_id]
                results[idx] = processed

                if processed.submitted:
                    self.logger.info(
                        f"[Strategy] order submit success: no {processed.order_no} uid {processed.unique_id}",
                        extra={"owner": self.agent_id},
                    )
                else:
                    self.logger.error(
                        f"[Strategy] order not processed: no {processed.order_no} uid {processed.unique_id}",
                        extra={"owner": self.agent_id},
                    )

        except asyncio.CancelledError:
            # Clean only unfinished futures
            for uid, fut in list(self.pending_strategy_orders.items()): # mutating the dict while iterating, so list(copy) needed
                if not fut.done():
                    self.pending_strategy_orders.pop(uid, None)
            raise

        return results if len(results) > 1 else results[0]

    def handle_order_dispatch(self, dispatched_order: Order | CancelOrder):
        fut = self.pending_strategy_orders.pop(dispatched_order.unique_id, None)
        if not fut:
            self.logger.error(f"[Strategy] no pending future exists for the dispatched_order: uid {dispatched_order.unique_id}", extra={"owner": self.agent_id})
            return

        if not fut.done():
            fut.set_result(dispatched_order)        
        else: 
            self.logger.error(f"[Strategy] future is already done for the dispatched_order: uid {dispatched_order.unique_id}", extra={"owner": self.agent_id})

    # -----------------------------------------------------------------
    # validators
    # -----------------------------------------------------------------
    def _validate_strategy_order(self, order: Order | None) -> bool:
        if order is None: return False

        if order.side == SIDE.BUY:
            if order.mtype == MTYPE.LIMIT:
                if order.quantity*order.price > self.pm.get_max_limit_buy_amt():
                    self.logger.error(f'account limit reached - order cancelled', extra={"owner": self.agent_id})
                    raise asyncio.CancelledError # this case to be checked with logic
                    # return False
            else: # MARKET or MIDDLE
                exp_amount = excel_round(order.quantity*self.pm.moving_bar.current_price) # check with current price
                if exp_amount > self.pm.get_max_market_buy_amt():
                    self.logger.error(f'account limit reached - order cancelled', extra={"owner": self.agent_id})
                    raise asyncio.CancelledError # this case to be checked with logic
                    # return False

        else: # str_cmd.side == SIDE.SELL:
            if order.quantity > self.pm.max_sell_qty:
                return False
        return True

    # this requires to use SIDE and MTYPE classes
    def create_an_order(self, side, mtype, quantity, price, exchange=EXG.SOR) -> Order:
        # if error handling is necessary, for errors return None
        return Order(
            agent_id=self.agent_id, 
            code=self.code, 
            side=side, 
            mtype=mtype, 
            quantity=quantity, 
            price=price, 
            exchange=exchange, 
            )

    # following: no need to use SIDE and MTYPE
    def market_buy(self, quantity):
        return self.create_an_order(SIDE.BUY, MTYPE.MARKET, quantity=quantity, price=0)

    def limit_buy(self, quantity, price): 
        return self.create_an_order(SIDE.BUY, MTYPE.LIMIT, quantity=quantity, price=price)

    def market_sell(self, quantity):
        return self.create_an_order(SIDE.BUY, MTYPE.MARKET, quantity=quantity, price=0)

    def limit_sell(self, quantity, price): 
        return self.create_an_order(SIDE.BUY, MTYPE.MARKET, quantity=quantity, price=price)
    
    # may add middle too 

