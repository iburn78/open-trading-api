import asyncio
from dataclasses import dataclass, field

from .order import Order, CancelOrder
from ..common.optlog import optlog, log_raise, LOG_INDENT
from ..common.interface import Sync
from ..kis.kis_auth import KISEnv
from ..kis.ws_data import ORD_DVSN, SIDE, TransactionNotice

@dataclass
class OrderBook: 
    """
    Order/CancelOrder record boook used by agents, individually
    """
    agent_id: str = ""
    code: str = ""
    trenv: KISEnv | None = None # initialized once agent is registered

    # private order lists - should use setter/getter functions to calculate dashboard info real time
    _indexed_incompleted_orders: dict["order_no": str, Order | CancelOrder] = field(default_factory=dict)
    _indexed_prev_incompleted_orders: dict["order_no": str, Order | CancelOrder] = field(default_factory=dict) # only used when sync
    _indexed_completed_orders: dict["order_no": str, Order | CancelOrder] = field(default_factory=dict)
    # - below _pending_trns: copied from the server; and this is not agent specific; so it is possible not to emptied out eventually, which is acceptable
    _pending_trns_from_server_on_sync: dict["order_no": str, list[TransactionNotice]] = field(default_factory=dict)
    _unhandled_trns: list[TransactionNotice] = field(default_factory=list)

    # _lock is necessary because order submission and notice processing may happen concurrently
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    # ----------------------------------------------------------------
    # dashboard info / shared with performance metric / has to be reset before sync
    # - below ONLY accounts for the transactions since in this order book creation
    # - there can be initial holding qty assigned to the agent 
    # - if sell, orderbook_holding_qty is sold first: that is FILO 
    # - if initial holding qty is sold, then it does not affect orderbook_holding_qty
    # - orderbook_holding_avg_price is only for new buys in this order_book
    # ----------------------------------------------------------------
    orderbook_holding_qty: int = 0 # can not be negative
    orderbook_holding_avg_price: float = 0
    initial_holding_sold_qty: int = 0 # when initial holding qty is sold, this records it

    # 주문 상태
    pending_buy_qty: int = 0 # quantity, counted from _indexed_incompleted_orders 
    pending_limit_buy_amt: int = 0 # amount
    pending_market_buy_qty: int = 0 # quantity
    pending_sell_qty: int = 0 # qauntity, counted from _indexed_incompleted_orders 

    # 체결된 사항
    cumul_buy_qty: int = 0 # cumulative quantity
    cumul_sell_qty: int = 0 # cumulative quantity

    # history reflected data
    # - pending orders not accounted (체결된 사항)
    net_cash_used: int = 0 # (cumul buy - sold) excluding fee and tax: negative possible (e.g., profit or sold from initial holding)
    cumul_cost: int = 0 # cumulative tax and fee
    total_cash_used: int = 0 # net_cash_used + cumul_cost
    # ----------------------------------------------------------------

    def __str__(self):
        if not self._indexed_incompleted_orders and not self._indexed_completed_orders:
            return "[OrderBook] no records"
        return (
            f"[OrderBook] dashboard {(self.code)}, agent {self.agent_id}\n"
            f"{LOG_INDENT}----------------------------------------------------\n"
            f"{LOG_INDENT}OrderBook Holding Qty: {self.orderbook_holding_qty:>15,d}\n"
            f"{LOG_INDENT}Pending Buy Qty      : {self.pending_buy_qty:>15,d}\n"
            f"{LOG_INDENT}- Limit (Amount)     : {self.pending_limit_buy_amt :>15,d}\n"
            f"{LOG_INDENT}- Market (Quantity)  : {self.pending_market_buy_qty :>15,d}\n"  # including Middle
            f"{LOG_INDENT}Pending Sell Qty     : {self.pending_sell_qty:>15,d}\n"
            f"{LOG_INDENT}Init Holding Sold Qty: {self.initial_holding_sold_qty:>15,d}\n"
            f"{LOG_INDENT}----------------------------------------------------\n"
            f"{LOG_INDENT}Cumulative Buy       : {self.cumul_buy_qty:>15,d}\n"
            f"{LOG_INDENT}Cumulative Sell      : {self.cumul_sell_qty:>15,d}\n"
            f"{LOG_INDENT}----------------------------------------------------\n"
            f"{LOG_INDENT}Net Cash Used        : {self.net_cash_used:>15,d}\n"
            f"{LOG_INDENT}Cumulative Cost      : {self.cumul_cost:>15,d}\n"
            f"{LOG_INDENT}Total Cash Used      : {self.total_cash_used:>15,d}\n"
            f"{LOG_INDENT}----------------------------------------------------\n"
            f"{LOG_INDENT}OrderBook Holding AvP: {self.orderbook_holding_avg_price:>15,.0f}\n"
            f"{LOG_INDENT}----------------------------------------------------"
        )
    def _section(self, title, indexed_orders: dict):
        return f"{title} ({len(indexed_orders)} orders)\n" + "\n".join(f"{LOG_INDENT}{v}" for k, v in indexed_orders.items())

    def get_listings_str(self, processing_only: bool=True):
        sections = []
        if self._indexed_incompleted_orders:
            sections.append(self._section("[OrderBook] incompleted orders", self._indexed_incompleted_orders))
        if self._indexed_completed_orders and not processing_only:
            sections.append(self._section("[OrderBook] completed orders", self._indexed_completed_orders))
        if not sections:
            return "[OrderBook] no orders under processing"
        return "\n".join(sections)

    # ----------------------------------------------------------------------------------
    # sync on initialization
    # ----------------------------------------------------------------------------------
    async def process_sync(self, sync: Sync):
        async with self._lock:
            optlog.info(f"sync data received: {sync}", name=self.agent_id)
            
            # sync has to be done when agent is initialized... 
            self._check_if_start_from_empty()

            # then overwrite with the server data
            self._indexed_prev_incompleted_orders = sync.prev_incompleted_orders # before today
            self._indexed_incompleted_orders = sync.incompleted_orders # today
            self._indexed_completed_orders = sync.completed_orders

            # _pending_trns_from_server_on_sync value assigned only here
            self._pending_trns_from_server_on_sync = sync.pending_trns

            unhandled = await self._parse_orders_and_update_stats()
            optlog.info(f"sync completed: {self}", name=self.agent_id)

        for trn in unhandled: # if any
            await self.process_tr_notice(trn)
    
    def _check_if_start_from_empty(self):
        # checking representative ones
        if self._indexed_incompleted_orders: optlog.error(f"[OrderBook] parse_orders, initial state not empty - 1", name=self.agent_id) 
        if self._indexed_completed_orders: optlog.error(f"[OrderBook] parse_orders, initial state not empty - 2", name=self.agent_id) 
        if self.orderbook_holding_qty != 0: optlog.error(f"[OrderBook] key_stat is not zero - 1", name=self.agent_id)
        if self.total_cash_used != 0: optlog.error(f"[OrderBook] key_stat is not zero - 2", name=self.agent_id)

    async def _parse_orders_and_update_stats(self):
        for _, v in self._indexed_completed_orders.items():
            self._stat_update(v, on_sync=True)

        for _, v in self._indexed_prev_incompleted_orders.items():
            self._stat_update(v, on_sync=True)

        unhandled = [] 
        for _, v in self._indexed_incompleted_orders.items():
            unhandled = self._handle_order_dispatch(v) # to avoid deadlock
            self._stat_update(v)
        return unhandled

    # ----------------------------------------------------------------------------------
    # executed order portion stat update (체결된 사항에 대한 update)
    # ----------------------------------------------------------------------------------
    # - prev_qty = order.processed 
    # - prev_cost = order.fee_ + order.tax_ 
    # - prev_amount = order.amount 
    def _stat_update(self, updated_order: Order | CancelOrder, prev_qty=0, prev_cost=0, prev_amount=0, on_sync=False):
        if not isinstance(updated_order, CancelOrder): 
            delta_qty = updated_order.processed - prev_qty
            if delta_qty == 0:
                return # nothing to update 
            if delta_qty < 0: 
                optlog.error(f'[OrderBook] stat_update - delta quantity negative: {updated_order}', name=self.agent_id)
                return

            delta_cost = (updated_order.fee_ + updated_order.tax_) - prev_cost
            delta_amount = updated_order.amount - prev_amount

            if updated_order.side == SIDE.BUY:
                if not on_sync:
                    self.pending_buy_qty += -delta_qty
                    if updated_order.ord_dvsn == ORD_DVSN.LIMIT:
                        self.pending_limit_buy_amt += -delta_amount
                    else:  # MARKET or MIDDLE
                        self.pending_market_buy_qty += -delta_qty
                    
                pq = self.orderbook_holding_qty # prev quantity, copy value
                self.orderbook_holding_qty += delta_qty
                self.orderbook_holding_avg_price = (pq*self.orderbook_holding_avg_price+delta_amount)/self.orderbook_holding_qty if self.orderbook_holding_qty !=0 else 0
                self.cumul_buy_qty += delta_qty
                self.net_cash_used += delta_amount

            else:
                if not on_sync:
                    self.pending_sell_qty += -delta_qty

                if self.orderbook_holding_qty - delta_qty >= 0:
                    self.orderbook_holding_qty += -delta_qty
                else:
                    self.initial_holding_sold_qty += -(self.orderbook_holding_qty - delta_qty)
                    self.orderbook_holding_qty = 0
                    self.orderbook_holding_avg_price = 0

                self.cumul_sell_qty += delta_qty
                self.net_cash_used += -delta_amount

            self.cumul_cost += delta_cost
            self.total_cash_used = self.net_cash_used + self.cumul_cost

        else: # CancelOrder
            if not on_sync:
                cancelled_qty = updated_order.original_order.quantity-updated_order.original_order.processed
                cancelled_amt = updated_order.original_order.price*cancelled_qty
                if updated_order.original_order.side == SIDE.BUY:
                    self.pending_buy_qty += -cancelled_qty
                    if updated_order.original_order.ord_dvsn == ORD_DVSN.LIMIT:
                        self.pending_limit_buy_amt += -cancelled_amt
                    else:  # MARKET or MIDDLE
                        self.pending_market_buy_qty += -cancelled_qty
                else:
                    self.pending_sell_qty += -cancelled_qty

    # ----------------------------------------------------------------------------------
    # trn handling
    # ----------------------------------------------------------------------------------
    async def process_tr_notice(self, notice: TransactionNotice):
        # reroute notice to corresponding order
        # - no race condition expected here
        async with self._lock:
            order = self._indexed_incompleted_orders.get(notice.oder_no)
            if order: 
                # store previous state
                prev_qty = order.processed 
                prev_cost = order.fee_ + order.tax_ 
                prev_amount = order.amount 

                # update order itself 
                order.update(notice, self.trenv)

                # update order_book stat
                self._stat_update(updated_order=order, prev_qty=prev_qty, prev_cost=prev_cost, prev_amount=prev_amount)

                if order.completed:
                    self._indexed_incompleted_orders.pop(order.order_no)
                    self._indexed_completed_orders[order.order_no] = order

                if isinstance(order, CancelOrder):
                    # move original_order 
                    self._indexed_incompleted_orders.pop(order.original_order.order_no)
                    self._indexed_completed_orders[order.original_order.order_no] = order.original_order
            else: 
                # just in case race condition occurs
                self._unhandled_trns.append(notice)

    # ----------------------------------------------------------------------------------
    # order dispatch handling
    # ----------------------------------------------------------------------------------
    async def handle_order_dispatch(self, dispatched_order: Order | CancelOrder):
        async with self._lock:
            unhandled = self._handle_order_dispatch(dispatched_order)

        for trn in unhandled:
            await self.process_tr_notice(trn)
        
    def _handle_order_dispatch(self, dispatched_order: Order | CancelOrder):
        # order successfully submitted to the API
        if dispatched_order.submitted: # this has to be checking with dispatched_order
            self._indexed_incompleted_orders[dispatched_order.order_no] = dispatched_order

            if not isinstance(dispatched_order, CancelOrder):
                # pending order status update
                if dispatched_order.side == SIDE.BUY:
                    self.pending_buy_qty += dispatched_order.quantity
                    if dispatched_order.ord_dvsn == ORD_DVSN.LIMIT:
                        self.pending_limit_buy_amt += dispatched_order.quantity*dispatched_order.price
                    else:  # MARKET or MIDDLE
                        self.pending_market_buy_qty += dispatched_order.quantity
                else:  # sell
                    self.pending_sell_qty += dispatched_order.quantity

            # handle notices that are synced from the server
            sync_trns = self._pending_trns_from_server_on_sync.pop(dispatched_order.order_no, [])

            # processing unhandled trns here
            # - empty the list, otherwise trns stay (still unmatched trns will be add back to the list)
            # - unhandled will be processed outside of _lock (as process_tr_notice requires _lock)
            unhandled = sync_trns + self._unhandled_trns.copy()
            self._unhandled_trns.clear() # might be shared 
            return unhandled
        return []