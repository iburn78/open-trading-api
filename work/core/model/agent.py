import asyncio
from dataclasses import dataclass, field

from .order import Order
from .client import PersistentClient
from ..common.optlog import optlog, log_raise
from ..model.order_book import OrderBook
from ..model.price import PriceRecords
from ..strategy.strategy import StrategyBase, StrategyCommand
from ..kis.ws_data import TransactionPrices, TransactionNotice

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
    hardstop_event: asyncio.Event = field(default_factory=asyncio.Event)

    # data tracking and strategy
    order_book: OrderBook = field(default_factory=OrderBook)
    price_book: PriceRecords = field(default_factory=PriceRecords)
    strategy: StrategyBase = field(default_factory=StrategyBase) 

    def __post_init__(self):
        self.card.id = self.id
        self.card.code = self.code
        self.client.on_dispatch = self.on_dispatch

        # setup strategy with order_book and price_book
        # if needed, may assign previously built order_book and price_book 
        self.strategy.agent_data_setup(self.order_book, self.price_book)

    async def capture_command(self):
        while not self.hardstop_event.is_set():
            str_command: StrategyCommand = await self.strategy.signal_queue.get()
            self.make_an_order_locally(str_command)
            await self.submit_orders_in_orderbook()

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

        self.trenv = resp.get('response_data')

        resp = await self.client.send_command("subscribe_trp_by_agent_card", request_data=self.card)
        optlog.info(resp.get('response_status'))

        asyncio.create_task(self.strategy.logic_run())
        asyncio.create_task(self.capture_command())

        try:
            await self.hardstop_event.wait() 
        except asyncio.CancelledError:
            optlog.info(f"Agent {self.id} hardstopped.")
        finally:
            await self.client.close()

    def report_performance(self): 
        pass
    
    # make an order, not sent to server yet
    def make_an_order_locally(self, strategy_command: StrategyCommand): # side: SIDE, quantity, ord_dvsn: ORD_DVSN, price, exchange: EXCHANGE = EXCHANGE.SOR):
        ''' Create an order and add to new_orders (not yet sent to server for submission) '''
        side = strategy_command.side
        ord_dvsn = strategy_command.ord_dvsn
        quantity = strategy_command.quantity
        price = strategy_command.price
        exchange = strategy_command.exchange

        order = Order(agent_id=self.id, code=self.code, side=side, ord_dvsn=ord_dvsn, quantity=quantity, price=price, exchange=exchange)
        self.order_book.new_orders.append(order)

    async def submit_orders_in_orderbook(self, orders: list[Order] | None = None):
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
        if not self.client.is_connected:
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
        self.price_book.update_from_trp(trp)
        self.strategy.price_updated()
        # optlog.debug(self.price_records)
        
    async def handle_notice(self, trn: TransactionNotice):
        await self.order_book.process_tr_notice(trn, self.trenv)
        self.strategy.order_updated()
        optlog.info(f"TR Notice: {trn}")

