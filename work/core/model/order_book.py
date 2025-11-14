import asyncio
from dataclasses import dataclass, field

from .order import Order
from .client import PersistentClient
from ..common.optlog import optlog, log_raise, LOG_INDENT
from ..common.tools import compare_indexed_listings
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
    print_processing_only: bool = True 

    # private order lists - use setter functions for calculating dashboard info real time
    _indexed_submission_failure_orders: dict["str_id": str, Order] = field(default_factory=dict)
    _non_str_origin_failure_orders: list[Order] =field(default_factory=list)
    _indexed_sent_for_submit: dict["unique_id": str, Order] = field(default_factory=dict) # sent to server repository / once server sent it to KIS API, submitted orders will be sent back via on_dispatch
    _indexed_incompleted_orders: dict["order_no": str, Order] = field(default_factory=dict)
    _indexed_completed_orders: dict["order_no": str, Order] = field(default_factory=dict)
    # - below _pending_trns... doesn't need to be this agent specific; so possible not to emptied out eventually, which is acceptable
    _pending_trns_from_server_on_sync: dict["order_no": str, list[TransactionNotice]] = field(default_factory=dict)
    _unhandled_trns: list[TransactionNotice] = field(default_factory=list)

    # _lock is necessary because order submission and notice processing may happen concurrently
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    # ----------------------------------------------------------------
    # dashboard info / shared with performance metric
    # - below ONLY from orders in this order book 
    #   (including sync data, but not including initial agent set-up)
    # ----------------------------------------------------------------
    orderbook_holding: int = 0  
    # - quantity
    # - orderbook_holding can be negative (e.g., agent reconnected and synced with server, initial holding amount exists, etc.) 

    # 주문 상태
    on_buy_order: int = 0 # quantity, include from _indexed_sent_for_submit and _indexed_incompleted_orders 
    on_LIMIT_buy_amount: int = 0 # amount
    on_MARKET_buy_quantity: int = 0 # quantity
    on_sell_order: int = 0 # qauntity, include from _indexed_sent_for_submit and _indexed_incompleted_orders 

    # 체결된 사항
    total_purchased: int = 0 # cumulative quantity
    total_sold: int = 0 # cumulative quantity

    # history reflected overall data
    # - on buy/sell order amounts not accounted (체결된 사항)
    principle_cash_used: int = 0 # (purchased - sold) excluding fee and tax: negative possible (e.g., profit or sold from initial holding)
    total_cost_incurred: int = 0 # cumulative tax and fee
    total_cash_used: int = 0 # principle + total_cost_incurred
    # ----------------------------------------------------------------

    def __str__(self):
        if not self._indexed_sent_for_submit and not self._indexed_incompleted_orders and not self._indexed_completed_orders:
            return "[OrderBook] no records"
        return (
            f"[OrderBook] dashboard {(self.code)}, agent {self.agent_id}\n"
            f"{LOG_INDENT}----------------------------------------------------\n"
            f"{LOG_INDENT}OrderBook Holding     : {self.orderbook_holding:>15,d}\n"
            f"{LOG_INDENT}On Buy Order        : {self.on_buy_order:>15,d}\n"
            f"{LOG_INDENT}- Limit (Amount)    : {self.on_LIMIT_buy_amount :>15,d}\n"
            f"{LOG_INDENT}- Market (Quantity) : {self.on_MARKET_buy_quantity :>15,d}\n"
            f"{LOG_INDENT}On Sell Order       : {self.on_sell_order:>15,d}\n"
            f"{LOG_INDENT}----------------------------------------------------\n"
            f"{LOG_INDENT}Total Purchased     : {self.total_purchased:>15,d}\n"
            f"{LOG_INDENT}Total Sold          : {self.total_sold:>15,d}\n"
            f"{LOG_INDENT}----------------------------------------------------\n"
            f"{LOG_INDENT}Principle Cash Used : {self.principle_cash_used:>15,d}\n"
            f"{LOG_INDENT}Total Cost Incurred : {self.total_cost_incurred:>15,d}\n"
            f"{LOG_INDENT}Total Cash Used     : {self.total_cash_used:>15,d}\n"
            f"{LOG_INDENT}----------------------------------------------------"
        )
    def _section(self, title, indexed_orders: dict):
        return f"{title} ({len(indexed_orders)} orders)\n" + "\n".join(f"{LOG_INDENT}{v}" for k, v in indexed_orders.items())

    def get_listings_str(self, processing_only: bool=True):
        processing_only = self.print_processing_only

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
            ires, imsg = compare_indexed_listings(self._indexed_incompleted_orders, sync.incompleted_orders)
            cres, cmsg = compare_indexed_listings(self._indexed_completed_orders, sync.completed_orders)

            # check if the same or not, and show differences
            if ires and cres:
                optlog.info(f'[OrderBook] agent {self.agent_id} sync done: all order history matches', name=self.agent_id)
            else: 
                msg = f'[OrderBook] agent {self.agent_id} updated with server OrderManager data:'
                if not ires:
                    msg += f'    [incompleted orders updated]\n' + imsg
                if not cres:
                    msg += f'    [completed orders updated]\n' + cmsg
                optlog.info(msg, name=self.agent_id)

            self._check_if_start_from_empty()

            # then overwrite with the server data
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
        if self._indexed_submission_failure_orders: optlog.warning(f"[OrderBook] parse_orders, initial state not empty - 1", name=self.agent_id) 
        if self._non_str_origin_failure_orders: optlog.warning(f"[OrderBook] parse_orders, initial state not empty - 2", name=self.agent_id) 
        if self._indexed_sent_for_submit: optlog.warning(f"[OrderBook] parse_orders, initial state not empty - 3", name=self.agent_id) 
        if self._indexed_incompleted_orders: optlog.warning(f"[OrderBook] parse_orders, initial state not empty - 4", name=self.agent_id) 
        if self._indexed_completed_orders: optlog.warning(f"[OrderBook] parse_orders, initial state not empty - 5", name=self.agent_id) 
        if self._unhandled_trns: optlog.warning(f"[OrderBook] parse_orders, initial state not empty - 6", name=self.agent_id) 

        # checking representative ones
        if self.orderbook_holding != 0: optlog.warning(f"[OrderBook] key_stat is not zero - 1", name=self.agent_id)
        if self.on_buy_order != 0 : optlog.warning(f"[OrderBook] key_stat is not zero - 2", name=self.agent_id)
        if self.on_sell_order != 0 : optlog.warning(f"[OrderBook] key_stat is not zero - 3", name=self.agent_id)
        if self.total_cash_used != 0: optlog.warning(f"[OrderBook] key_stat is not zero - 4", name=self.agent_id)

    def _parse_orders_and_update_stats(self):
        # from completed to sent
        for k, v in self._indexed_completed_orders.items():
            self.stat_update_to_on_orders(v)
            self.stat_update(v)

        for k, v in self._indexed_incompleted_orders.items():
            self.stat_update_to_on_orders(v)
            self.stat_update(v)

        for k, v in self._indexed_sent_for_submit.items():
            self.stat_update_to_on_orders(v)

    # Executed order portion stat update (체결된 사항에 대한 update)
    # - prev_qty = order.processed 
    # - prev_cost = order.fee_rounded + order.tax_rounded 
    # - prev_amount = order.amount 
    def stat_update(self, updated_order: Order, prev_qty = 0, prev_cost = 0, prev_amount = 0):
        delta_qty = updated_order.processed - prev_qty
        if delta_qty == 0:
            return # nothing to update
        if delta_qty < 0: 
            optlog.error(f'[OrderBook] stat_update - delta quantity negative: {updated_order}', name=self.agent_id)

        delta_cost = (updated_order.fee_rounded + updated_order.tax_rounded) - prev_cost
        delta_amount = updated_order.amount - prev_amount

        if updated_order.side == SIDE.BUY:
            # adjust on_order (to feedback in available cash for new orders)
            self.on_buy_order += -delta_qty
            
            if updated_order.ord_dvsn == ORD_DVSN.LIMIT:
                self.on_LIMIT_buy_amount += -delta_amount
            else:  # MARKET or MIDDLE
                self.on_MARKET_buy_quantity += -delta_qty
                    
            self.orderbook_holding += delta_qty
            self.total_purchased += delta_qty
            self.principle_cash_used += delta_amount

        else:
            # adjust on_order
            self.on_sell_order += -delta_qty

            # update stats
            self.orderbook_holding += -delta_qty
            self.total_sold += delta_qty
            self.principle_cash_used += -delta_amount

        self.total_cost_incurred += delta_cost
        self.total_cash_used = self.principle_cash_used + self.total_cost_incurred

    # reflect: even before sumitted, count in already generated orders
    # revert: API refused order portion stat update (각종 오류로, KIS에서 submit 실패한 사항에 대한 update)
    # note: cash is not yet used
    def stat_update_to_on_orders(self, order, revert=False):
        if revert: m = -1
        else: m = 1
            
        if order.side == SIDE.BUY:
            self.on_buy_order += m*order.quantity
            if order.ord_dvsn == ORD_DVSN.LIMIT:
                self.on_LIMIT_buy_amount += m*order.quantity * order.price
            else:  # MARKET or MIDDLE
                self.on_MARKET_buy_quantity += m*order.quantity
        else:
            self.on_sell_order += m*order.quantity

    async def process_tr_notice(self, notice: TransactionNotice):
        # reroute notice to corresponding order
        # no race condition expected here
        async with self._lock:
            order = self._indexed_incompleted_orders.get(notice.oder_no)
            if order: 
                # store previous state
                prev_qty = order.processed 
                prev_cost = order.fee_rounded + order.tax_rounded 
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
            self.stat_update_to_on_orders(order)
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
                self.stat_update_to_on_orders(matched_order, revert=True)

                # save dispatched_order for record keeping by strategy id
                if dispatched_order.str_id:
                    self._indexed_submission_failure_orders[dispatched_order.str_id] = dispatched_order
                else: 
                    self._non_str_origin_failure_orders.append(dispatched_order)
                return

            # order successfully submitted to KIS
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
