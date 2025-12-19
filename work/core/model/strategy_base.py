from abc import ABC, abstractmethod
import asyncio

from ..common.tools import excel_round
from ..common.optlog import optlog, LOG_INDENT
from ..kis.ws_data import SIDE, ORD_DVSN, EXCHANGE
from ..model.order import Order, CancelOrder
from .perf_metric import PerformanceMetric
from .strategy_util import UpdateEvent

class StrategyBase(ABC):
    """
    Subclasses should call:
    def __init__(self): or __post_init__
        super().__init__()

    """
    def __init__(self):
        self.agent_id = None
        self.code = None
        self.submit_order = None # callback assigned by agent
        self.pending_strategy_orders: dict[str, asyncio.Future] = {}
        self.lazy_run: bool = True

        # snapshot data to use in making strategy
        # -----------------------------------------------------------------
        self.pm: PerformanceMetric | None = None 
        # - through pm, access to initial data of the agent possible
        # - also, access to market_prices and order_book possible
        # - self.update_pm() is called on every on_update through on_update_shell
        # -----------------------------------------------------------------

        # Strategy - Agent communication channel (only used in StrategyBase and Agent - internal for both)
        self._order_receipt_event: asyncio.Event = asyncio.Event()
        self._price_update_event: asyncio.Event = asyncio.Event()
        self._trn_receive_event: asyncio.Event = asyncio.Event()

        # others
        self.str_name = self.__class__.__name__ # subclass name
        self._on_update_lock: asyncio.Lock = asyncio.Lock()

    async def logic_run(self):
        # initial run
        await self.on_update_shell(UpdateEvent.INITIATE)

        while True:
            self._price_update_event.clear() # does not run on every price change
            # choose which to start fresh waiting 
            if self.lazy_run:
                self._trn_receive_event.clear() 
                self._order_receipt_event.clear() 
            tasks = [
                asyncio.create_task(self._price_update_event.wait(), name=f"{self.agent_id}_pu_event_task"),
                asyncio.create_task(self._trn_receive_event.wait(), name=f"{self.agent_id}_tr_event_task"),
                asyncio.create_task(self._order_receipt_event.wait(), name=f"{self.agent_id}_or_event_task"),
            ]

            _, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )

            for t in pending:
                t.cancel()

            try:
                if self._price_update_event.is_set():
                    self._price_update_event.clear()
                    await self.on_update_shell(UpdateEvent.PRICE_UPDATE)

                if self._trn_receive_event.is_set():
                    self._trn_receive_event.clear()
                    optlog.info(self.pm, name=self.agent_id)
                    await self.on_update_shell(UpdateEvent.TRN_RECEIVE)

                if self._order_receipt_event.is_set():
                    self._order_receipt_event.clear()
                    await self.on_update_shell(UpdateEvent.ORDER_RECEIVE)

            except Exception:
                optlog.critical("[Strategy] logic_run crashed", name=self.agent_id, exc_info=True)
                raise

    async def on_update_shell(self, update_event: UpdateEvent):
        try:
            async with self._on_update_lock:
                await self.on_update(update_event)
        except asyncio.CancelledError:
            raise  # re-raise
        except Exception as e:
            optlog.error(f"[Strategy] on_update failed ({update_event.name}): {e}", name=self.agent_id, exc_info=True)
            raise  

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
            # pm has market_prices and order_book
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
    # returned orders are the same orders saved in the order_book
    # ---------------------------------------------------------------
    async def execute_rebind(self, orders: list[Order | CancelOrder] | Order | CancelOrder):
        if not isinstance(orders, list):
            orders = [orders]
        processed_orders = {}

        for order in orders:
            if order.is_regular_order:
                if not self.validate_strategy_order(order): 
                    optlog.error(f"[Strategy] order validation failed: {order}", name=self.agent_id)
                    return None

        # this ensures furture exists in pending strategy order dict as the dispatch_order could arrive faster
        loop = asyncio.get_running_loop()
        futures = []

        for order in orders: 
            fut = loop.create_future()
            futures.append(fut)
            self.pending_strategy_orders[order.unique_id] = fut
            processed_orders[order.unique_id] = None # prepare placeholders

        submitted = await self.submit_order(orders) 

        if not submitted: # none submitted
            for order in orders:
                self.pending_strategy_orders.pop(order.unique_id) 
                optlog.error(f"[Strategy] order submission to KIS failed at server: no {order.order_no} uid {order.unique_id}", name=self.agent_id)
            return None
        
        try:
            for fut in asyncio.as_completed(futures):
                processed: Order | CancelOrder = await fut
                processed_orders[processed.unique_id] = processed
                if processed.submitted:
                    optlog.info(f"[Strategy] order submit success: no {processed.order_no} uid {processed.unique_id}", name=self.agent_id)
                else: 
                    optlog.error(f"[Strategy] order not processed at KIS: no {processed.order_no} uid {processed.unique_id}", name=self.agent_id)
            
        except asyncio.CancelledError:
            for order in orders:
                self.pending_strategy_orders.pop(order.unique_id, None)
            raise
        
        res = list(processed_orders.values())
        return res if len(res) > 1 else res[0]

    def handle_order_dispatch(self, dispatched_order: Order | CancelOrder):
        fut = self.pending_strategy_orders.pop(dispatched_order.unique_id, None)
        if not fut:
            optlog.error(f"[Strategy] no pending future exists for the dispatched_order: uid {dispatched_order.unique_id}", name=self.agent_id)
            return

        if not fut.done():
            fut.set_result(dispatched_order)        
        else: 
            optlog.error(f"[Strategy] future is already done for the dispatched_order: uid {dispatched_order.unique_id}", name=self.agent_id)

    # -----------------------------------------------------------------
    # validators
    # -----------------------------------------------------------------
    def validate_strategy_order(self, order: Order | None) -> bool:
        if order is None: return False

        if order.side == SIDE.BUY:
            if order.ord_dvsn == ORD_DVSN.LIMIT:
                if order.quantity*order.price > self.pm.get_max_limit_buy_amt():
                    return False
            else: # MARKET or MIDDLE
                exp_amount = excel_round(order.quantity*self.pm.market_prices.current_price) # check with current price
                if exp_amount > self.pm.get_max_market_buy_amt():
                    return False

        else: # str_cmd.side == SIDE.SELL:
            if order.quantity > self.pm.max_sell_qty:
                return False
        return True

    def create_an_order(self, side, ord_dvsn, quantity, price, exchange=EXCHANGE.SOR) -> Order:
        # if error handling is necessary, for errors return None
        return Order(
            agent_id=self.agent_id, 
            code=self.code, 
            listed_market=self.pm.listed_market, 
            side=side, 
            ord_dvsn=ord_dvsn, 
            quantity=quantity, 
            price=price, 
            exchange=exchange, 
            )