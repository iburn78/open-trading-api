import asyncio
from dataclasses import dataclass, field

from .order import Order
from .client import PersistentClient
from ..common.optlog import optlog
from ..common.setup import TradePrinciples
from ..common.tools import adj_int
from ..model.order_book import OrderBook
from ..model.price import MarketPrices
from ..strategy.strategy import StrategyBase, StrategyCommand, StrategyFeedback, FeedbackKind
from ..kis.ws_data import TransactionPrices, TransactionNotice, SIDE, ORD_DVSN
from ..model.perf_metric import PerformanceMetric

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

    # for server communication
    card: AgentCard = field(default_factory=lambda: AgentCard(id="", code=""))
    client: PersistentClient = field(default_factory=PersistentClient)
    trenv: object | None = None  # to be assigned later
    hardstop_event: asyncio.Event = field(default_factory=asyncio.Event)

    # data tracking and strategy
    trade_principles: TradePrinciples = field (default_factory=TradePrinciples)
    order_book: OrderBook = field(default_factory=OrderBook)
    market_prices: MarketPrices = field(default_factory=MarketPrices)
    strategy: StrategyBase = field(default_factory=StrategyBase) 
    pm: PerformanceMetric = field(default_factory=PerformanceMetric)

    # other flags
    strict_API_check_required: bool = False  

    def __post_init__(self):
        # initialize
        self.card.id = self.id
        self.card.code = self.code

        self.order_book.agent_id = self.id
        self.order_book.code = self.code

        self.market_prices.code = self.code

        self.client.agent_id = self.id
        self.client.on_dispatch = self.on_dispatch

        self.pm.agent_id = self.id
        self.pm.code = self.code

        # setup strategy with order_book and market_prices
        self.strategy.agent_data_setup(self.id, self.code, self.order_book, self.market_prices, self.pm)

    def define_initial_state(self, total_allocated_cash = 0, initial_holding = 0, bep_price_iholding = 0):
        self.pm.total_allocated_cash = total_allocated_cash
        self.pm.initial_holding = initial_holding
        self.pm.bep_price_iholding = bep_price_iholding
    
    def get_performance_metirc(self):
        self.order_book.update_performance_metric(self.pm)
        self.market_prices.update_performance_metric(self.pm)
        self.pm.calc()
        return self.pm

    async def capture_command_signals(self):
        while not self.hardstop_event.is_set():
            str_command: StrategyCommand = await self.strategy.command_signal_queue.get()
            self.strategy.command_signal_queue.task_done()
            valid, msg = await self.validate_strategy_command(str_command)
            if valid:
                orders = self.process_strategy_command(str_command)
                self._check_connected('submit')
                await self.order_book.submit_new_orders(self.client, orders)
            else: 
                str_feedback = StrategyFeedback(kind=FeedbackKind.STR_COMMAND, obj=str_command, message=msg)
                await self.strategy.command_feedback_queue.put(str_feedback)
                optlog.warning(f'Invalid strategy command received - not processed: {msg}')

    # [Agent-level checking] internal logic checking before sending strategy command to the API server
    async def validate_strategy_command(self, str_cmd: StrategyCommand):
        # exact status
        agent_cash = self.pm.total_allocated_cash - self.order_book.total_cash_used
        agent_holding = self.pm.initial_holding + self.order_book.current_holding

        if str_cmd.side == SIDE.BUY:
            if str_cmd.ord_dvsn == ORD_DVSN.MARKET:
                # [check 0] if market_prices are not yet initialized, make it return False
                if self.market_prices.current_price is None:
                    return False, 'Market buy order not processed - market prices not yet initialized'

                # [check 1] check if agent has enough cash (stricter cond-check)
                exp_amount = str_cmd.quantity*self.market_prices.current_price
                if exp_amount > adj_int(agent_cash*(1-TradePrinciples.MARKET_ORDER_SAFETY_MARGIN)):
                    return False, 'Market buy order not processed - exceeding agent cash (after considering safety margin)'

                # [check 2] check if the account API allows it 
                if self.strict_API_check_required:
                    resp = await self.client.send_command(request_command="get_psbl_order", request_data=(self.code, str_cmd.ord_dvsn, str_cmd.price))
                    a_, q_, p_ = resp.get("response_data")

                    if str_cmd.quantity > q_:
                        return False, 'Market buy order not processed - exceeding KIS quantity limit'

                return True, None
            else:
                ord_amount = str_cmd.quantity*str_cmd.price
                if ord_amount > adj_int(agent_cash*(1-TradePrinciples.LIMIT_ORDER_SAFETY_MARGIN)):
                    return False, 'Limit buy order not processed - exceeding agent cash (after considering safety margin)'

                # practically no need to check the account API for limit orders
                return True, None

        else: 
            if str_cmd.quantity > agent_holding:
                return False, 'Sell order not processed - exceeding total holding'
            return True, None

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
        optlog.info(f"Response: {resp.get('response_status')}", name=self.id)
        if not resp.get('response_success'):
            await self.client.close()
            return 

        self.trenv = resp.get('response_data')

        resp = await self.client.send_command("subscribe_trp_by_agent_card", request_data=self.card)
        optlog.info(f"Response: {resp.get('response_status')}", name=self.id)

        asyncio.create_task(self.strategy.logic_run())
        asyncio.create_task(self.capture_command_signals())

        try:
            await self.hardstop_event.wait() 
        except asyncio.CancelledError:
            optlog.info(f"Agent {self.id} hardstopped.", name=self.id)
        finally:
            await self.client.close()

    # make an order, not sent to server yet
    def process_strategy_command(self, strategy_command: StrategyCommand): # side: SIDE, quantity, ord_dvsn: ORD_DVSN, price, exchange: EXCHANGE = EXCHANGE.SOR):
        ''' Create an order and add to new_orders (not yet sent to server for submission) '''
        # Single order case
        side = strategy_command.side
        ord_dvsn = strategy_command.ord_dvsn
        quantity = strategy_command.quantity
        price = strategy_command.price
        exchange = strategy_command.exchange

        order = Order(agent_id=self.id, code=self.code, side=side, ord_dvsn=ord_dvsn, quantity=quantity, price=price, exchange=exchange)

        # multiple orders case:
        # ...

        return [order]
    
    def cancel_all_orders(self):
        self._check_connected('cancel')
        asyncio.create_task(self.client.send_command("CANCEL_orders", request_data=None))

    def _check_connected(self, msg: str = ""): 
        if not self.client.is_connected:
            optlog.error(f"Client not connected - cannot ({msg}) orders for agent {self.id} ---", name=self.id)

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
            optlog.error("Unhandled type:", type(data), name=self.id)

    # handlers for dispatched msg types ---
    async def handle_str(self, msg):
        optlog.info(f"Received message: {msg}", name=self.id)

    # dict should not have 'request_id' key, as it can be confused with a certain response to a specific request
    async def handle_dict(self, data):
        optlog.info(f"Received dict: {data}", name=self.id)

    async def handle_order(self, order: Order):
        optlog.info(f"Submit result received: {order}", name=self.id) 
        order_processed = await self.order_book.handle_order_dispatch(order)
        if not order_processed:
            str_feedback = StrategyFeedback(kind=FeedbackKind.ORDER, obj=order, message="server rejected the order")
            self.strategy.command_feedback_queue.put(str_feedback)

    async def handle_prices(self, trp: TransactionPrices):
        self.market_prices.update_from_trp(trp)
        self.strategy.price_update_event.set()
        optlog.debug(self.market_prices, name=self.id)
        
    async def handle_notice(self, trn: TransactionNotice):
        await self.order_book.process_tr_notice(trn, self.trenv) 
        self.strategy.order_update_event.set()
        optlog.info(trn, name=self.id)

