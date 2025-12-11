import asyncio
from dataclasses import dataclass, field
import pickle

from .order import Order, ReviseCancelOrder
from .client import PersistentClient
from .order_book import OrderBook
from .price import MarketPrices
from .perf_metric import PerformanceMetric
from .strategy_base import StrategyBase
from ..common.tools import get_listed_market, get_df_krx_price
from ..common.interface import RequestCommand, ClientRequest, ServerResponse, Sync
from ..common.optlog import optlog, log_raise, notice_beep
from ..model.strategy_util import StrategyRequest, StrategyCommand, StrategyResponse
from ..model.dashboard import DashBoard
from ..kis.kis_auth import KISEnv
from ..kis.ws_data import TransactionPrices, TransactionNotice, ORD_DVSN, RCtype

@dataclass
class AgentCard: # an agent's business card (e.g., agents submit their business cards in registration)
    """
    Server managed info / may change per connection
    - e.g., server memos additional info to the agent's business card
    An agent card is removed once disconnected, so order history etc should not be here.
    """
    id: str
    code: str
    dp: int | None

    client_port: str | None = None # assigned by the server/OS 
    writer: object | None = None 

@dataclass
class Agent:
    # id and code do not change for the lifetime
    id: str  # ID SHOULD BE UNIQUE ACROSS ALL AGENTS (should be managed centrally)
    code: str
    dp: int # dashboard port: should be unique 
    listed_market: str | None = None # KOSPI, KOSDAQ etc (used in tax calc) - determined by code / auto assigned
    dashboard: DashBoard = field(default_factory=DashBoard)

    # for server communication
    card: AgentCard = field(default_factory=lambda: AgentCard(id="", code="", dp=None))
    client: PersistentClient = field(default_factory=PersistentClient)
    trenv: KISEnv | None = None  # to be assigned later
    hardstop_event: asyncio.Event = field(default_factory=asyncio.Event)

    # data tracking and strategy
    order_book: OrderBook = field(default_factory=OrderBook)
    market_prices: MarketPrices = field(default_factory=MarketPrices)
    strategy: StrategyBase = field(default_factory=StrategyBase) 
    pm: PerformanceMetric = field(default_factory=PerformanceMetric)

    # other flags
    agent_initialized: bool = False
    agent_ready: bool = False # ready to start strategy
    agent_initial_price_set_up: asyncio.Event = field(default_factory=asyncio.Event) # wheather the first TNP is received (so that pm can be properly initialized)
    sync_start_date: str | None = None # isoformat date ("yyyy-mm-dd")

    def __post_init__(self):
        # initialize
        self.listed_market = get_listed_market(self.code)
        self.dashboard.owner = self.id
        self.dashboard.port = self.dp
        self.card.id = self.id
        self.card.code = self.code
        self.card.dp = self.dp

        self.order_book.agent_id = self.id
        self.order_book.code = self.code
        self.order_book.on_update = self.on_orderbook_update # callback func

        self.market_prices.code = self.code
        self.market_prices.current_price = get_df_krx_price(self.code)

        self.client.agent_id = self.id
        self.client.on_dispatch = self.on_dispatch

        self.pm.agent_id = self.id
        self.pm.code = self.code
        self.pm.listed_market = self.listed_market
        self.pm.order_book = self.order_book
        self.pm.market_prices = self.market_prices
        self.pm.dashboard = self.dashboard

        # link strategy with agent own data - market_prices, pm, etc
        self.strategy.link_agent_data(self.id, self.code, self.market_prices, self.pm, self.check_psbl_buy_amount)

    # has to be called on start-up
    # INITIAL STATE has to be defined carefully, as "sync" will be performed
    def initial_value_setup(self, init_cash_allocated = 0, init_holding_qty = 0, 
                            init_avg_price = 0, sync_start_date = None):
        self.pm.init_cash_allocated = init_cash_allocated
        self.pm.init_holding_qty = init_holding_qty
        self.pm.init_avg_price = init_avg_price
        self.sync_start_date = sync_start_date # default to be today (None)
        self.agent_initialized = True
    
    def on_orderbook_update(self, pending_orders=False):
        self.pm.update(pending_orders)
        if self.agent_ready: # to avoid excessive logging
            optlog.info(self.pm, name=self.id)

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

        # [DashBoard enact part]
        await self.dashboard.start()

        # [Registration part]
        register_request = ClientRequest(command=RequestCommand.REGISTER_AGENT_CARD)
        register_request.set_request_data(self.card) 
        register_resp: ServerResponse = await self.client.send_client_request(register_request)
        optlog.info(f"[ServerResponse] {register_resp}", name=self.id)
        if not register_resp.success:
            await self.client.close()
            return 
        self.trenv = register_resp.data_dict['trenv'] # trenv should be in data, otherwise let it raise here

        # set order_book and pm trenv here 
        self.order_book.trenv = self.trenv 
        self.pm.my_svr = self.trenv.my_svr

        # [Subscription part]
        subs_request = ClientRequest(command=RequestCommand.SUBSCRIBE_TRP_BY_AGENT_CARD)
        subs_request.set_request_data(self.card) 
        subs_resp: ServerResponse = await self.client.send_client_request(subs_request)
        optlog.info(f"[ServerResponse] {subs_resp}", name=self.id)

        # [Sync part - getting sync data]
        self.pm.update() # to set initial values to be calculated in pm before sync 
        sync_request = ClientRequest(command=RequestCommand.SYNC_ORDER_HISTORY)
        sync_request.set_request_data((self.id, self.sync_start_date))
        sync_resp: ServerResponse = await self.client.send_client_request(sync_request)
        optlog.debug(f'[ServerResponse] {sync_resp}', name=self.id)
        sync: Sync = sync_resp.data_dict.get("sync_data") 
        await self.order_book.process_sync(sync)

        # [Sync part - releasing lock]
        release_request = ClientRequest(command=RequestCommand.SYNC_COMPLETE_NOTICE)
        release_request.set_request_data(self.id)
        release_resp: ServerResponse = await self.client.send_client_request(release_request)
        if release_resp.success:
            optlog.debug(f'[ServerResponse] {release_resp}', name=self.id)
        else: 
            log_raise(f"lock release failed ---", name=self.id)

        # [Price initialization part]
        optlog.debug(f'[Agent] waiting for initial market price', name=self.id)
        await self.agent_initial_price_set_up.wait() # ensures that pm is set with latest market data
        optlog.info(f"[Agent] ready to run strategy: {self.strategy.str_name}", name=self.id)
        self.pm.update()
        optlog.info(self.pm, name=self.id)

        # [Strategy enact part]
        asyncio.create_task(self.process_strategy_command())
        asyncio.create_task(self.strategy.logic_run())

        try:
            await self.hardstop_event.wait()
        except asyncio.CancelledError:
            optlog.info(f"[Agent] agent {self.id} hardstopped.", name=self.id)
        finally:
            # --- dashboard cleanup ---
            await self.dashboard.stop()
            # --- client cleanup ---
            await self.client.close()

    # ----------------------------------------------------------------------------------
    # str processing and order creation
    # ----------------------------------------------------------------------------------
    async def process_strategy_command(self): 
        while not self.hardstop_event.is_set():
            str_command: StrategyCommand = await self.strategy._command_queue.get()

            order = self.create_an_order(str_command)
            if self.client.is_connected: 
                optlog.info(f"[submitting new order] {order}", name=self.id)
                await self.order_book.submit_new_order(self.client, order)
                response = StrategyResponse(request=str_command.request)
            else: 
                optlog.error(f'str command {str_command} not processed - client not connected', name=self.id)
                response = None

            await self.strategy._response_queue.put(response) 

    def create_an_order(self, strategy_command: StrategyCommand): 
        if strategy_command.request == StrategyRequest.ORDER:
            side = strategy_command.side
            ord_dvsn = strategy_command.ord_dvsn
            quantity = strategy_command.quantity or 0
            price = strategy_command.price or 0
            exchange = strategy_command.exchange

            return Order(
                agent_id=self.id, 
                code=self.code, 
                listed_market=self.listed_market, 
                side=side, 
                ord_dvsn=ord_dvsn, 
                quantity=quantity, 
                price=price, 
                exchange=exchange, 
                )

        elif strategy_command.request == StrategyRequest.RC_ORDER:
            original_order: Order = strategy_command.original_order
            rc = strategy_command.rc
            all_yn = strategy_command.all_yn

            ord_dvsn = strategy_command.ord_dvsn or original_order.ord_dvsn
            if rc == RCtype.CANCEL:
                quantity = original_order.quantity - original_order.processed
            else: 
                quantity = strategy_command.quantity or original_order.quantity - original_order.processed
            price = strategy_command.price or original_order.price

            return original_order.make_revise_cancel_order(rc, ord_dvsn, quantity, price, all_yn)
        
        else:
            return None
    
    # ----------------------------------------------------------------------------------
    # on dispatch handling
    # ----------------------------------------------------------------------------------
    # msg can be 1) str, 2) Order, 3) TransactionPrices, 4) TransactionNotice
    # should be careful when datatype is dict (could be response to certain request, and captured before getting here)
    async def on_dispatch(self, data):
        TYPE_HANDLERS = {
            str: self.handle_str,
            dict: self.handle_dict, 
            Order: self.handle_order,
            ReviseCancelOrder: self.handle_order,
            TransactionPrices: self.handle_prices,
            TransactionNotice: self.handle_notice,
        }
        handler = TYPE_HANDLERS.get(type(data))
        if handler:
            await handler(data)
        else:
            optlog.error(f"[Agent] unhandled dispatch type: {type(data)}", name=self.id)
            optlog.debug(data, name=self.id)

    # handlers for dispatched msg types ---
    async def handle_str(self, msg):
        optlog.info(f"[Agent] dispatched message: {msg}", name=self.id)

    async def handle_dict(self, dict_data):
        optlog.info(f"[Agent] dispatched dict: {dict_data}", name=self.id)

    async def handle_order(self, order: Order):
        optlog.info(f"[Agent] dispatched order: {order}", name=self.id) 
        matched_order = await self.order_book.handle_order_dispatch(order)
        self.strategy.latest_sc_order = matched_order 
        self.strategy._order_receipt_event.set() 

    async def handle_prices(self, trp: TransactionPrices):
        self.market_prices.update_from_trp(trp)
        self.strategy._price_update_event.set()
        # optlog.debug(self.market_prices, name=self.id)
        self.agent_initial_price_set_up.set() 
        
    async def handle_notice(self, trn: TransactionNotice):
        optlog.info(trn, name=self.id) # show trn before processing
        notice_beep() # make a sound upton trn
        await self.order_book.process_tr_notice(trn)
        self.strategy._trn_receive_event.set()

    # ----------------------------------------------------------------------------------
    # tools
    # ----------------------------------------------------------------------------------
    async def check_psbl_buy_amount(self, ord_dvsn: ORD_DVSN, price: int):
        psbl_request = ClientRequest(command=RequestCommand.GET_PSBL_ORDER)
        psbl_request.set_request_data((self.code, ord_dvsn, price)) 
        psbl_resp: ServerResponse = await self.client.send_client_request(psbl_request)
        (a_, q_, p_) = psbl_resp.data_dict['psbl_data'] # tuple should be returned, otherwise let it raise here
        return q_


# ----------------------------------------------------------------------------------
# server tools
# ----------------------------------------------------------------------------------
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
