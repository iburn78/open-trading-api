import asyncio
from dataclasses import dataclass, field
import pickle

from .order import Order
from .client import PersistentClient
from .order_book import OrderBook
from .price import MarketPrices
from ..common.interface import RequestCommand, ClientRequest, ServerResponse
from .perf_metric import PerformanceMetric
from ..common.optlog import optlog
from ..common.setup import TradePrinciples
from ..common.tools import adj_int
from ..strategy.strategy import StrategyBase, StrategyCommand, StrategyFeedback, FeedbackKind
from ..kis.kis_auth import KISEnv
from ..kis.ws_data import TransactionPrices, TransactionNotice, SIDE, ORD_DVSN


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
    trenv: KISEnv | None = None  # to be assigned later
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

    def define_initial_state(self, total_allocated_cash = 0, initial_holding = 0, avg_price_initial_holding = 0, bep_price_initial_holding = 0):
        self.pm.total_allocated_cash = total_allocated_cash
        self.pm.initial_holding = initial_holding
        self.pm.avg_price_initial_holding = avg_price_initial_holding
        self.pm.bep_price_initial_holding = bep_price_initial_holding
    
    def get_performance_metirc(self):
        self.order_book.update_performance_metric(self.pm)
        self.market_prices.update_performance_metric(self.pm)
        self.pm.calc()
        return self.pm

    async def capture_command_signals(self):
        while not self.hardstop_event.is_set():
            str_command: StrategyCommand = await self.strategy.command_signal_queue.get()
            valid, msg = await self.validate_strategy_command(str_command)
            self.strategy.command_signal_queue.task_done()
            if valid:
                order = self.process_strategy_command(str_command)
                self._check_connected('submit')
                optlog.info(f"[submitting new order] {order}", name=self.id)
                await self.order_book.submit_new_order(self.client, order)
            else: 
                str_feedback = StrategyFeedback(kind=FeedbackKind.STR_COMMAND, obj=str_command, message=msg)
                await self.strategy.command_feedback_queue.put(str_feedback)
                optlog.warning(f'[Agent] invalid strategy command received - not processed: {msg}', name=self.id)

    # [Agent-level checking] internal logic checking before sending strategy command to the API server
    async def validate_strategy_command(self, str_cmd: StrategyCommand) -> tuple["valid": bool, "error_message": str]:
        """
        Validates a strategy command before execution.
    
        Checks:
        - Sufficient cash for buy orders
        - Sufficient holdings for sell orders  
        - Market price availability for market orders
        """

        if str_cmd.side == SIDE.BUY:
            # [check 0] if market_prices are not yet initialized, make it return False
            cp = self.market_prices.current_price
            if cp is None:
                return False, 'Market buy order not processed - market prices not yet initialized'

            # exact status
            # - need to account for pending orders too
            on_LIMIT_order_amount = self.order_book.on_LIMIT_buy_amount*(1+TradePrinciples.LIMIT_ORDER_SAFETY_MARGIN)
            on_MARKET_order_amount = self.order_book.on_MARKET_buy_quantity*cp*(1+TradePrinciples.MARKET_ORDER_SAFETY_MARGIN)
            agent_cash = self.pm.total_allocated_cash - self.order_book.total_cash_used - on_LIMIT_order_amount - on_MARKET_order_amount

            if str_cmd.ord_dvsn == ORD_DVSN.MARKET:
                # [check 1] check if agent has enough cash (stricter cond-check)
                exp_amount = str_cmd.quantity*cp # best guess with current price, and approach conservatively with margin
                if exp_amount > adj_int(agent_cash*(1-TradePrinciples.MARKET_ORDER_SAFETY_MARGIN)):
                    return False, 'Market buy order not processed - exceeding agent cash (after considering safety margin)'

                # [check 2] check if the account API allows it 
                if self.strict_API_check_required:
                    psbl_request = ClientRequest(command=RequestCommand.GET_PSBL_ORDER)
                    psbl_request.set_request_data((self.code, str_cmd.ord_dvsn, str_cmd.price)) 
                    psbl_resp: ServerResponse = await self.client.send_client_request(psbl_request)
                    (a_, q_, p_) = psbl_resp.data_dict['psbl_data'] # tuple should be returned, otherwise let it raise here

                    if str_cmd.quantity > q_:
                        return False, 'Market buy order not processed - exceeding KIS account quantity limit'

                return True, None

            else: # LIMIT
                ord_amount = str_cmd.quantity*str_cmd.price
                if ord_amount > adj_int(agent_cash*(1-TradePrinciples.LIMIT_ORDER_SAFETY_MARGIN)):
                    return False, 'Limit buy order not processed - exceeding agent cash (after considering safety margin)'

                # practically no need to check the account API for limit orders
                return True, None

        else: # Sell
            agent_holding = self.pm.initial_holding + self.order_book.current_holding
            # has to account for pending orders too
            if str_cmd.quantity > agent_holding - self.order_book.on_sell_order:
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

        register_request = ClientRequest(command=RequestCommand.REGISTER_AGENT_CARD)
        register_request.set_request_data(self.card) 
        register_resp: ServerResponse = await self.client.send_client_request(register_request)
        optlog.info(f"[ServerResponse] {register_resp}", name=self.id)
        if not register_resp.success:
            await self.client.close()
            return 

        self.trenv = register_resp.data_dict['trenv'] # trenv should be in data, otherwise let it raise here

        subs_request = ClientRequest(command=RequestCommand.SUBSCRIBE_TRP_BY_AGENT_CARD)
        subs_request.set_request_data(self.card) 
        subs_resp: ServerResponse = await self.client.send_client_request(subs_request)
        optlog.info(f"[ServerResponse] {subs_resp}", name=self.id)

        asyncio.create_task(self.strategy.logic_run())
        asyncio.create_task(self.capture_command_signals())

        try:
            await self.hardstop_event.wait() 
        except asyncio.CancelledError:
            optlog.info(f"[Agent] agent {self.id} hardstopped.", name=self.id)
        finally:
            await self.client.close()

    # makes an order, not sent to server yet
    def process_strategy_command(self, strategy_command: StrategyCommand): 
        ''' Create an order and add to new_orders (which is not yet sent to server for submission) '''
        side = strategy_command.side
        ord_dvsn = strategy_command.ord_dvsn
        quantity = strategy_command.quantity
        price = strategy_command.price
        exchange = strategy_command.exchange

        return Order(agent_id=self.id, code=self.code, side=side, ord_dvsn=ord_dvsn, quantity=quantity, price=price, exchange=exchange)
    
    def cancel_all_orders(self):
        self._check_connected('cancel')
        cancel_request = ClientRequest(command=RequestCommand.CANCEL_ALL_ORDERS_BY_AGENT)
        # note cancel request does not receive server response - if needed, make this as async cancel_all_orders(self), etc
        asyncio.create_task(self.client.send_client_request(cancel_request))

    def _check_connected(self, msg: str = ""): 
        if not self.client.is_connected:
            optlog.error(f"[Agent] client not connected - cannot ({msg}) orders for agent {self.id} ---", name=self.id)

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
            optlog.error("[Agent] unhandled dispatch type:", type(data), name=self.id)

    # handlers for dispatched msg types ---
    async def handle_str(self, msg):
        optlog.info(f"[Agent] dispatched message: {msg}", name=self.id)

    # dict should not have 'request_id' key, as it can be confused with a certain response to a specific request
    async def handle_dict(self, data):
        optlog.info(f"[Agent] dispatched dict: {data}", name=self.id)

    async def handle_order(self, order: Order):
        optlog.info(f"[submit result received] {order}", name=self.id) 
        await self.order_book.handle_order_dispatch(order)

        # send back the order to the strategy as is
        str_feedback = StrategyFeedback(kind=FeedbackKind.ORDER, obj=order)
        await self.strategy.command_feedback_queue.put(str_feedback)

    async def handle_prices(self, trp: TransactionPrices):
        self.market_prices.update_from_trp(trp)
        self.strategy.price_update_event.set()
        optlog.debug(self.market_prices, name=self.id)
        
    async def handle_notice(self, trn: TransactionNotice):
        optlog.info(trn, name=self.id) # show trn before processing
        await self.order_book.process_tr_notice(trn, self.trenv) 
        self.strategy.order_update_event.set()


# this function is used in the server side, so the logging is also on the server side
async def dispatch(to: AgentCard | list[AgentCard], message: object):
    if not to:
        optlog.info(f"[Agent] no agents to dispatch: {message}")

    if isinstance(to, AgentCard):
        to = [to]

    data = pickle.dumps(message)
    msg_bytes = len(data).to_bytes(4, 'big') + data
    for agent in to:
        try:
            agent.writer.write(msg_bytes)
            await agent.writer.drain()  # await ensures exceptions are caught here
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            optlog.error(f"[Agent] agent {agent.id} (port {agent.client_port}) disconnected - dispatch msg failed.", name=agent.id, exc_info=True)
        except Exception as e:
            optlog.error(f"[Agent] unexpected dispatch error: {e}", name=agent.id, exc_info=True)
