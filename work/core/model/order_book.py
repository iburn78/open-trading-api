import asyncio
from dataclasses import dataclass, field
import logging

from .order import Order, CancelOrder
from ..kis.kis_tools import SIDE, MTYPE
from ..kis.ws_data import TransactionNotice
from ..comm.comm_interface import Sync

@dataclass
class OrderBook: 
    """
    Order/CancelOrder record boook used by agents, individually

    note: 
    - submitted: goes to incompleted orders already
    - accepted: reflected in pending quanity (at this level, strategy is notified)
    """
    agent_id: str 
    code: str
    logger: logging.Logger

    # order lists - should use setter/getter functions to calculate dashboard info real time
    _indexed_incompleted_orders: dict["order_no": str, Order | CancelOrder] = field(default_factory=dict)
    _indexed_prev_incompleted_orders: dict["order_no": str, Order | CancelOrder] = field(default_factory=dict) # only used when sync
    _indexed_completed_orders: dict["order_no": str, Order | CancelOrder] = field(default_factory=dict)
    # - below _pending_trns: copied from the server; and this is not agent specific; so it is possible not to emptied out eventually, which is acceptable
    _pending_trns_from_server_on_sync: dict["order_no": str, list[TransactionNotice]] = field(default_factory=dict)
    _unhandled_trns: dict["order_no": str, list[TransactionNotice]] = field(default_factory=dict)

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
        _indent = '    '
        return (
            f"[OrderBook] dashboard {(self.code)}, agent {self.agent_id}\n"
            f"{_indent}----------------------------------------------------\n"
            f"{_indent}OrderBook Holding Qty: {self.orderbook_holding_qty:>15,d}\n"
            f"{_indent}Pending Buy Qty      : {self.pending_buy_qty:>15,d}\n"
            f"{_indent}- Limit (Amount)     : {self.pending_limit_buy_amt :>15,d}\n"
            f"{_indent}- Market (Quantity)  : {self.pending_market_buy_qty :>15,d}\n"  # including Middle
            f"{_indent}Pending Sell Qty     : {self.pending_sell_qty:>15,d}\n"
            f"{_indent}Init Holding Sold Qty: {self.initial_holding_sold_qty:>15,d}\n"
            f"{_indent}----------------------------------------------------\n"
            f"{_indent}Cumulative Buy       : {self.cumul_buy_qty:>15,d}\n"
            f"{_indent}Cumulative Sell      : {self.cumul_sell_qty:>15,d}\n"
            f"{_indent}----------------------------------------------------\n"
            f"{_indent}Net Cash Used        : {self.net_cash_used:>15,d}\n"
            f"{_indent}Cumulative Cost      : {self.cumul_cost:>15,d}\n"
            f"{_indent}Total Cash Used      : {self.total_cash_used:>15,d}\n"
            f"{_indent}----------------------------------------------------\n"
            f"{_indent}OrderBook Holding AvP: {self.orderbook_holding_avg_price:>15,.0f}\n"
            f"{_indent}----------------------------------------------------"
        )
    def _section(self, title, indexed_orders: dict):
        return f"{title} ({len(indexed_orders)} orders)\n" + "\n".join(f"    {v}" for k, v in indexed_orders.items())

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
            self.logger.info(f"[OrderBook] sync data received: {sync}", extra={"owner": self.agent_id})
            
            # sync has to be done when agent is initialized... 
            self._check_if_start_from_empty()

            # then overwrite with the server data
            self._indexed_prev_incompleted_orders = sync.prev_incompleted_orders # before today
            self._indexed_incompleted_orders = sync.incompleted_orders # today
            self._indexed_completed_orders = sync.completed_orders

            # _pending_trns_from_server_on_sync value assigned only here
            self._pending_trns_from_server_on_sync = sync.pending_trns

            for _, v in self._indexed_completed_orders.items():
                if v.is_regular_order:
                    self._record_increase(v, v.processed, v.fee_+v.tax_, v.amount)

            for _, v in self._indexed_prev_incompleted_orders.items():
                if v.is_regular_order:
                    self._record_increase(v, v.processed, v.fee_+v.tax_, v.amount)

            for _, v in self._indexed_incompleted_orders.items():
                if v.is_regular_order:
                    self._record_increase(v, v.processed, v.fee_+v.tax_, v.amount)
                    self._pending_increase(v, v.quantity-v.processed)
            self.logger.info(f"[OrderBook] sync completed: {self}", extra={"owner": self.agent_id})

    def _check_if_start_from_empty(self):
        # checking representative ones
        if self._indexed_incompleted_orders: self.logger.error(f"[OrderBook] parse_orders, initial state not empty - 1", extra={"owner": self.agent_id})
        if self._indexed_completed_orders: self.logger.error(f"[OrderBook] parse_orders, initial state not empty - 2", extra={"owner": self.agent_id})
        if self.orderbook_holding_qty != 0: self.logger.error(f"[OrderBook] key_stat is not zero - 1", extra={"owner": self.agent_id})
        if self.total_cash_used != 0: self.logger.error(f"[OrderBook] key_stat is not zero - 2", extra={"owner": self.agent_id})

    # ----------------------------------------------------------------------------------
    # executed order portion stat update (체결된 사항에 대한 update)
    # ----------------------------------------------------------------------------------
    def _pending_increase(self, updated_order, delta_qty):
        if delta_qty == 0: return
        if updated_order.side == SIDE.BUY:
            self.pending_buy_qty += delta_qty
            if updated_order.mtype == MTYPE.LIMIT:
                self.pending_limit_buy_amt += updated_order.price*delta_qty
            else:  # MARKET or MIDDLE
                self.pending_market_buy_qty += delta_qty
        else:  # sell
            self.pending_sell_qty += delta_qty

    def _record_increase(self, updated_order: Order, delta_qty, delta_cost, delta_amount):
        if delta_qty == 0: return
        if updated_order.side == SIDE.BUY:
            pq = self.orderbook_holding_qty # prev quantity, copy value
            self.orderbook_holding_qty += delta_qty
            self.orderbook_holding_avg_price = (pq*self.orderbook_holding_avg_price+delta_amount)/self.orderbook_holding_qty if self.orderbook_holding_qty !=0 else 0
            self.cumul_buy_qty += delta_qty
            self.net_cash_used += delta_amount
        else:
            if self.orderbook_holding_qty - delta_qty > 0:
                self.orderbook_holding_qty += -delta_qty
            elif self.orderbook_holding_qty - delta_qty == 0:
                self.orderbook_holding_qty = 0
                self.orderbook_holding_avg_price = 0
            else:
                self.initial_holding_sold_qty += -(self.orderbook_holding_qty - delta_qty)
                self.orderbook_holding_qty = 0
                self.orderbook_holding_avg_price = 0

            self.cumul_sell_qty += delta_qty
            self.net_cash_used += -delta_amount
        self.cumul_cost += delta_cost
        self.total_cash_used = self.net_cash_used + self.cumul_cost
    
    # ----------------------------------------------------------------------------------
    # trn handling
    # ----------------------------------------------------------------------------------
    async def process_tr_notice(self, notice: TransactionNotice):
        # reroute notice to corresponding order
        async with self._lock:
            order = self._indexed_incompleted_orders.get(notice.order_no)
            if order: 
                # store previous state
                prev_qty = order.processed 
                prev_cost = order.fee_ + order.tax_ 
                prev_amount = order.amount 
                prev_accepted = order.accepted

                # update order itself 
                res = order.update(notice)
                notice.consumed = True
                if res:
                    self.logger.info(res, extra={"owner": self.agent_id})

                # update order_book stat
                delta_qty = order.processed - prev_qty
                delta_cost = (order.fee_ + order.tax_) - prev_cost
                delta_amount = order.amount - prev_amount
                if delta_qty < 0: 
                    self.logger.error(f"[OrderBook] delta quantity negative: {order}", extra={"owner": self.agent_id})

                if order.is_regular_order:
                    if not prev_accepted and order.accepted:
                        self._pending_increase(order, order.quantity)
                        # this point, a new order is accepted and the orderbook (pending) record is reflected
                        return order

                    self._record_increase(order, delta_qty, delta_cost, delta_amount)
                    self._pending_increase(order, -delta_qty)
                else: 
                    if order.completed:
                        self._pending_increase(order, -order.processed)

                # order list update - move orders
                if order.completed:
                    del self._indexed_incompleted_orders[order.order_no]
                    self._indexed_completed_orders[order.order_no] = order

                    if not order.is_regular_order: 
                        original_order = self._indexed_incompleted_orders.get(order.original_order_no)
                        if original_order is None: 
                            self.logger.error(f"[OrderBook] cancel order update error {order}", extra={"owner": self.agent_id})
                            return

                        original_order.quantity = original_order.quantity - order.processed
                        if original_order.quantity < original_order.processed:
                            self.logger.error(f"[OrderBook] cancel quantity error {order}, {original_order}", extra={"owner": self.agent_id})
                            return 

                        if original_order.quantity == original_order.processed:
                            original_order.completed = True
                            del self._indexed_incompleted_orders[order.original_order_no]
                            self._indexed_completed_orders[original_order.order_no] = original_order
            else: 
                # in race case 
                self._unhandled_trns.setdefault(notice.order_no, []).append(notice)

    # ----------------------------------------------------------------------------------
    # order dispatch handling
    # ----------------------------------------------------------------------------------
    async def handle_order_dispatch(self, dispatched_order: Order | CancelOrder):
        async with self._lock:
            # order instances being stored in the order_book are dispatched orders from the server, not the ones created by the strategy / agent
            self._indexed_incompleted_orders[dispatched_order.order_no] = dispatched_order

            # handle notices that are synced from the server
            sync_trns = self._pending_trns_from_server_on_sync.pop(dispatched_order.order_no, [])
            unhandled_trns = self._unhandled_trns.pop(dispatched_order.order_no, [])
            to_process = sync_trns + unhandled_trns

        # to_process will be processed outside of _lock to avoid deadlock
        # this is the correct way to put _unhandled_trns back in
        for trn in to_process:
            await self.process_tr_notice(trn)
        