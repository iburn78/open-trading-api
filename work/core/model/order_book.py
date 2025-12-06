import asyncio
from dataclasses import dataclass, field
from typing import Callable

from .order import Order
from .client import PersistentClient
from ..common.optlog import optlog, log_raise, LOG_INDENT
from ..common.interface import RequestCommand, ClientRequest, Sync
from ..kis.kis_auth import KISEnv
from ..kis.ws_data import ORD_DVSN, SIDE, TransactionNotice

@dataclass
class OrderBook: 
    """
    Order record boook used by agents, individually
    """
    agent_id: str = ""
    code: str = ""
    trenv: KISEnv | None = None # initialized once agent is registered
    on_update: Callable | None  = None

    # private order lists - should use setter/getter functions to calculate dashboard info real time
    _indexed_submission_failure_orders: dict["str_id": str, Order] = field(default_factory=dict)
    _non_strategy_related_failure_orders: list[Order] =field(default_factory=list)
    _indexed_sent_for_submit: dict["unique_id": str, Order] = field(default_factory=dict) # order sent to the server; once the server sent it to API, the submitted order will be sent back through on_dispatch
    _indexed_incompleted_orders: dict["order_no": str, Order] = field(default_factory=dict)
    _indexed_prev_incompleted_orders: dict["order_no": str, Order] = field(default_factory=dict) # only used when sync
    _indexed_completed_orders: dict["order_no": str, Order] = field(default_factory=dict)
    # - below _pending_trns: copied from the server; and this is not agent specific; so possible not to emptied out eventually, which is acceptable
    _pending_trns_from_server_on_sync: dict["order_no": str, list[TransactionNotice]] = field(default_factory=dict)
    _unhandled_trns: list[TransactionNotice] = field(default_factory=list)

    # _lock is necessary because order submission and notice processing may happen concurrently
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    # ----------------------------------------------------------------
    # dashboard info / shared with performance metric / has to be reset before sync
    # - below ONLY accounts for the transactions since in this order book creation
    # - there can be initial holding qty assigned to the agent / pm (not known to the order_book)
    # - if sell, orderbook_holding_qty is sold first: that is FILO 
    # - if initial holding qty is sold, then it does not affect orderbook_holding_qty
    # - orderbook_holding_avg_price is only for new buys in this order_book
    # ----------------------------------------------------------------
    orderbook_holding_qty: int = 0 # can not be negative
    orderbook_holding_avg_price: float = 0
    initial_holding_sold_qty: int = 0 # when initial holding qty is sold, this records it

    # 주문 상태
    pending_buy_qty: int = 0 # quantity, counted from _indexed_sent_for_submit and _indexed_incompleted_orders 
    pending_limit_buy_amt: int = 0 # amount
    pending_market_buy_qty: int = 0 # quantity
    pending_sell_qty: int = 0 # qauntity, counted from _indexed_sent_for_submit and _indexed_incompleted_orders 

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
        if not self._indexed_sent_for_submit and not self._indexed_incompleted_orders and not self._indexed_completed_orders:
            return "[OrderBook] no records"
        return (
            f"[OrderBook] dashboard {(self.code)}, agent {self.agent_id}\n"
            f"{LOG_INDENT}----------------------------------------------------\n"
            f"{LOG_INDENT}OrderBook Holding Qty: {self.orderbook_holding_qty:>15,d}\n"
            f"{LOG_INDENT}Pending Buy Qty      : {self.pending_buy_qty:>15,d}\n"
            f"{LOG_INDENT}- Limit (Amount)     : {self.pending_limit_buy_amt :>15,d}\n"
            f"{LOG_INDENT}- Market (Quantity)  : {self.pending_market_buy_qty :>15,d}\n"
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
        if self._indexed_sent_for_submit:
            sections.append(self._section("[OrderBook] sent for submit", self._indexed_sent_for_submit))
        if self._indexed_incompleted_orders:
            sections.append(self._section("[OrderBook] incompleted orders", self._indexed_incompleted_orders))
        if self._indexed_completed_orders and not processing_only:
            sections.append(self._section("[OrderBook] completed orders", self._indexed_completed_orders))
        if not sections:
            return "[OrderBook] no orders under processing"
        return "\n".join(sections)

    async def process_sync(self, sync: Sync):
        if self.agent_id != sync.agent_id: log_raise(f'[OrderBook] sync error - agent {self.agent_id}, received {sync.agent_id}')
        async with self._lock:

            optlog.info(f"sync data received: {sync}", name=self.agent_id)
            
            # sync has to be done when agent is initialized... 
            self._check_if_start_from_empty()

            # then overwrite with the server data
            self._indexed_prev_incompleted_orders = sync.prev_incompleted_orders
            self._indexed_incompleted_orders = sync.incompleted_orders
            self._indexed_completed_orders = sync.completed_orders

            # _pending_trns_from_server_on_sync value assigned only here
            self._pending_trns_from_server_on_sync = sync.pending_trns

            self._parse_orders_and_update_stats()
            optlog.info("sync completed", name=self.agent_id)
            optlog.info(self, name=self.agent_id)
    
    def _check_if_start_from_empty(self):
        # this is to be called when connected to the server
        # therefore, the order_book initial state expected to be empty 
        if self._indexed_submission_failure_orders: optlog.error(f"[OrderBook] parse_orders, initial state not empty - 1", name=self.agent_id) 
        if self._non_strategy_related_failure_orders: optlog.error(f"[OrderBook] parse_orders, initial state not empty - 2", name=self.agent_id) 
        if self._indexed_sent_for_submit: optlog.error(f"[OrderBook] parse_orders, initial state not empty - 3", name=self.agent_id) 
        if self._indexed_incompleted_orders: optlog.error(f"[OrderBook] parse_orders, initial state not empty - 4", name=self.agent_id) 
        if self._indexed_completed_orders: optlog.error(f"[OrderBook] parse_orders, initial state not empty - 5", name=self.agent_id) 
        if self._unhandled_trns: optlog.error(f"[OrderBook] parse_orders, initial state not empty - 6", name=self.agent_id) 

        # checking representative ones
        if self.orderbook_holding_qty != 0: optlog.error(f"[OrderBook] key_stat is not zero - 1", name=self.agent_id)
        if self.pending_buy_qty != 0 : optlog.error(f"[OrderBook] key_stat is not zero - 2", name=self.agent_id)
        if self.pending_sell_qty != 0 : optlog.error(f"[OrderBook] key_stat is not zero - 3", name=self.agent_id)
        if self.total_cash_used != 0: optlog.error(f"[OrderBook] key_stat is not zero - 4", name=self.agent_id)

    def _parse_orders_and_update_stats(self):
        # from completed to sent
        for _, v in self._indexed_completed_orders.items():
            self.stat_update_to_pending_orders(v)
            self.stat_update(v, prev_qty = 0, prev_cost = 0, prev_amount = 0)

        for _, v in self._indexed_prev_incompleted_orders.items():
            self.stat_update_to_pending_orders(v, prev_incomplete=True)
            self.stat_update(v, prev_qty = 0, prev_cost = 0, prev_amount = 0)

        for _, v in self._indexed_incompleted_orders.items():
            self.stat_update_to_pending_orders(v)
            self.stat_update(v, prev_qty = 0, prev_cost = 0, prev_amount = 0)

        for _, v in self._indexed_sent_for_submit.items():
            self.stat_update_to_pending_orders(v)

    # executed order portion stat update (체결된 사항에 대한 update)
    # - prev_qty = order.processed 
    # - prev_cost = order.fee_ + order.tax_ 
    # - prev_amount = order.amount 
    def stat_update(self, updated_order: Order, prev_qty, prev_cost, prev_amount):
        delta_qty = updated_order.processed - prev_qty
        if delta_qty == 0:
            return # nothing to update
        if delta_qty < 0: 
            optlog.error(f'[OrderBook] stat_update - delta quantity negative: {updated_order}', name=self.agent_id)

        delta_cost = (updated_order.fee_ + updated_order.tax_) - prev_cost
        delta_amount = updated_order.amount - prev_amount

        if updated_order.side == SIDE.BUY:
            # adjust pending orders (to feedback in cash available for new orders)
            self.pending_buy_qty += -delta_qty
            
            if updated_order.ord_dvsn == ORD_DVSN.LIMIT:
                self.pending_limit_buy_amt += -delta_amount
            else:  # MARKET or MIDDLE
                self.pending_market_buy_qty += -delta_qty
                    
            pq = self.orderbook_holding_qty
            self.orderbook_holding_qty += delta_qty
            self.orderbook_holding_avg_price = (pq*self.orderbook_holding_avg_price+delta_amount)/self.orderbook_holding_qty if self.orderbook_holding_qty !=0 else 0
            self.cumul_buy_qty += delta_qty
            self.net_cash_used += delta_amount

        else:
            # adjust pending orders
            self.pending_sell_qty += -delta_qty

            # update stats
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
        self.on_update()

    # count in orders that are not yet submtted
    # revert: API refused order portion stat update (각종 오류로, API 에서 submit 실패한 사항에 대한 update)
    # note: cash is not yet used
    def stat_update_to_pending_orders(self, order: Order, revert=False, prev_incomplete=False):
        if revert: m = -1
        else: m = 1

        if prev_incomplete: to_process = m*order.processed 
        else: to_process = m*order.quantity 

        if order.side == SIDE.BUY:
            self.pending_buy_qty += to_process
            if order.ord_dvsn == ORD_DVSN.LIMIT:
                self.pending_limit_buy_amt += to_process * order.price
            else:  # MARKET or MIDDLE
                self.pending_market_buy_qty += to_process
        else:
            self.pending_sell_qty += to_process
        self.on_update(pending=True)

    async def process_tr_notice(self, notice: TransactionNotice):
        # reroute notice to corresponding order
        # no race condition expected here
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
                self.stat_update(updated_order=order, prev_qty=prev_qty, prev_cost=prev_cost, prev_amount=prev_amount)

                # if order is completed or canceled, move to completed_orders
                if order.completed or order.cancelled:
                    self._indexed_incompleted_orders.pop(order.order_no)
                    self._indexed_completed_orders[order.order_no] = order
            else: 
                # log_raise(f"Order not found in incompleted_orders for notice {notice.oder_no}, notice: {notice} ---", name=self.agent_id)
                # just in case race condition occurs
                self._unhandled_trns.append(notice)
    
    async def submit_new_order(self, client: PersistentClient, order: Order):
        async with self._lock:
            # note the dashboard has to be reverted if order fails in the server: implemented in handle_order_dispatch()
            self.stat_update_to_pending_orders(order)
            self._indexed_sent_for_submit[order.unique_id] = order

            submit_request = ClientRequest(command=RequestCommand.SUBMIT_ORDERS)
            submit_request.set_request_data([order]) # submit as a list (a list required)

        # fire and forget: Server will send back individual order updates via on_dispatch
        await client.send_client_request(submit_request)

    async def handle_order_dispatch(self, dispatched_order: Order): 
        async with self._lock:
            # caution: dispatched order is not the same object in local: match it with unique_id
            matched_order = self._indexed_sent_for_submit.get(dispatched_order.unique_id)
            if not matched_order:
                log_raise(f"Dispatched order not found in orders_sent_for_submit: {dispatched_order} ---", name=self.agent_id)
            self._indexed_sent_for_submit.pop(matched_order.unique_id)

            # order submission failure - revert and return
            if not dispatched_order.submitted: # this has to be checking with dispatched_order, but need to revert with matched_order
                # revert the dashboard 
                self.stat_update_to_pending_orders(matched_order, revert=True)

                # save dispatched_order for record keeping by strategy id
                if dispatched_order.str_id:
                    self._indexed_submission_failure_orders[dispatched_order.str_id] = dispatched_order
                else: 
                    self._non_strategy_related_failure_orders.append(dispatched_order)
                return

            # order successfully submitted to the API
            self._indexed_incompleted_orders[dispatched_order.order_no] = dispatched_order

            # handle notices that are synced from the server
            to_process = self._pending_trns_from_server_on_sync.get(dispatched_order.order_no, None)
            if to_process:
                for notice in to_process:
                    dispatched_order.update(notice, self.trenv)

                self._pending_trns_from_server_on_sync.pop(dispatched_order.order_no)

            # processing unhandled trns here
            # empty the list, otherwise trns stay (still unmatched trns will be add back to the list)
            unhandled = self._unhandled_trns.copy()
            self._unhandled_trns.clear()

        # as process_tr_notice requires _lock, take this out from _lock
        for trn in unhandled:
            await self.process_tr_notice(trn)
