import pickle
import asyncio

from .subs_manager import SubscriptionManager
from .conn_agents import ConnectedAgents
from core.common.optlog import optlog
from core.model.order import Order
from core.model.agent import AgentCard
from core.model.interface import RequestCommand, ClientRequest, ServerResponse, CommandQueueInput
from core.kis.domestic_stock_functions_ws import ccnl_krx, ccnl_total
from core.kis.api_tools import get_psbl_order

"""
---------------------------------------------------------------------------------
Parameters:
    - request_data_dict.get("request_data"): from client
    - server_data_dict: from server 

Processing order in server:
    - command_queue put(): tuple (writer, request_command: str, request_data: obj) # request_data is from request_data_dict.get("request_data") 
    - return: dict {"response_status": str, "response_data": obj | None}
---------------------------------------------------------------------------------
"""
# ---------------------------------------------------------------------------------
# the following run in server side
# ---------------------------------------------------------------------------------
# list[Order]를 받아서 submit
async def handle_submit_orders(client_request: ClientRequest, writer, **server_data_dict):
    await server_data_dict.get("command_queue").put(CommandQueueInput(writer, client_request))
    return ServerResponse(success=True, status="order queued")

# 현재 server의 모든 order에 대해 cancel을 submit 
async def handle_cancel_orders(client_request: ClientRequest, writer, **server_data_dict):
    await server_data_dict.get("command_queue").put(CommandQueueInput(writer, client_request))
    return ServerResponse(success=True, status="requested cancel all orders")

# 연결된 Agent를 Register함 (AgentCard가 ConnectedAgents에 연결)
# when disconnected, auto-remove (or use connected_agents.remove(agent_card))
async def handle_register_agent_card(client_request: ClientRequest, writer, **server_data_dict):
    agent_card: AgentCard = client_request.get_request_data()
    connected_agents: ConnectedAgents = server_data_dict.get('connected_agents')

    # set server-side data to agent_card
    agent_card.writer = writer
    agent_card.client_port = writer.get_extra_info("peername")[1] 
    success, msg = await connected_agents.add(agent_card)

    # return with trenv data
    resp = ServerResponse(success, msg)
    resp.data['trenv'] = server_data_dict.get("trenv")
    return resp

# Agent의 관리 종목(code) 실시간 시세에 대해 subscribe / unsubscribe
# when disconnected, auto-unsubscribe (or use subs_manager.remove(subs_name, agent_card), where subs_name is ccnl_krx or ccnl_total, etc)
async def handle_subscribe_trp_by_agent_card(client_request: ClientRequest, writer, **server_data_dict):
    agent_card: AgentCard = client_request.get_request_data()
    trenv = server_data_dict.get("trenv")
    subs_manager: SubscriptionManager = server_data_dict.get("subs_manager")

    if trenv.env_dv == 'demo':
        msg = await subs_manager.add(ccnl_krx, agent_card)
    else: 
        msg = await subs_manager.add(ccnl_total, agent_card) # 모의투자 미지원
    
    # request itself is surely successful 
    # if API refueses accept, then API will raise or return error message
    return ServerResponse(success=True, status=msg)

async def handle_get_psbl_order(client_request: ClientRequest, writer, **server_data_dict):
    trenv = server_data_dict.get("trenv")
    code, ord_dvsn, price = client_request.get_request_data()
    a_, q_, p_ = get_psbl_order(trenv, code, ord_dvsn, price)
    await asyncio.sleep(trenv.sleep)

    resp = ServerResponse(success=True, status="")
    resp.data['psbl_data'] = (a_, q_, p_)
    return resp

# ------------------------------------------------------------
# Command registry - UNIQUE PLACE TO REGISTER
# ------------------------------------------------------------
###_make it ABS 
'''
from abc import ABC, abstractmethod

class Command(ABC):
    @abstractmethod
    async def execute(self, context: ServerContext) -> CommandResult:
        pass

class SubmitOrdersCommand(Command):
    def __init__(self, orders: list[Order]):
        self.orders = orders
    
    async def execute(self, context: ServerContext) -> CommandResult:
        # Implementation
        pass

'''
COMMAND_HANDLERS = {
    RequestCommand.SUBMIT_ORDERS: handle_submit_orders, 
    RequestCommand.CANCEL_ORDERS: handle_cancel_orders, 
    RequestCommand.REGISTER_AGENT_CARD: handle_register_agent_card, 
    RequestCommand.SUBSCRIBE_TRP_BY_AGENT_CARD: handle_subscribe_trp_by_agent_card, 
    RequestCommand.GET_PSBL_ORDER: handle_get_psbl_order,
}

async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, **server_data_dict):
    port = writer.get_extra_info("peername")[1] 
    cid = port
    agent = None
    while True:
        if agent is None:
            # agent assigned after register, so need to read
            agent = server_data_dict['connected_agents'].get_agent_card_by_port(port)
            if agent: cid = agent.id

        # Read length + body
        length_bytes = await reader.read(4)
        if not length_bytes: break

        length = int.from_bytes(length_bytes, "big")
        client_bytes = await reader.readexactly(length)

        try:
            client_request: ClientRequest = pickle.loads(client_bytes)
            optlog.info(f"Request received: {client_request}", name=cid) 

            rd = client_request.get_request_data()
            if rd and isinstance(rd, list): 
                optlog.info(f"Request data: list ({len(rd)} items)", name=cid)
                for o in rd: 
                    optlog.debug(o, name=cid)
            elif rd:
                optlog.info(f"Request data: {rd}", name=cid)

            handler = COMMAND_HANDLERS.get(client_request.command)
            response: ServerResponse = await handler(client_request, writer, **server_data_dict)

        except (pickle.UnpicklingError, EOFError, AttributeError,
            ValueError, ImportError, IndexError) as e:
            response = ServerResponse(success=False, status=f"client request pickle load error {e}")
            optlog.error(response, name=cid, exc_info=True)

        except Exception as e:
            response = ServerResponse(success=False, status=f"invalid client request {e}")
            optlog.error(response, name=cid, exc_info=True)

        # Send response back
        resp_bytes = pickle.dumps(response)
        writer.write(len(resp_bytes).to_bytes(4, "big"))
        writer.write(resp_bytes)
        await writer.drain()

async def dispatch(to: AgentCard | list[AgentCard], message: object):
    if not to:
        optlog.info(f"No agents to dispatch: {message}")

    if isinstance(to, AgentCard):
        to = [to]

    data = pickle.dumps(message)
    msg_bytes = len(data).to_bytes(4, 'big') + data
    for agent in to:
        try:
            agent.writer.write(msg_bytes)
            await agent.writer.drain()  # await ensures exceptions are caught here
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            optlog.error(f"Agent {agent.id} (port {agent.client_port}) disconnected - dispatch msg failed.", name=agent.id)
        except Exception as e:
            optlog.error(f"Unexpected dispatch error: {e}", name=agent.id, exc_info=True)

