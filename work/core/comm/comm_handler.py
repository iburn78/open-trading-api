import pickle
import asyncio

from .comm_interface import RequestCommand, ClientRequest, ServerResponse, Sync, Dispatch_ACK
from .conn_agents import ConnectedAgents
from .subs_manager import SubscriptionManager
from .order_manager import OrderManager
from ..model.agent import AgentCard
from ..kis.kis_tools import KIS_Functions

# CommunicationHandler for local communication
class CommHandler: 
    def __init__(self, logger, server):
        self.logger = logger
        self.connected_agents: ConnectedAgents = server.connected_agents
        self.subs_manager: SubscriptionManager = server.subs_manager
        self.order_manager: OrderManager = server.order_manager
        self.kf: KIS_Functions = server.kf
        self.COMMAND_HANDLERS = {
            RequestCommand.SUBMIT_ORDERS: self.handle_submit_orders, 
            RequestCommand.REGISTER_AGENT_CARD: self.handle_register_agent_card, 
            RequestCommand.SYNC_ORDER_HISTORY: self.handle_sync_order_history,
            RequestCommand.SYNC_COMPLETE_NOTICE: self.handle_sync_complete_notice,
            RequestCommand.SUBSCRIBE_TRP: self.handle_subscribe_trp, 
            RequestCommand.GET_PSBL_ORDER: self.handle_get_psbl_order,
        }

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info("peername") # peername: network term / uniqe in a session
        client_port = addr[1] # uniquley assigned by OS and TCP per client
        self.logger.info(f"[CommHandler] client connected {addr}")

        try: 
            while True:
                length_bytes = await reader.read(4)
                if not length_bytes: break 

                length = int.from_bytes(length_bytes, "big")
                client_bytes = await reader.readexactly(length)

                client_msg = pickle.loads(client_bytes)

                if isinstance(client_msg, Dispatch_ACK):
                    await self.order_manager.ack_received(client_msg)
                    continue

                client_request: ClientRequest = client_msg
                rd = client_request.get_request_data()

                logmsg = f"[CommHandler] request received: {client_request}"
                if rd:  
                    if not isinstance(rd, list): rd = [rd]
                    for d in rd: 
                        logmsg += f"\n    {d}"
                self.logger.info(logmsg)

                handler = self.COMMAND_HANDLERS.get(client_request.command)
                kwargs = {'writer': writer, 'client_port': client_port}
                response: ServerResponse = await handler(client_request, **kwargs)
                response.request_id = client_request.request_id

                # Send response back
                resp_bytes = pickle.dumps(response)
                writer.write(len(resp_bytes).to_bytes(4, "big"))
                writer.write(resp_bytes)
                await writer.drain()
        except Exception as e:
            self.logger.error(f"[CommHandler] handler error {addr}: {e}", exc_info=True)
        except asyncio.CancelledError:
            raise
        finally:
            # clean-up
            agent = self.connected_agents.get_agent_by_port(client_port)
            if agent:
                self.logger.info(f"[CommHandler] cleaning-up agent {agent.id}")
                await self.subs_manager.remove(agent)
                await self.connected_agents.remove(agent)
            else:     
                self.logger.error(f"[CommHandler] agent not found for client_port {client_port}")
            writer.close()
            await writer.wait_closed()

    # list[Order|CancelOrder]를 받아서 submit
    async def handle_submit_orders(self, client_request: ClientRequest, **kwargs):
        orders = client_request.get_request_data()
        res: bool = await self.order_manager.submit_orders_and_register(orders)
        return ServerResponse(success=res, status='order queued')

    # 연결된 Agent를 Register 
    async def handle_register_agent_card(self, client_request: ClientRequest, **kwargs):
        agent: AgentCard = client_request.get_request_data()
        # set server-side data to agent_card
        agent.writer = kwargs.get('writer') # used in agent dispatch
        agent.client_port = kwargs.get('client_port')
        success, msg = await self.connected_agents.add(agent)

        # return with registration status
        res = ServerResponse(success, msg)
        return res

    # agent sync with server 
    async def handle_sync_order_history(self, client_request: ClientRequest, **kwargs):
        sync_start_date = client_request.get_request_data()
        agent: AgentCard = self.connected_agents.get_agent_by_port(kwargs.get('client_port'))
        sync: Sync = await self.order_manager.get_agent_sync(agent, sync_start_date=sync_start_date)

        # return with sync data
        res = ServerResponse(True, "sync request submitted")
        res.data_dict['sync_data'] = sync
        return res

    async def handle_sync_complete_notice(self, client_request: ClientRequest, **kwargs):
        agent: AgentCard = self.connected_agents.get_agent_by_port(kwargs.get('client_port'))
        success = await self.order_manager.agent_sync_completed_lock_release(agent)

        # return with sync data
        if success:
            return ServerResponse(success, "sync-release completed")
        else: 
            return ServerResponse(success, "")

    # Agent의 종목(code) 실시간 시세에 대해 subscribe / unsubscribe
    async def handle_subscribe_trp(self, client_request: ClientRequest, **kwargs):
        agent: AgentCard = self.connected_agents.get_agent_by_port(kwargs.get('client_port'))
        msg = await self.subs_manager.add(agent, self.kf.ccnl_krx)
    
        return ServerResponse(success=True, status=msg)

    async def handle_get_psbl_order(self, client_request: ClientRequest, **kwargs):
        code, mtype, price = client_request.get_request_data()
        a_, q_, p_ = await self.kf.get_psbl_order(code, mtype, price)

        res = ServerResponse(success=True, status="")
        res.data_dict['psbl_data'] = (a_, q_, p_)
        return res


