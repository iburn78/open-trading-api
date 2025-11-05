import pickle
import asyncio

from .subs_manager import SubscriptionManager
from .conn_agents import ConnectedAgents
from .order_manager import OrderManager
from core.common.optlog import optlog
from core.model.agent import AgentCard
from core.common.interface import RequestCommand, ClientRequest, ServerResponse
from core.kis.domestic_stock_functions_ws import ccnl_krx, ccnl_total
from core.kis.api_tools import get_psbl_order

# ---------------------------------------------------------------------------------
# the following run in server side
# ---------------------------------------------------------------------------------
# list[Order]를 받아서 submit
async def handle_submit_orders(client_request: ClientRequest, writer, **server_data_dict):
    order_manager: OrderManager = server_data_dict.get('order_manager')
    connected_agents: ConnectedAgents = server_data_dict.get('connected_agents')
    trenv = server_data_dict.get("trenv")

    # agents should be registered already.
    port = writer.get_extra_info("peername")[1] 
    agent = connected_agents.get_agent_card_by_port(port)
    orders = client_request.get_request_data()

    await order_manager.submit_orders_and_register(agent, orders, trenv)
    # no need to assign any value to ServerResponse as the command is already processed, and return value is meaningless at this moment
    # however, empty ServerResponse object return required to match request-response 
    return ServerResponse(success=True, status='order queued')

# 현재 server의 모든 agent-sepcific pending order에 대해 cancel을 submit 
# below client_request.command is already used to get here
async def handle_cancel_all_orders_by_agent(client_request: ClientRequest, writer, **server_data_dict):
    order_manager: OrderManager = server_data_dict.get('order_manager')
    connected_agents: ConnectedAgents = server_data_dict.get('connected_agents')
    trenv = server_data_dict.get("trenv")

    port = writer.get_extra_info("peername")[1] 
    agent = connected_agents.get_agent_card_by_port(port)

    await order_manager.cancel_all_outstanding_for_agent(agent, trenv)
    await order_manager.closing_checker(agent)
    # no need to assign any value to ServerResponse as the command is already processed, and return value is meaningless at this moment
    # however, empty ServerResponse object return required to match request-response 
    return ServerResponse(success=True, status=f'cancel requested for agent {agent.id}')

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
    resp.data_dict['trenv'] = server_data_dict.get("trenv")
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
    resp.data_dict['psbl_data'] = (a_, q_, p_)
    return resp

# ------------------------------------------------------------
# Command registry - UNIQUE PLACE TO REGISTER
# ------------------------------------------------------------
COMMAND_HANDLERS = {
    RequestCommand.SUBMIT_ORDERS: handle_submit_orders, 
    RequestCommand.CANCEL_ALL_ORDERS_BY_AGENT: handle_cancel_all_orders_by_agent, 
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
            # client id is set back to the server response when the response is generated by a handler
            response.set_id(client_request)

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
