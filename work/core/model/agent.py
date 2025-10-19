import pandas as pd
import asyncio
from dataclasses import dataclass, field
from collections import deque
from datetime import datetime, timedelta

from .order import Order
from .client import PersistentClient
from ..common.tools import adj_int
from ..common.optlog import optlog, log_raise
from ..kis.ws_data import ORD_DVSN, SIDE, TransactionNotice, TransactionPrices, trenv_from_json

@dataclass
class AgentCard: # an agent's business card (e.g., agents submit their business cards in registration)
    """
    Server managed info / may change per connection
    - e.g., server memos additional info to the agent's business card
    An agent card is removed once disconnected, so order history etc should not be here.
    """
    id: str
    code: str

    client_port: str | None = None # assigned by the server/OS 
    writer: object | None = None 

@dataclass
class OrderBook: 
    """ To be used in Agent class """
    new_orders: list[Order] = field(default_factory=list) # to be submitted
    orders_sent_to_server_for_submit: list[Order] = field(default_factory=list) # sent to server repository, just to keep track / once server sent it to KIS API, submitted orders will be sent back via on_dispatch
    incompleted_orders: list[Order] = field(default_factory=list) # submitted but not yet fully completed or cancelled
    completed_orders: list[Order] = field(default_factory=list) 

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

@dataclass
class PriceRecords:
    """ 
    To be used in Agent class 
    - only keeps essential data 
    - price notices to be sent to strategy (to be implemented) later
    """
    current_price: int | None = None
    low_price: int | None = None # per window_size
    high_price: int | None = None # per window_size
    moving_avg: int | None = None # per window_size

    # volume: 거래량 (quantity: 개별 거래건 수량)
    cumulative_volume: int | None = None
    moving_volume: int | None = None # per window_size
    
    # amount: 거래대금
    cumulative_amount: int | None = None 
    moving_amount: int | None = None # per window_size

    window_size: int = 5 # min

    def __str__(self):
        if not self.current_price:
            return "price record not initialized"
        parts = []
        parts.append(f"current price: {self.current_price}, low/high: {self.low_price}/{self.high_price}, moving avg: {self.moving_avg}")
        parts.append(f"moving amount: {adj_int(self.moving_amount/10**6)} M KRW, cumulative amount: {adj_int(self.cumulative_amount/10**6)} M KRW")
        parts.append(f"measure window: {self.window_size} min")
        return "\n".join(parts)

    def __post_init__(self):
        # initialize sliding windows for price, volume, and amount
        self._price_window = deque()   # (timestamp, price)
        self._volume_window = deque()  # (timestamp, volume)
        self._amount_window = deque()  # (timestamp, amount)

        # running sums for O(1) updates
        self._sum_price = 0.0
        self._sum_volume = 0
        self._sum_amount = 0

        # initialize cumulative trackers
        self.cumulative_volume = 0
        self.cumulative_amount = 0

    def update_from_trp(self, trp: TransactionPrices):
        p, q, t = trp.get_price_quantity_time()
        self.update(p, q, t)

    def update(self, price: int, quantity: int, tr_time: datetime):
        cutoff = tr_time - timedelta(minutes=self.window_size)

        # remove outdated records
        for dq, total_attr, field in [
            (self._price_window, '_sum_price', price),
            (self._volume_window, '_sum_volume', quantity),
            (self._amount_window, '_sum_amount', price * quantity)
        ]:
            total = getattr(self, total_attr)
            while dq and dq[0][0] < cutoff:
                _, old_val = dq.popleft()
                total -= old_val
            dq.append((tr_time, field))
            total += field
            setattr(self, total_attr, total)

        # update derived metrics
        self.current_price = price
        if self._price_window:
            self.low_price = min(p for _, p in self._price_window)
            self.high_price = max(p for _, p in self._price_window)
            self.moving_avg = adj_int(self._sum_price / len(self._price_window))
        else:
            self.low_price = self.high_price = self.moving_avg = None

        # update cumulative and moving values
        self.cumulative_volume += quantity
        self.cumulative_amount += price * quantity
        self.moving_volume = self._sum_volume
        self.moving_amount = self._sum_amount

@dataclass
class Agent:
    # id and code do not change for the lifetime
    id: str  # ID SHOULD BE UNIQUE ACROSS ALL AGENTS (should be managed centrally)
    code: str

    # ---------------------------------------------------------------------------
    # # temporary vars for trading stretegy - need review 
    # target_return_rate: float = 0.0
    # strategy: str | None = None # to be implemented
    # assigned_cash_t_2: int = 0 # available cash for trading
    # holding_quantity: int = 0
    # total_cost_incurred: int = 0
    # ---------------------------------------------------------------------------

    # for server communication
    card: AgentCard = field(default_factory=lambda: AgentCard(id="", code=""))
    client: PersistentClient = field(default_factory=PersistentClient)
    trenv: object | None = None  # to be assigned later
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    _ready_event: asyncio.Event = field(default_factory=asyncio.Event)

    # for order control
    order_book: OrderBook = field(default_factory=lambda: OrderBook())
    price_records: PriceRecords = field(default_factory=lambda: PriceRecords(window_size=2))

    def __post_init__(self):
        # keep AgentCard consistent with Agent's id/code
        self.card.id = self.id
        self.card.code = self.code

        self.client.on_dispatch = self.on_dispatch

    async def run(self, **kwargs):
        """     
        Keeps the agent alive until stopped.
        agent's main loop 
        - to be run in an asyncio task
        - has to be the starting point of the agent
        - does 1) connect to server, 2) register itself, 3) subscribe to trp by code, 4) wait until stopped
        - orders can be made afterward
        """
        await self.client.connect()

        resp = await self.client.send_command("register_agent_card", request_data=self.card)
        optlog.info(resp.get('response_status'))
        if not resp.get('response_success'):
            await self.client.close()
            return 

        # get trenv from server upon registration (only partial data)
        self.trenv = trenv_from_json(resp.get('response_data'))

        resp = await self.client.send_command("subscribe_trp_by_agent_card", request_data=self.card)
        optlog.info(resp.get('response_status'))

        self._ready_event.set()

        try:
            await self._stop_event.wait()  # wait until .close() is called
        except asyncio.CancelledError:
            optlog.info(f"Agent {self.id} cancelled")
        finally:
            await self.client.close()

    def report_performance(self): 
        pass
    
    # make an order / not sent to server yet
    def make_an_order_locally(self, side: SIDE, quantity, ord_dvsn: ORD_DVSN, price):
        ''' Create an order and add to new_orders (not yet sent to server for submission) '''
        order = Order(self.id, self.code, side, quantity, ord_dvsn, price)
        self.order_book.new_orders.append(order)

    async def submit_orders(self, orders: list[Order] | None):
        if orders: 
            if isinstance(orders, Order):
                orders = [orders]
            self.order_book.new_orders.extend(orders)
        self._check_connected('submit')
        await self.order_book.submit_new_orders(self.client)
    
    def cancel_all_orders(self):
        self._check_connected('cancel')
        asyncio.create_task(self.client.send_command("CANCEL_orders", request_data=None))

    def _check_connected(self, msg: str = ""): 
        if not self.client.is_connected():
            optlog.error(f"Client not connected - cannot ({msg}) orders for agent {self.id} ---")

    # msg can be 1) str, 2) Order, 3) TransactionPrices, 4) TransactionNotice
    # should be careful when datatype is dict (could be response to certain request, and captured before getting here)
    async def on_dispatch(self, data):
        TYPE_HANDLERS = {
            str: self.handle_str,
            dict: self.handle_dict, 
            Order: self.handle_order,
            TransactionPrices: self.handle_prices,
            TransactionNotice: self.handle_notice,
        }

        handler = TYPE_HANDLERS.get(type(data))
        if handler:
            await handler(data)
        else:
            print("Unhandled type:", type(data))

    # handlers for dispatched msg types ---
    async def handle_str(self, msg):
        optlog.info(f"Received message: {msg}")

    # dict should not have 'request_id' key, as it can be confused with a certain response to a specific request
    async def handle_dict(self, data):
        optlog.info(f"Received a dict: {data}")

    async def handle_order(self, order: Order):
        # check if the order is in sent_to_server_for_submit list
        async with self.order_book._lock:
            processed_order = next((o for o in self.order_book.orders_sent_to_server_for_submit if o.unique_id == order.unique_id), None) 
            if processed_order:
                # update the order in sent_to_server_for_submit list
                self.order_book.orders_sent_to_server_for_submit.remove(processed_order)
                self.order_book.incompleted_orders.append(order)
            else: 
                log_raise(f"Received order not found in sent_to_server_for_submit: {order} ---")

    async def handle_prices(self, trp: TransactionPrices):
        self.price_records.update_from_trp(trp)
        optlog.debug(self.price_records)

    async def handle_notice(self, msg):
        await self.order_book.process_tr_notice(msg, self.trenv)
        optlog.info(f"TR Notice: {msg}")

