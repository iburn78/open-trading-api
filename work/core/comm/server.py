import asyncio
import json
import datetime

from .comm_interface import AgentSession
from .comm_handler import CommHandler
from .conn_agents import ConnectedAgents
from .subs_manager import SubscriptionManager
from .order_manager import OrderManager
from ..base.logger import LogSetup
from ..base.settings import Service, HOST, SERVER_PORT, DASHBOARD_SERVER_PORT, DASHBOARD_MANAGER_PORT, server_broadcast_interval, server_env_file
from ..kis.kis_connect import KIS_Connector 
from ..kis.kis_tools import KIS_Functions
from ..kis.ws_data import TransactionNotice, TransactionPrices
from ..model.aux_info import AuxInfo
from ..model.dashboard import DashBoard, DashboardManager

class Server:
    def __init__(self, service: Service, logger): 
        self.service = service
        self.logger = logger 
        # self.server_env = self.get_server_env() # for not leave it as dict
        self.kc = KIS_Connector(self.logger, self.service, self.on_result) # self.server_env)
        self.kf = KIS_Functions(self.kc)
        self.aux_info = AuxInfo(self.service)
        self.dashboard_manager = DashboardManager(self.logger, "manager", DASHBOARD_MANAGER_PORT[self.service])
        self.dashboard = DashBoard(self.logger, "server", DASHBOARD_SERVER_PORT[self.service]) # server's own dashboard
        self.dashboard_manager.register_dp(self.dashboard.owner_name, self.dashboard.port)
        self.connected_agents = ConnectedAgents(self.logger, self.dashboard_manager, self.aux_info) 
        self.order_manager = OrderManager(self.logger, self.connected_agents, self.kf, self.service)
        self.subs_manager = SubscriptionManager()
        self.comm_handler = CommHandler(self.logger, self)

    # def get_server_env(self) -> dict:
    #     if not server_env_file.exists(): return {}
    #     with open(server_env_file, 'r', encoding='utf-8') as f: return json.load(f)

    # def save_server_env(self):
    #     self.server_env['token'] = self.kc.token
    #     self.server_env['token_exp'] = self.kc.token_exp.strftime('%Y-%m-%d %H:%M:%S') if self.kc.token_exp else None
    #     # ... to be added ...

    #     self.server_env['token'] = self.kc.token
    #     with open(server_env_file, 'w', encoding='utf-8') as f:
    #         json.dump(self.server_env, f, ensure_ascii=False, indent=4)

    def on_result(self, tr_id, n_rows, d):
        target = self.kf.tr_id.get_target(tr_id)

        if target == "TransactionNotice":
            trn = TransactionNotice(n_rows, d, self.aux_info)
            self.logger.info(trn)
            self._tg.create_task(self.order_manager.process_tr_notice(trn))

        elif target == "TransactionPrices": 
            trp = TransactionPrices(n_rows, d)
            # self.logger.info(trp)
            self._tg.create_task(AgentSession.dispatch_multiple(self.connected_agents.get_target_agents_by_trp(trp), trp)) 

        self.get_status()
    
    def get_status(self): 
        text = (
            f"[Server] {self.service} - dashboard\n"
            f"----------------------------------------------------\n"
            f"{self.connected_agents}\n"
            f"{self.subs_manager}\n"
            f"{self.order_manager}\n"
            f"----------------------------------------------------"
        )
        # relay to dashboard
        self.dashboard.enqueue(text)
        return text

    async def run_comm_server(self):
        # listening on HOST:PORT
        local_server = await asyncio.start_server(self.comm_handler.handle_client, HOST, SERVER_PORT[self.service])  
        async with local_server:  
            await local_server.serve_forever()

    async def broadcast_to_clients(self):
        while True:
            await asyncio.sleep(server_broadcast_interval)
            message = datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S")
            message += ' ping from the server '
            await AgentSession.dispatch_multiple(self.connected_agents.get_all_agents(), message)
            self.logger.info(self.get_status())

    async def run(self): 
        self.logger.info(f"[Server] start running =============================================")
        try: 
            async with asyncio.TaskGroup() as tg: 
                self._tg = tg

                # websocket dashboard servers
                tg.create_task(self.dashboard.run()) # server own dashboard
                tg.create_task(self.connected_agents.dashboard_manager.run()) # collects dashboards to a brower client

                # API - server (in addition to the REST connection)
                tg.create_task(self.kc.run_websocket()) 
                await self.kc.ws_ready.wait()

                # default subscriptions
                await self.kf.ccnl_notice()

                # server - clients(agents) using asyncio reader/writer streams
                tg.create_task(self.run_comm_server()) 

                # other periodic tasks
                tg.create_task(self.broadcast_to_clients())
                tg.create_task(self.order_manager.persist_to_disk())
                tg.create_task(self.order_manager.pending_trns_timeout())
        except Exception as e: 
            self.logger.error(f"[Server] {e}", exc_info=True)
        finally: 
            await self.kc.close_httpx()
            saved_date = await self.order_manager.persist_to_disk(immediate = True)
            # self.save_server_env()
            self.logger.info(f"[Server] order_manager saved for {saved_date}")
            self.logger.info(f"[Server] shutdown completed =============================================")

if __name__ == "__main__":
    service = Service.DEMO
    logger = LogSetup(service).logger
    server = Server(service, logger)
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt: # to suppress reraised KI
        logger.info("[Server] stopped by user (Ctrl+C)\n\n")