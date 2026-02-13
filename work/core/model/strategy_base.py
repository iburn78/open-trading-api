from abc import ABC, abstractmethod
import asyncio

from .perf_metric import PerformanceMetric
from .strategy_util import UpdateEvent
from .order import Order, CancelOrder
from .bar import RawBars, BarBuilder, BarList
from .barlist_analysis import BarListStatus
from .dashboard import DashBoard
from ..base.tools import excel_round
from ..kis.kis_tools import SIDE, MTYPE, EXG

class StrategyError(Exception):
    """Recoverable error inside strategy logic."""
    pass

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

        # BarList analysis
        self._barlist_event_event: asyncio.Event = asyncio.Event()
        self.barlist_status: BarListStatus | None = None

        self.raw_bars = RawBars() # default 1 sec, full history 
        self.bar_builer = BarBuilder(raw_bars=self.raw_bars) # default 20 sec; adjust by reset()
        self.barlist = BarList(bar_builder=self.bar_builer) # default 50 bars; adjust by reset() 
        self.barlist.on_barlist_update = self.on_barlist_update 
        
        # others
        self.str_name = self.__class__.__name__ # subclass (specific strategy) name
        self._on_update_lock: asyncio.Lock = asyncio.Lock()

        # ----------------------------------
        # error handling
        # ----------------------------------
        self._error_count = 0
        self._max_errors = 5
        self._cool_down = 1 # sec
        self._suspend_on_update: bool = False

    async def logic_run(self):
        # initial run
        await self.on_update_shell(UpdateEvent.INITIATE)

        while True:
            self._price_update_event.clear() # does not run on every price change
            if self.lazy_run: # if True, strategy does not run on every trn: only reacts to new trns
                self._trn_receive_event.clear() 

            tasks = {
                asyncio.create_task(self._price_update_event.wait()): UpdateEvent.PRICE_UPDATE,
                asyncio.create_task(self._trn_receive_event.wait()): UpdateEvent.TRN_RECEIVE,
                asyncio.create_task(self._barlist_event_event.wait()): UpdateEvent.BARLIST_EVENT,
            }

            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )

            for t in pending:
                t.cancel()

            event_type = tasks[done.pop()] # done and pending are sets, so use pop()
            if event_type is UpdateEvent.BARLIST_EVENT:
                self._barlist_event_event.clear()

            await self.on_update_shell(event_type)
    
    async def on_update_shell(self, update_event: UpdateEvent):
        if self._suspend_on_update: return

        try:
            async with self._on_update_lock:
                await self.on_update(update_event)
            self._error_count = 0 # resets

        except StrategyError as e:
            self._error_count += 1 
            self.logger.warning(f"[Strategy] on update failed {self._error_count}/{self._max_errors}: {e}", extra={"owner": self.agent_id})
            if self._error_count == self._max_errors: 
                self._suspend_on_update = True
                self.logger.warning(f"[Strategy] on_update suspended", extra={"owner": self.agent_id})
            await asyncio.sleep(self._cool_down)

        except Exception as e:
            self.logger.error(f"[Strategy] on_update failed ({update_event.name}): {e}", extra={"owner": self.agent_id}, exc_info=True)
            raise asyncio.CancelledError

    def check_barlist_event(self, **kwargs):
        self.barlist_status = BarListStatus(**kwargs)

        status = None
        if self.barlist_status.barlist_event:
            status = str(self.barlist_status) 

        self.barlist.mark_on_barlist(self.barlist_status, status=status)

    @abstractmethod
    def on_barlist_update(self):
        # ------------------------------
        # 1) do analysis
        # 2) call self.check_barlist_event(**kwargs)
        # 3) **kwargs should match with BarListStatus signature
        if self.dashboard: 
            self.dashboard.send_bars(self.barlist.barlist)

        if self.barlist_status and self.barlist_status.barlist_event:
            self._barlist_event_event.set()

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

        for order in orders:
            if order.is_regular_order:
                self._validate_strategy_order(order) 

            elif order.creation_success: # cancel_order case
                self.logger.error(
                    f"[Strategy] invalid cancellation order is included: {order}",
                    extra={"owner": self.agent_id},
                )
                raise StrategyError('invalid cancellation order')

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
                    f"[Strategy] order submit failed: no {order.order_no} uid {order.unique_id}",
                    extra={"owner": self.agent_id},
                )
            return results 

        try:
            for fut in asyncio.as_completed(futures):
                processed: Order | CancelOrder = await fut # prepare placeholders
                idx = uid_to_index[processed.unique_id]
                results[idx] = processed # may contain non-submitted orders (failed at API/server)

        except asyncio.CancelledError:
            # clean only unfinished futures
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
        if order is None: return 
        
        if order.side == SIDE.BUY:
            if order.mtype == MTYPE.LIMIT:
                if order.quantity*order.price > self.pm.get_max_limit_buy_amt():
                    self.logger.error(f'[Strategy] account limit reached - order cancelled', extra={"owner": self.agent_id})
                    raise StrategyError('account limit reached')

            else: # MARKET or MIDDLE
                exp_amount = excel_round(order.quantity*self.pm.moving_bar.current_price) # check with current price
                if exp_amount > self.pm.get_max_market_buy_amt():
                    self.logger.error(f'[Strategy] account limit reached - order cancelled', extra={"owner": self.agent_id})
                    raise StrategyError('account limit reached')

        else: # str_cmd.side == SIDE.SELL:
            if order.quantity > self.pm.max_sell_qty:
                raise StrategyError('order quantity exceeds limit')

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
        return self.create_an_order(SIDE.SELL, MTYPE.MARKET, quantity=quantity, price=0)

    def limit_sell(self, quantity, price): 
        return self.create_an_order(SIDE.SELL, MTYPE.LIMIT, quantity=quantity, price=price)

    # - may add middle too 

