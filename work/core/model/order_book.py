import asyncio
from dataclasses import dataclass, field

from ..common.optlog import optlog, log_raise
from ..kis.ws_data import SIDE, TransactionNotice
from ..model.order import Order
from ..model.client import PersistentClient

@dataclass
class OrderBook: 
    new_orders: list[Order] = field(default_factory=list) # to be submitted
    orders_sent_to_server_for_submit: list[Order] = field(default_factory=list) # sent to server repository, just to keep track / once server sent it to KIS API, submitted orders will be sent back via on_dispatch
    incompleted_orders: list[Order] = field(default_factory=list) # submitted but not yet fully completed or cancelled
    completed_orders: list[Order] = field(default_factory=list) 

    # _lock is necessary because order submission and notice processing may happen concurrently
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __str__(self):
        if not self.new_orders and not self.incompleted_orders and not self.completed_orders:
            return "<no orders>"
        parts = []
        if self.new_orders:
            parts.append("New Orders:\n" + "\n".join(str(order) for order in self.new_orders))  
        if self.incompleted_orders:
            parts.append("Incompleted Orders:\n" + "\n".join(str(order) for order in self.incompleted_orders))
        if self.completed_orders:
            parts.append("Completed Orders:\n" + "\n".join(str(order) for order in self.completed_orders))
        return "\n".join(parts)

    async def process_tr_notice(self, notice: TransactionNotice, trenv):
        # reroute notice to corresponding order
        # no race condition expected here
        async with self._lock:
            order = next((o for o in self.incompleted_orders if o.order_no == notice.oder_no), None)
            if order: 
                order.update(notice, trenv)
                # if order is completed or canceled, move to completed_orders
                if order.completed or order.cancelled:
                    self.incompleted_orders.remove(order)
                    self.completed_orders.append(order)
            else: 
                log_raise(f"Order not found in incompleted_orders for notice {notice.oder_no}, notice: {notice} ---")
    
    async def submit_new_orders(self, client: PersistentClient):
        async with self._lock:
            if not self.new_orders:
                return 
            resp = await client.send_command("submit_orders", request_data=self.new_orders)
            # Just simply 'orders submitted' message expected
            # Server will send back individual order updates via on_dispatch
            optlog.info(resp.get('response_status'))

            # move new_orders to incompleted_orders
            self.orders_sent_to_server_for_submit.extend(self.new_orders)
            self.new_orders.clear()

    # make this real time holding tracking later 
    def quantity_holding(self) -> int:
        # parse completed_orders and incompleted_orders to calculate current holding quantity
        # or get account info (but it is API bound)
        total_bought = sum(order.processed for order in self.completed_orders + self.incompleted_orders if order.side == SIDE.BUY)
        total_sold = sum(order.processed for order in self.completed_orders + self.incompleted_orders if order.side == SIDE.SELL)
        return total_bought - total_sold