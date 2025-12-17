import pickle
import asyncio

from .subs_manager import SubscriptionManager
from .conn_agents import ConnectedAgents
from .order_manager import OrderManager
from core.common.optlog import optlog, LOG_INDENT
from core.model.agent import AgentCard
from core.common.interface import RequestCommand, ClientRequest, ServerResponse, Sync
from core.kis.domestic_stock_functions_ws import ccnl_krx, ccnl_total
from core.kis.api_tools import get_psbl_order

# ---------------------------------------------------------------------------------
# the following run in server side
# ---------------------------------------------------------------------------------
# list[Order|CancelOrder]를 받아서 submit
async def handle_submit_orders(client_request: ClientRequest, writer, **server_data_dict):
    order_manager: OrderManager = server_data_dict.get('order_manager')
    connected_agents: ConnectedAgents = server_data_dict.get('connected_agents')
    trenv = server_data_dict.get("trenv")

    # agents should be registered already.
    port = writer.get_extra_info("peername")[1] 
    agent = connected_agents.get_agent_card_by_port(port)
    orders = client_request.get_request_data()

    res: bool = await order_manager.submit_orders_and_register(agent, orders, trenv)
    return ServerResponse(success=res, status='order queued')

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

# agent sync with server 
async def handle_sync_order_history(client_request: ClientRequest, writer, **server_data_dict):
    agent_id, sync_start_date = client_request.get_request_data()
    connected_agents: ConnectedAgents = server_data_dict.get('connected_agents')
    agent_card: AgentCard = connected_agents.get_agent_card_by_id(agent_id)
    order_manager: OrderManager = server_data_dict.get('order_manager')

    sync: Sync = await order_manager.get_agent_sync(agent_card, sync_start_date=sync_start_date)

    # return with sync data
    resp = ServerResponse(True, "sync request submitted")
    resp.data_dict['sync_data'] = sync
    return resp

async def handle_sync_complete_notice(client_request: ClientRequest, writer, **server_data_dict):
    agent_id: str = client_request.get_request_data()
    connected_agents: ConnectedAgents = server_data_dict.get('connected_agents')
    agent_card: AgentCard = connected_agents.get_agent_card_by_id(agent_id)
    order_manager: OrderManager = server_data_dict.get('order_manager')

    success = order_manager.agent_sync_completed_lock_release(agent_card)
    # return with sync data
    if success:
        resp = ServerResponse(success, "sync-release completed")
    else: 
        resp = ServerResponse(success, "")
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
    a_, q_, p_ = await get_psbl_order(trenv, code, ord_dvsn, price)

    resp = ServerResponse(success=True, status="")
    resp.data_dict['psbl_data'] = (a_, q_, p_)
    return resp

# ------------------------------------------------------------
# Command registry - UNIQUE PLACE TO REGISTER in the server side
# ------------------------------------------------------------
COMMAND_HANDLERS = {
    RequestCommand.SUBMIT_ORDERS: handle_submit_orders, 
    RequestCommand.REGISTER_AGENT_CARD: handle_register_agent_card, 
    RequestCommand.SYNC_ORDER_HISTORY: handle_sync_order_history,
    RequestCommand.SYNC_COMPLETE_NOTICE: handle_sync_complete_notice,
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
            logmsg = f"[request received] {client_request}"

            rd = client_request.get_request_data()
            if rd and isinstance(rd, list): 
                logmsg += f"\n{LOG_INDENT}request data: list ({len(rd)} items)"
                for o in rd: 
                    logmsg += f"\n{LOG_INDENT}{o}"
            elif rd:
                logmsg += f"\n{LOG_INDENT}request data: {rd}"
            optlog.info(logmsg, name=cid)

            handler = COMMAND_HANDLERS.get(client_request.command)
            response: ServerResponse = await handler(client_request, writer, **server_data_dict)
            response.set_attr(client_request)

        except (pickle.UnpicklingError, EOFError, AttributeError,
            ValueError, ImportError, IndexError) as e:
            response = ServerResponse(success=False, status=f"client request load error {e}")
            optlog.error(f"[HandleClient] {response}", name=cid, exc_info=True)

        except Exception as e:
            response = ServerResponse(success=False, status=f"invalid client request (or unknown error) {e}")
            optlog.error(f"[HandleClient] {response}", name=cid, exc_info=True)

        # Send response back
        resp_bytes = pickle.dumps(response)
        writer.write(len(resp_bytes).to_bytes(4, "big"))
        writer.write(resp_bytes)
        await writer.drain()
