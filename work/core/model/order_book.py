import asyncio
from dataclasses import dataclass, field

from ..common.optlog import optlog, log_raise
from ..common.tools import adj_int
from ..kis.ws_data import SIDE, TransactionNotice
from ..model.order import Order
from ..model.client import PersistentClient

@dataclass
class OrderBook: 
    agent_id: str = ""
    code: str = ""

    # private order lists - use setter functions for calculating dashboard info real time
    _new_orders: list[Order] = field(default_factory=list) # to be submitted
    _orders_sent_for_submit: list[Order] = field(default_factory=list) # sent to server repository / once server sent it to KIS API, submitted orders will be sent back via on_dispatch
    _incompleted_orders: list[Order] = field(default_factory=list) # submitted but not yet fully completed or cancelled
    _completed_orders: list[Order] = field(default_factory=list) 

    # --------------------------------
    # [dashboard info]
    # --------------------------------
    # below only from orders in this order book, not from account info
    # - current_holding can be negative 
    current_holding: int = 0  
    on_buy_order: int = 0 # include from _orders_sent_for_submit and _incompleted_orders (not from _new_orders)
    on_sell_order: int = 0 # include from _orders_sent_for_submit and _incompleted_orders (not from _new_orders)
    total_purchased: int = 0 # cumulative
    total_sold: int = 0 # cumulative

    # below only for current holding:
    # - average_price can be negative 
    average_price: int = 0

    # - only calculated when current_holding > 0, otherwise 0
    bep_price: int = 0  

    # - only calculated when buy, otherwise 0
    low_price: int = 0 
    high_price: int = 0

    principle_cash_used: int = 0 # (purchased - sold) excluding fee and tax
    total_cash_used: int = 0 # principle + fee and tax 
    total_cost_incurred: int = 0 # cumulative tax and fee

    # _lock is necessary because order submission and notice processing may happen concurrently
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def append_to_new_orders(self, orders: Order | list[Order]):
        if isinstance(orders, Order):
            orders = [orders]
        self._new_orders.extend(orders)

    def clear_new_orders(self):
        self._new_orders.clear()

    def append_to_orders_sent_for_submit(self, orders: Order | list[Order]):
        if isinstance(orders, Order):
            orders = [orders]
        for order in orders:
            if order.side == SIDE.BUY:
                self.on_buy_order += order.quantity
            else:
                self.on_sell_order += order.quantity
        self._orders_sent_for_submit.extend(orders)
    
    def remove_from_orders_sent_for_submit(self, order: Order):
        processed_order = next((o for o in self._orders_sent_for_submit if o.unique_id == order.unique_id), None) 
        if processed_order:
            # caution: not directly removing 'order' because it may be a different object with same unique_id
            self._orders_sent_for_submit.remove(processed_order)
        else: 
            log_raise(f"Received order not found in orders_sent_for_submit: {order} ---", name=self.agent_id)

    def append_to_incompleted_orders(self, orders: Order | list[Order]):
        if isinstance(orders, Order):
            orders = [orders]
        self._incompleted_orders.extend(orders)
    
    def remove_from_incompleted_orders(self, order: Order):
        self._incompleted_orders.remove(order)
    
    def append_to_completed_orders(self, orders: Order | list[Order]):
        if isinstance(orders, Order):
            orders = [orders]
        self._completed_orders.extend(orders)   

    def __str__(self):
        if not self._new_orders and not self._orders_sent_for_submit and not self._incompleted_orders and not self._completed_orders:
            return "<no orders>"
        return (
            f"Dashboard {(self.code)}, agent {self.agent_id}\n"
            f"──────────────────────────────────────────\n"
            f"Current Holding     : {self.current_holding:>15,d}\n"
            f"On Buy Order        : {self.on_buy_order:>15,d}\n"
            f"On Sell Order       : {self.on_sell_order:>15,d}\n"
            f"──────────────────────────────────────────\n"
            f"Total Purchased     : {self.total_purchased:>15,d}\n"
            f"Total Sold          : {self.total_sold:>15,d}\n"
            f"Avg. Price          : {self.average_price:>15,d}\n"
            f"BEP Price           : {self.bep_price:>15,d}\n"
            f"──────────────────────────────────────────\n"
            f"Principle Cash Used : {self.principle_cash_used:>15,d}\n"
            f"Total Cash Used     : {self.total_cash_used:>15,d}\n"
            f"Total Cost Incurred : {self.total_cost_incurred:>15,d}\n"
            f"──────────────────────────────────────────\n"
        )

    def get_listings_str(self, processing_only: bool = True):
        def _section(title, orders):
            return f"{title} ({len(orders)} orders)\n" + "\n".join(f"{o}" for o in orders)

        sections = []
        if self._new_orders and not processing_only:
            sections.append(_section("[listings] New orders", self._new_orders))
        if self._orders_sent_for_submit:
            sections.append(_section("[listings] Sent for submit", self._orders_sent_for_submit))
        if self._incompleted_orders:
            sections.append(_section("[listings] Incompleted orders", self._incompleted_orders))
        if self._completed_orders and not processing_only:
            sections.append(_section("[listings] Completed orders", self._completed_orders))

        return "\n".join(sections)

    async def process_tr_notice(self, notice: TransactionNotice, trenv):
        # reroute notice to corresponding order
        # no race condition expected here
        async with self._lock:
            order = next((o for o in self._incompleted_orders if o.order_no == notice.oder_no), None)
            if order: 
                prev_qty = order.processed 
                prev_cost = order.fee_rounded + order.tax_rounded
                prev_amount = order.amount

                order.update(notice, trenv)

                delta_qty = order.processed - prev_qty
                delta_cost = (order.fee_rounded + order.tax_rounded) - prev_cost
                delta_amount = order.amount - prev_amount

                if order.side == SIDE.BUY:
                    self.on_buy_order += -delta_qty
                    self.current_holding += delta_qty
                    self.total_purchased += delta_qty
                    self.principle_cash_used += delta_amount
                    self.high_price = max(self.high_price, notice.cntg_unpr)
                    self.low_price = min(self.low_price, notice.cntg_unpr) if self.low_price != 0 else notice.cntg_unpr
                else:
                    self.on_sell_order += -delta_qty
                    self.current_holding += -delta_qty
                    self.total_sold += delta_qty
                    self.principle_cash_used += -delta_amount
                self.total_cost_incurred += delta_cost
                self.total_cash_used = self.principle_cash_used + self.total_cost_incurred
                self.average_price = adj_int((self.principle_cash_used / self.current_holding) if self.current_holding != 0 else 0)
                self.bep_price = adj_int((self.total_cash_used / self.current_holding) if self.current_holding > 0 else 0)

                # if order is completed or canceled, move to completed_orders
                if order.completed or order.cancelled:
                    self.remove_from_incompleted_orders(order)
                    self.append_to_completed_orders(order)
            else: 
                log_raise(f"Order not found in incompleted_orders for notice {notice.oder_no}, notice: {notice} ---", name=self.agent_id)
    
    async def submit_new_orders(self, client: PersistentClient):
        if not self._new_orders:
            return 
        async with self._lock:
            resp = await client.send_command("submit_orders", request_data=self._new_orders)
            # Just simply 'orders submitted' message expected
            # Server will send back individual order updates via on_dispatch
            optlog.info(f"Response: {resp.get('response_status')}", name=self.agent_id)

            # move new_orders to orders_sent_for_submit
            self.append_to_orders_sent_for_submit(self._new_orders)
            self.clear_new_orders()
