import pandas as pd
import asyncio
from dataclasses import dataclass, field

from .order import Order
from .client import PersistentClient
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
        return "\n\n".join(parts)

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
            optlog.info(resp.get('response_status'))

            # move new_orders to incompleted_orders
            self.incompleted_orders.extend(self.new_orders)
            self.new_orders.clear()

@dataclass
class Agent:
    # id and code do not change for the lifetime
    id: str  # ID SHOULD BE UNIQUE ACROSS ALL AGENTS (should be managed centrally)
    code: str

    # # temporary vars for trading stretegy - need review 
    # target_return_rate: float = 0.0
    # strategy: str | None = None # to be implemented
    # assigned_cash_t_2: int = 0 # available cash for trading
    # holding_quantity: int = 0
    # total_cost_incurred: int = 0

    # # temporary var for performance measure testing - need review 
    # stats: dict = field(default_factory=dict)

    # for server communication
    card: AgentCard = field(default_factory=lambda: AgentCard(id="", code=""))
    client: PersistentClient = field(default_factory=PersistentClient)
    trenv: object | None = None  # to be assigned later
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    _ready_event: asyncio.Event = field(default_factory=asyncio.Event)

    # for order control
    order_book: OrderBook = field(default_factory=lambda: OrderBook())

    def __post_init__(self):
        # keep AgentCard consistent with Agent's id/code
        self.card.id = self.id
        self.card.code = self.code

        self.client.on_dispatch = self.on_dispatch

        # self.stats = {
        #     'key_data': 0, 
        #     'count': 0,
        # }

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
    
    def make_an_order(self, side: SIDE, quantity, ord_dvsn: ORD_DVSN, price):
        order = Order(self.id, self.code, side, quantity, ord_dvsn, price)
        self.order_book.new_orders.append(order)

    def submit_orders(self, orders: list[Order] | None):
        if orders: 
            if isinstance(orders, Order):
                orders = [orders]
            self.order_book.new_orders.extend(orders)
        self._check_connected()
        self.order_book.submit_new_orders(self.client)

    def _check_connected(self): 
        if not self.client.is_connected():
            optlog.error(f"Client not connected - cannot submit orders for agent {self.id} ---")

    # msg can be 1) str, 2) Order, 3) TransactionPrices, 4) TransactionNotice
    # should be careful when datatype is dict (could be response to certain request, and captured before getting here)
    async def on_dispatch(self, msg):
        TYPE_HANDLERS = {
            str: self.handle_str,
            dict: self.handle_dict, 
            Order: self.handle_order,
            TransactionPrices: self.handle_prices,
            TransactionNotice: self.handle_notice,
        }

        handler = TYPE_HANDLERS.get(type(msg))
        if handler:
            await handler(msg)
        else:
            print("Unhandled type:", type(msg))

    # handlers for dispatched msg types ---
    async def handle_str(self, msg):
        print("String:", msg)

    # dict should not have 'request_id' key, as it can be confused with response
    async def handle_dict(self, msg):
        print("Dict:", msg)

    async def handle_order(self, msg):
        print("Order:", msg)

    async def handle_prices(self, msg):
        print("Prices:", msg)

    async def handle_notice(self, msg):
        self.order_book.process_tr_notice(msg, self.trenv)
        optlog.info(f"TR Notice: {msg}")

