import asyncio
from dataclasses import dataclass, field

from .order import Order
from .client import PersistentClient
from .perf_metric import PerformanceMetric
from ..common.optlog import optlog, log_raise
from ..common.tools import adj_int
from ..common.interface import RequestCommand, ClientRequest
from ..kis.kis_auth import KISEnv
from ..kis.ws_data import ORD_DVSN, SIDE, TransactionNotice

@dataclass
class OrderBook: 
    """
    Order record boook used by agents, individually
    """
    agent_id: str = ""
    code: str = ""
    trenv: KISEnv | None = None  
    print_processing_only: bool = True 

    # private order lists - use setter functions for calculating dashboard info real time
    _indexed_sent_for_submit: dict["unique_id": str, Order] = field(default_factory=dict) # sent to server repository / once server sent it to KIS API, submitted orders will be sent back via on_dispatch
    _indexed_incompleted_orders: dict["order_no": str, Order] = field(default_factory=dict)
    _completed_orders: list[Order] = field(default_factory=list) 
    _unhandled_trns: list[TransactionNotice] = field(default_factory=list)

    # --------------------------------
    # [dashboard info]
    # --------------------------------
    # below only from orders in this order book, not from account info
    # - current_holding can be negative 
    current_holding: int = 0  
    on_buy_order: int = 0 # include from _indexed_sent_for_submit and _indexed_incompleted_orders 
    on_LIMIT_buy_amount: int = 0 
    on_MARKET_buy_quantity: int = 0

    on_sell_order: int = 0 # include from _indexed_sent_for_submit and _indexed_incompleted_orders 
    total_purchased: int = 0 # cumulative
    total_sold: int = 0 # cumulative

    # below only for current holding / snapshot
    # - only calculated when current_holding > 0, otherwise 0
    avg_price: int = 0

    # - only calculated when current_holding > 0, otherwise 0
    bep_price: int = 0 # bep cost only considers tax and fee for that order (not all cumulative costs)

    # - only calculated when buy, otherwise 0
    low_price: int = 0 
    high_price: int = 0

    # - history reflected overall data
    # - on buy/sell order amounts not accounted
    principle_cash_used: int = 0 # (purchased - sold) excluding fee and tax: so negative possible (e.g., profit or sold from initial holding)
    total_cost_incurred: int = 0 # cumulative tax and fee
    total_cash_used: int = 0 # principle + total_cost: likewise 

    # _lock is necessary because order submission and notice processing may happen concurrently
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def update_performance_metric(self, pm: PerformanceMetric):
        # if pm.code != self.code: return None
        pm.holding = self.current_holding
        pm.avg_price = self.avg_price
        pm.bep_price = self.bep_price
        pm.principle_cash_used = self.principle_cash_used
        pm.total_cost_incurred = self.total_cost_incurred
        pm.total_cash_used = self.total_cash_used

    def __str__(self):
        if not self._indexed_sent_for_submit and not self._indexed_incompleted_orders and not self._completed_orders:
            return "<no orders>"
        return (
            f"\n"
            f"Dashboard {(self.code)}, agent {self.agent_id}\n"
            f"----------------------------------------------------\n"
            f"Current Holding     : {self.current_holding:>15,d}\n"
            f"On Buy Order        : {self.on_buy_order:>15,d}\n"
            f"- Limit (Amount)    : {self.on_LIMIT_buy_amount :>15,d}\n"
            f"- Market (Quantity) : {self.on_MARKET_buy_quantity :>15,d}\n"
            f"On Sell Order       : {self.on_sell_order:>15,d}\n"
            f"----------------------------------------------------\n"
            f"Total Purchased     : {self.total_purchased:>15,d}\n"
            f"Total Sold          : {self.total_sold:>15,d}\n"
            f"Avg. Price          : {self.avg_price:>15,d}\n"
            f"BEP Price           : {self.bep_price:>15,d}\n"
            f"----------------------------------------------------\n"
            f"Principle Cash Used : {self.principle_cash_used:>15,d}\n"
            f"Total Cost Incurred : {self.total_cost_incurred:>15,d}\n"
            f"Total Cash Used     : {self.total_cash_used:>15,d}\n"
            f"----------------------------------------------------"
        )

    def get_listings_str(self, processing_only: bool=True):
        processing_only = self.print_processing_only
        def _section(title, orders: list, indexed_orders: dict):
            if orders:  # list 
                return f"{title} ({len(orders)} orders)\n" + "\n".join(f"{o}" for o in orders)
            if indexed_orders:  # dict
                return f"{title} ({len(indexed_orders)} orders)\n" + "\n".join(f"{v}" for k, v in indexed_orders.items())

        sections = []
        if self._indexed_sent_for_submit:
            sections.append(_section("[listings] Sent for submit", None, self._indexed_sent_for_submit))
        if self._indexed_incompleted_orders:
            sections.append(_section("[listings] Incompleted orders", None, self._indexed_incompleted_orders))
        if self._completed_orders and not processing_only:
            sections.append(_section("[listings] Completed orders", self._completed_orders, None))
        if not sections:
            return "[listings] no orders processing"
        return "\n".join(sections)

    async def process_tr_notice(self, notice: TransactionNotice, trenv):
        # reroute notice to corresponding order
        # no race condition expected here
        async with self._lock:
            order = self._indexed_incompleted_orders.get(notice.oder_no)
            if order: 
                prev_qty = order.processed 
                prev_cost = order.fee_rounded + order.tax_rounded
                prev_amount = order.amount

                order.update(notice, trenv)

                delta_qty = order.processed - prev_qty
                if delta_qty < 0: 
                    optlog.error(f'trn processed quantity negative: {notice}', name=self.agent_id)
                delta_cost = (order.fee_rounded + order.tax_rounded) - prev_cost
                delta_amount = order.amount - prev_amount
                if order.side == SIDE.BUY:
                    # adjust on orders(to feedback in available cash for new orders)
                    self.on_buy_order += -delta_qty
                    if order.ord_dvsn == ORD_DVSN.LIMIT:
                        self.on_LIMIT_buy_amount += -delta_amount
                    else:  # MARKET or MIDDLE
                        self.on_MARKET_buy_quantity += -delta_qty
                    
                    # update stats
                    self.avg_price = adj_int((self.current_holding*self.avg_price + delta_amount)/(self.current_holding+delta_qty) if delta_qty > 0 else self.avg_price)
                    self.bep_price = adj_int((self.current_holding*self.bep_price + delta_amount + delta_cost)/(self.current_holding+delta_qty) if delta_qty > 0 else self.bep_price)

                    self.current_holding += delta_qty
                    self.total_purchased += delta_qty
                    self.principle_cash_used += delta_amount
                    self.high_price = max(self.high_price, notice.cntg_unpr)
                    self.low_price = min(self.low_price, notice.cntg_unpr) if self.low_price != 0 else notice.cntg_unpr

                else:
                    # adjust on orders
                    self.on_sell_order += -delta_qty

                    # update stats
                    self.current_holding += -delta_qty
                    self.total_sold += delta_qty
                    self.principle_cash_used += -delta_amount

                self.total_cost_incurred += delta_cost
                self.total_cash_used = self.principle_cash_used + self.total_cost_incurred

                # if order is completed or canceled, move to completed_orders
                if order.completed or order.cancelled:
                    self._indexed_incompleted_orders.pop(order.order_no)
                    self._completed_orders.append(order)   
            else: 
                # log_raise(f"Order not found in incompleted_orders for notice {notice.oder_no}, notice: {notice} ---", name=self.agent_id)
                # just in case race condition occurs
                self.trenv = trenv
                self._unhandled_trns.append(notice)
    
    async def submit_new_order(self, client: PersistentClient, order: Order):
        async with self._lock:
            # note the dashboard has to be reverted if order fails in the server: implemented in handle_order_dispatch()
            if order.side == SIDE.BUY:
                self.on_buy_order += order.quantity
                if order.ord_dvsn == ORD_DVSN.LIMIT:
                    self.on_LIMIT_buy_amount += order.quantity * order.price
                else:  # MARKET or MIDDLE
                    self.on_MARKET_buy_quantity += order.quantity
            else:
                self.on_sell_order += order.quantity

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
            if dispatched_order.order_no is None: # this has to be checking with dispatched_order, but revert with matched_order
                # Revert the dashboard 
                if matched_order.side == SIDE.BUY:
                    self.on_buy_order -= matched_order.quantity
                    if matched_order.ord_dvsn == ORD_DVSN.LIMIT:
                        self.on_LIMIT_buy_amount -= matched_order.quantity*matched_order.price # this is amount
                    else: # MARKET or MIDDLE
                        self.on_MARKET_buy_quantity -= matched_order.quantity # this is quantity
                else:
                    self.on_sell_order -= matched_order.quantity
                return

            # order success
            self._indexed_incompleted_orders[dispatched_order.order_no] = dispatched_order

            # processing unhandled trns here
            # empty the list, otherwise trns stay (still unmatched trns will be add back to the list)
            unhandled = self._unhandled_trns.copy()
            self._unhandled_trns.clear()

        # as process_tr_notice requires _lock, take this out from _lock
        for trn in unhandled:
            await self.process_tr_notice(trn, self.trenv)


