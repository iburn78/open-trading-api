import asyncio
import logging

from .order import Order, CancelOrder
from .client import PersistentClient
from .order_book import OrderBook
from .bar import MovingBar
from .perf_metric import PerformanceMetric
from .strategy_base import StrategyBase
from ..base.logger import notice_beep
from ..base.settings import Service, SERVER_PORT
from ..kis.kis_tools import MTYPE
from ..kis.ws_data import TransactionPrices, TransactionNotice
from ..model.dashboard import DashBoard
from ..comm.comm_interface import RequestCommand, ClientRequest, ServerResponse, Sync

class Agent:
    def __init__(self, id, code, service, dp, logger, strategy):
        self.id: str = id
        self.code: str = code
        self.service: Service = service
        self.dp: int = dp # dashboard port 
        self.logger: logging.Logger = logger

        # dashboard
        self.dashboard = DashBoard(logger=self.logger, owner_name=self.id, port=self.dp) 

        # for server communication
        self.client = PersistentClient(id = self.id, logger = self.logger, port=SERVER_PORT[self.service], on_dispatch=self.on_dispatch)
        self.hardstop_event = asyncio.Event() # to finish agent activity

        # data tracking and strategy
        self.order_book = OrderBook(agent_id=self.id, code=self.code, logger=self.logger)
        self.moving_bar = MovingBar(code=self.code)
        self.strategy: StrategyBase = strategy
        self.pm = PerformanceMetric(agent_id=self.id, code=self.code, service=self.service, order_book=self.order_book, moving_bar=self.moving_bar, dashboard=self.dashboard)

        # other flags
        self.initialized: bool = False
        self.agent_ready_to_run_strategy: bool = False
        self.agent_initial_price_set_up = asyncio.Event() # wheather the first TNP is received (so that pm can be properly initialized)
        self.sync_start_date: str | None = None # isoformat date ("yyyy-mm-dd") # should be assigned in initialize() 

        # strategy specific (ABC subclass instance)
        self.strategy.agent_id = self.id
        self.strategy.code = self.code
        self.strategy.logger = self.logger
        self.strategy.dashboard = self.dashboard
        self.strategy.submit_order = self.submit_order
        self.strategy.pm = self.pm

    def initialize(self, init_cash_allocated = 0, init_holding_qty = 0, 
                            init_avg_price = 0, sync_start_date = None):
        if init_cash_allocated < 0 or init_holding_qty < 0 or init_avg_price < 0: 
            self.logger.error(f"[Agent] negative initialization not allowed - not initialized", extra={"owner": self.id})
            return
        self.pm.init_cash_allocated = init_cash_allocated
        self.pm.init_holding_qty = init_holding_qty
        self.pm.init_avg_price = init_avg_price
        self.sync_start_date = sync_start_date # default to be today (if None: today)
        self.initialized = True
    
    async def run(self):
        """  
        Keeps the agent alive until stopped.
        agent's main loop 
        - to be run in an asyncio task
        - has to be the starting point of the agent
        - does 1) connect to server, 2) register itself, 3) subscribe to trp by code, 4) wait until stopped
        - orders can be made afterward
        """
        if not self.initialized: 
            self.logger.error(f"[Agent] agent not initialized - agent run aborted", extra={"owner": self.id})
            return 
        self.logger.info(f"[Agent] start running =============================================", extra={"owner": self.id})

        try:
            async with asyncio.TaskGroup() as tg:
                tasks = []
                tasks.append(tg.create_task(self.client.connect()))
                await self.client.connected.wait()

                # [DashBoard enact part]
                tasks.append(tg.create_task(self.dashboard.run()))

                # [Registration part]
                register_request = ClientRequest(command=RequestCommand.REGISTER_AGENT)
                register_request.set_request_data((self.id, self.code, self.dp)) 
                register_resp: ServerResponse | None = await self.client.send_client_request(register_request)
                if register_resp is None: 
                    raise asyncio.CancelledError 
                self.logger.info(f"[Agent] ServerResponse {register_resp}", extra={"owner": self.id})
                if not register_resp.success:
                    raise asyncio.CancelledError 

                # [Sync part - getting sync data]
                sync_request = ClientRequest(command=RequestCommand.SYNC_ORDER_HISTORY)
                sync_request.set_request_data(self.sync_start_date)
                sync_resp: ServerResponse | None = await self.client.send_client_request(sync_request)
                if sync_resp is None: 
                    raise asyncio.CancelledError 
                self.logger.info(f"[Agent] ServerResponse {sync_resp}", extra={"owner": self.id})
                sync: Sync = sync_resp.data_dict.get("sync_data") 
                await self.order_book.process_sync(sync)

                # [Sync part - releasing lock]
                release_request = ClientRequest(command=RequestCommand.SYNC_COMPLETE_NOTICE)
                release_resp: ServerResponse | None = await self.client.send_client_request(release_request)
                if release_resp is None: 
                    raise asyncio.CancelledError 
                if release_resp.success:
                    self.logger.info(f"[Agent] ServerResponse {release_resp}", extra={"owner": self.id})
                else: 
                    self.logger.error(f"[Agent] ServerResponse lock release failed", extra={"owner": self.id})
        
                # [Subscription part]
                subs_request = ClientRequest(command=RequestCommand.SUBSCRIBE_TRP)
                subs_resp: ServerResponse | None = await self.client.send_client_request(subs_request)
                if subs_resp is None:
                    raise asyncio.CancelledError 
                self.logger.info(f"[Agent] ServerResponse {subs_resp}", extra={"owner": self.id})

                # [Price initialization part]
                self.logger.info(f"[Agent] waiting for initial market price", extra={"owner": self.id})
                await self.agent_initial_price_set_up.wait() # ensures set with latest market data
                self.agent_ready_to_run_strategy = True
                self.logger.info(f"[Agent] ready to run strategy: {self.strategy.str_name}", extra={"owner": self.id})

                # [Strategy enact part]
                tasks.append(tg.create_task(self.strategy.logic_run()))

                # [Hard stop part]
                await self.hardstop_event.wait()
                # - need to cancel explicitly as tasks are long living
                for t in tasks:
                    t.cancel()
        
        finally:
            self.logger.info(f"[Agent] run completed =============================================", extra={"owner": self.id})

    # ----------------------------------------------------------------------------------
    # order handling
    # ----------------------------------------------------------------------------------
    async def submit_order(self, order_list: list[Order | CancelOrder]):
        if self.client.is_connected:
            # fire and forget: Server will send back individual order updates via on_dispatch
            submit_request = ClientRequest(command=RequestCommand.SUBMIT_ORDERS)
            submit_request.set_request_data(order_list)
            res: ServerResponse | None = await self.client.send_client_request(submit_request) 
            if res is None:
                return False
            if isinstance(res, ServerResponse):
                return res.success
        else:
            self.logger.error(f"[Agent] submit order not processed - client not connected", extra={"owner": self.id})
        return False

    # ----------------------------------------------------------------------------------
    # on dispatch handling
    # ----------------------------------------------------------------------------------
    async def on_dispatch(self, data):
        TYPE_HANDLERS = {
            str: self.handle_str,
            Order: self.handle_order,
            CancelOrder: self.handle_order,
            TransactionPrices: self.handle_prices,
            TransactionNotice: self.handle_notice,
        }
        handler = TYPE_HANDLERS.get(type(data))
        if handler:
            await handler(data)
        else:
            self.logger.error(f"[Agent] unhandled dispatch type: {type(data)}", extra={"owner": self.id})
            self.logger.debug(data)

    async def handle_str(self, msg):
        self.logger.info(f"[Agent] dispatched message: {msg}", extra={"owner": self.id})

    async def handle_order(self, order: Order | CancelOrder):
        # self.logger.info(f"[Agent] dispatched order: no {order.order_no} uid {order.unique_id}", extra={"owner": self.id})
        if not order.submitted: 
            self.logger.warning(f'[OrderBook] non-submitted order received {order.order_no}\n    {order}\n    could be 초당거래건수 / 주문가능금액부족 issues', extra={"owner": self.id})
            self.strategy.handle_order_dispatch(order) # if not submitted at all then, let strategy know
            return
        await self.order_book.handle_order_dispatch(order)
        if order.accepted: # and may consume additional trns
            self.pm.update()
            self.logger.info(self.pm, extra={"owner": self.id})
            self.strategy.handle_order_dispatch(order)
        # if the submitted but not yet accepted order should not be handled here for strategy future matching (will be handled when accepted by trn) 

    async def handle_prices(self, trp: TransactionPrices):
        # self.logger.info(trp, extra={"owner": self.id})

        self.moving_bar.update(trp.price, trp.quantity, trp.time)
        # self.logger.info(self.moving_bar, extra={"owner": self.id})

        self.strategy.raw_bars.update(trp.price, trp.quantity, trp.time)

        if not self.agent_ready_to_run_strategy:
            self.pm.update() # initial full update
            self.logger.info(self.pm, extra={"owner": self.id})
            self.agent_initial_price_set_up.set() 
        else: 
            self.pm.update(price_update_only=True) 

        self.strategy._price_update_event.set()
        
    async def handle_notice(self, trn: TransactionNotice):
        self.logger.info(trn, extra={"owner": self.id}) # show trn before processing
        notice_beep() # make a sound upton trn
        order = await self.order_book.process_tr_notice(trn) # returns order only when it is newly accepted
        if trn.consumed: 
            self.pm.update() 
            self.logger.info(self.pm, extra={"owner": self.id})
        if order is not None: # accepted order
            self.strategy.handle_order_dispatch(order)
        self.strategy._trn_receive_event.set()

    # ----------------------------------------------------------------------------------
    # tools
    # ----------------------------------------------------------------------------------
    async def check_psbl_buy_amount(self, mtype: MTYPE, price: int):
        psbl_request = ClientRequest(command=RequestCommand.GET_PSBL_ORDER)
        psbl_request.set_request_data((self.code, mtype, price)) 
        res: ServerResponse | None = await self.client.send_client_request(psbl_request)
        if res.success:
            (a_, q_, p_) = res.data_dict['psbl_data'] 
            # order quantity should be less than or equal to q_
            return q_
        return None

# minimal agent running example
if __name__ == "__main__":
    from ..base.logger import LogSetup
    from ..strategy.double_up import DoubleUpStrategy

    service = Service.DEMO
    logger = LogSetup(service).logger

    A = Agent(id = '_Agent_001', code = '005930', service=service, dp = 8051, logger=logger, strategy=DoubleUpStrategy())
    A.initialize(init_cash_allocated=100_000_000, init_holding_qty=0, init_avg_price=0, sync_start_date='2026-01-01')
    try:
        asyncio.run(A.run())
    except KeyboardInterrupt: 
        logger.info("[Agent] stopped by user (Ctrl+C)\n\n")