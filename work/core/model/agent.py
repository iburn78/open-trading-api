import asyncio
from dataclasses import dataclass, field
import pickle

from .order import Order
from .client import PersistentClient
from .order_book import OrderBook
from .price import MarketPrices
from .perf_metric import PerformanceMetric
from ..common.interface import RequestCommand, ClientRequest, ServerResponse, Sync
from ..common.optlog import optlog, log_raise, notice_beep
from ..common.setup import TradePrinciples
from ..model.strategy_util import StrategyRequest, StrategyCommand, StrategyResponse
from ..strategy.strategy import StrategyBase
from ..kis.kis_auth import KISEnv
from ..kis.ws_data import TransactionPrices, TransactionNotice, ORD_DVSN

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
    agent_initialized: bool = False
    agent_ready: bool = False # ready to start strategy
    agent_initial_price_set_up: asyncio.Event = field(default_factory=asyncio.Event) # wheather the first TNP is received (so that pm can be properly initialized)
    strict_API_check_required: bool = False # consume one API call

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
        self.strategy.link_agent_data(self.id, self.code, self.trade_principles, self.order_book, self.market_prices, self.pm)

    # has to be called on start-up
    def initialize(self, total_allocated_cash = 0, initial_holding = 0, avg_price_initial_holding = 0, bep_price_initial_holding = 0):
        self.pm.total_allocated_cash = total_allocated_cash
        self.pm.initial_holding = initial_holding
        self.pm.avg_price_initial_holding = avg_price_initial_holding
        self.pm.bep_price_initial_holding = bep_price_initial_holding
        self.agent_initialized = True
    
    def update_performance_metric(self):
        self.order_book.update_performance_metric(self.pm)
        self.market_prices.update_performance_metric(self.pm)
        self.pm.calc()
        return self.pm

    async def process_strategy_command(self): 
        while not self.hardstop_event.is_set():
            str_command: StrategyCommand = await self.strategy._command_queue.get()

            if str_command.request == StrategyRequest.ORDER:
                order = self.create_an_order(str_command)
                if self._check_connected('submit'):
                    optlog.info(f"[submitting new order] {order}", name=self.id)
                    await self.order_book.submit_new_order(self.client, order)
                    response = StrategyResponse(request=str_command.request, response_data=True)
                else: 
                    optlog.error(f'str command {str_command} not processed', name=self.id)
                    response = StrategyResponse(request=str_command.request, response_data=False)

            elif str_command.request == StrategyRequest.PSBL_QUANTITY:
                q_ = await self.check_psbl_buy_amount(ord_dvsn=str_command.ord_dvsn, price = str_command.price)
                response = StrategyResponse(request=str_command.request, response_data=q_)

            else: 
                response = None

            await self.strategy._response_queue.put(response) 

    async def run(self, **kwargs):
        """  
        Keeps the agent alive until stopped.
        agent's main loop 
        - to be run in an asyncio task
        - has to be the starting point of the agent
        - does 1) connect to server, 2) register itself, 3) subscribe to trp by code, 4) wait until stopped
        - orders can be made afterward
        """
        if not self.agent_initialized: 
            optlog.error(f'agent not initialized - agent run aborted', name = self.id)
            return 

        await self.client.connect()

        # [Registration part]
        register_request = ClientRequest(command=RequestCommand.REGISTER_AGENT_CARD)
        register_request.set_request_data(self.card) 
        register_resp: ServerResponse = await self.client.send_client_request(register_request)
        optlog.info(f"[ServerResponse] {register_resp}", name=self.id)
        if not register_resp.success:
            await self.client.close()
            return 
        self.trenv = register_resp.data_dict['trenv'] # trenv should be in data, otherwise let it raise here

        # [Sync part - getting sync data]
        sync_request = ClientRequest(command=RequestCommand.SYNC_ORDER_HISTORY)
        sync_request.set_request_data(self.id)
        sync_resp: ServerResponse = await self.client.send_client_request(sync_request)
        optlog.debug(f'[ServerResponse] {sync_resp}', name=self.id)
        sync: Sync = sync_resp.data_dict.get("sync_data") 
        await self.order_book.process_sync(sync)

        # [Sync part - releasing lock]
        release_request = ClientRequest(command=RequestCommand.SYNC_COMPLETE_NOTICE)
        release_request.set_request_data(self.id)
        release_resp: ServerResponse = await self.client.send_client_request(release_request)
        if release_resp.success:
            optlog.debug(f'[ServerResponse] {release_resp} sync-release completed', name=self.id)
        else: 
            log_raise(f"lock release failed ---", name=self.id)

        # [Subscription part]
        subs_request = ClientRequest(command=RequestCommand.SUBSCRIBE_TRP_BY_AGENT_CARD)
        subs_request.set_request_data(self.card) 
        subs_resp: ServerResponse = await self.client.send_client_request(subs_request)
        optlog.info(f"[ServerResponse] {subs_resp}", name=self.id)

        # [Price initialization part]
        optlog.debug(f'[Agent] waiting for initial market price', name=self.id)
        await self.agent_initial_price_set_up.wait() # ensures, pm is set with latest market data
        optlog.info(f"[Agent] ready to run strategy: {self.strategy.str_name}", name=self.id)

        # [Strategy enact part]
        asyncio.create_task(self.process_strategy_command())
        asyncio.create_task(self.strategy.logic_run())

        try:
            await self.hardstop_event.wait() 
        except asyncio.CancelledError:
            optlog.info(f"[Agent] agent {self.id} hardstopped.", name=self.id)
        finally:
            await self.client.close()

    # makes an order, not sent to server yet
    def create_an_order(self, strategy_command: StrategyCommand): 
        ''' Create an order and add to new_orders (which is not yet sent to server for submission) '''
        side = strategy_command.side
        ord_dvsn = strategy_command.ord_dvsn
        quantity = strategy_command.quantity
        price = strategy_command.price
        exchange = strategy_command.exchange
        str_id = strategy_command.id
        return Order(agent_id=self.id, code=self.code, side=side, ord_dvsn=ord_dvsn, quantity=quantity, price=price, exchange=exchange, str_id=str_id)
    
    def cancel_all_orders(self):
        if self._check_connected('cancel'):
            cancel_request = ClientRequest(command=RequestCommand.CANCEL_ALL_ORDERS_BY_AGENT)
            # note cancel request does not receive server response - if needed, make this as async cancel_all_orders(self), etc
            asyncio.create_task(self.client.send_client_request(cancel_request))
        else:
            optlog.error(f'cancel all order command not processed', name=self.id)
        
    def _check_connected(self, msg: str = ""): 
        if not self.client.is_connected:
            optlog.error(f"[Agent] client not connected - cannot ({msg}) orders for agent {self.id} ---", name=self.id)
            return False
        return True

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

    async def handle_dict(self, dict_data):
        optlog.info(f"[Agent] dispatched dict: {dict_data}", name=self.id)

    async def handle_order(self, order: Order):
        optlog.info(f"[submit result received] {order}", name=self.id) 
        await self.order_book.handle_order_dispatch(order)
        self.strategy._order_receipt_event.set() 

    async def handle_prices(self, trp: TransactionPrices):
        self.market_prices.update_from_trp(trp)
        self.strategy._price_update_event.set()
        optlog.debug(self.market_prices, name=self.id)
        self.agent_initial_price_set_up.set() 
        
    async def handle_notice(self, trn: TransactionNotice):
        optlog.info(trn, name=self.id) # show trn before processing
        notice_beep() # make a sound upton trn
        await self.order_book.process_tr_notice(trn, self.trenv) 
        self.strategy._trn_receive_event.set()

    async def check_psbl_buy_amount(self, ord_dvsn: ORD_DVSN, price: int):
        psbl_request = ClientRequest(command=RequestCommand.GET_PSBL_ORDER)
        psbl_request.set_request_data((self.code, ord_dvsn, price)) 
        psbl_resp: ServerResponse = await self.client.send_client_request(psbl_request)
        (a_, q_, p_) = psbl_resp.data_dict['psbl_data'] # tuple should be returned, otherwise let it raise here
        return q_

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
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as e:
            optlog.error(f"[Agent] agent {agent.id} (port {agent.client_port}) disconnected - dispatch msg failed: {e}", name=agent.id)
        except Exception as e:
            optlog.error(f"[Agent] unexpected dispatch error: {e}", name=agent.id, exc_info=True)
