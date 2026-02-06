import pickle
import asyncio

from .comm_interface import RequestCommand, ClientRequest, ServerResponse, Sync, Dispatch_ACK, AgentSession
from .order_manager import OrderManager
from .conn_agents import ConnectedAgents
from .subs_manager import SubscriptionManager

# CommunicationHandler for local communication
# CommHandler (single instance in server and used by asyncio.start_server(...))
 # ├─ handle_client()  ← client A / Session A
 # ├─ handle_client()  ← client B / Session B
 # └─ handle_client()  ← client C / Session C
class CommHandler: 
    def __init__(self, logger, server):
        self.logger = logger
        self.connected_agents: ConnectedAgents = server.connected_agents 
        self.subs_manager: SubscriptionManager = server.subs_manager
        self.order_manager: OrderManager = server.order_manager
        self.kf = server.kf
        self.COMMAND_HANDLERS = {
            RequestCommand.SUBMIT_ORDERS: self.handle_submit_orders, 
            RequestCommand.REGISTER_AGENT: self.handle_register_agent, 
            RequestCommand.SYNC_ORDER_HISTORY: self.handle_sync_order_history,
            RequestCommand.SYNC_COMPLETE_NOTICE: self.handle_sync_complete_notice,
            RequestCommand.SUBSCRIBE_TRP: self.handle_subscribe_trp, 
            RequestCommand.GET_PSBL_ORDER: self.handle_get_psbl_order,
        }

    async def writer_loop(self, agent: AgentSession):
        try:
            while True:
                data = await agent._send_queue.get()
                if data is None:  # shutdown signal
                    break

                agent.writer.write(len(data).to_bytes(4, "big") + data) # only bytes are accepted
                await agent.writer.drain()

        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError) as e:
            self.logger.warning(
                f"[CommHandler] writer error for agent {agent.id}: {e}",
                extra={"owner": agent.id}
            )

        finally:
            agent.writer.close()
            try:
                await agent.writer.wait_closed()
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as e:
                pass # suppress windows errors

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info("peername") # peername: network term / uniqe in a session
        agent = AgentSession() # agent_session is created here and assign session data first, later than agent-specific data
        agent.reader = reader
        agent.writer = writer
        
        self.logger.info(f"[CommHandler] client connected {peer}")
        writer_task = asyncio.create_task(self.writer_loop(agent))

        try: 
            while True:
                length_bytes = await reader.read(4)
                if not length_bytes: break 

                length = int.from_bytes(length_bytes, "big")
                payload = await reader.readexactly(length)

                client_msg = pickle.loads(payload)

                # process incoming
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
                self.logger.info(logmsg, extra={"owner": agent.id if agent.id is not None else peer[1]}) # client_port

                handler = self.COMMAND_HANDLERS.get(client_request.command)
                response: ServerResponse = await handler(client_request, agent)
                response.request_id = client_request.request_id

                # Send response back
                await agent.dispatch(response)
        
        except ConnectionAbortedError as e: 
            self.logger.info(f"[CommHandler] connection aborted at client port {peer[1]}: {e}")

        except Exception as e:
            self.logger.error(f"[CommHandler] handler error at client port {peer[1]}: {e}", exc_info=True)

        finally:
            await agent._send_queue.put(None) # stop writer
            await writer_task

            if agent.connected:
                self.logger.info(f"[CommHandler] cleaning-up agent {agent.id}", extra={"owner": agent.id})
                res = await self.subs_manager.remove(agent)
                self.logger.info(res, extra={"owner": agent.id})
                res = await self.connected_agents.remove(agent)
                self.logger.info(res, extra={"owner": agent.id})
                agent.connected = False

    # list[Order|CancelOrder]를 받아서 submit
    async def handle_submit_orders(self, client_request: ClientRequest, agent: AgentSession):
        orders = client_request.get_request_data()
        res: bool = await self.order_manager.submit_orders_and_register(agent, orders)
        return ServerResponse(success=res, status='order queued')

    # 연결된 Agent를 Register 
    async def handle_register_agent(self, client_request: ClientRequest, agent: AgentSession):
        agent.id, agent.code, agent.dp = client_request.get_request_data()
        agent.connected = True
        success, msg = await self.connected_agents.add(agent) 
        self.logger.info(f"agent registered at client port {agent.writer.get_extra_info('peername')[1]}", extra={"owner": agent.id})

        # return with registration status
        res = ServerResponse(success, msg)
        return res

    # agent sync with server 
    async def handle_sync_order_history(self, client_request: ClientRequest, agent: AgentSession):
        sync_start_date = client_request.get_request_data()
        sync: Sync = await self.order_manager.get_agent_sync(agent, sync_start_date=sync_start_date)

        # return with sync data
        res = ServerResponse(True, "sync request submitted")
        res.data_dict['sync_data'] = sync
        return res

    async def handle_sync_complete_notice(self, client_request: ClientRequest, agent: AgentSession):
        success = await self.order_manager.agent_sync_completed_lock_release(agent)

        # return with sync data
        if success:
            return ServerResponse(success, "sync-release completed")
        else: 
            return ServerResponse(success, "")

    # Agent의 종목(code) 실시간 시세에 대해 subscribe / unsubscribe
    async def handle_subscribe_trp(self, client_request: ClientRequest, agent: AgentSession):
        msg = await self.subs_manager.add(agent, self.kf.ccnl_krx)
        self.logger.info(f"agent {agent.id} trp ({agent.code}) subscribed", extra={"owner": agent.id})
    
        return ServerResponse(success=True, status=msg)

    async def handle_get_psbl_order(self, client_request: ClientRequest, agent: AgentSession):
        code, mtype, price = client_request.get_request_data()
        a_, q_, p_ = await self.kf.get_psbl_order(code, mtype, price)

        res = ServerResponse(success=True, status="")
        res.data_dict['psbl_data'] = (a_, q_, p_)
        return res


