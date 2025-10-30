import pickle
import asyncio

from .subs_manager import SubscriptionManager
from core.common.optlog import optlog
from core.model.order import Order
from core.model.agent import AgentCard
from core.kis.domestic_stock_functions_ws import ccnl_krx, ccnl_total
from core.kis.ws_data import ORD_DVSN
from core.kis.api_tools import get_psbl_order
from app.comm.conn_agents import ConnectedAgents

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
# server side
# ---------------------------------------------------------------------------------
# list[Order]를 받아서 submit
async def handle_submit_orders(request_command, request_data_dict, writer, **server_data_dict):
    orders: list[Order] = request_data_dict.get("request_data") 
    if not isinstance(orders, list):
        if isinstance(orders, Order):
            orders = [orders]
        else: 
            return {"response_status": "invalid order-format(list) or not a proper Order object"}
    command_queue: asyncio.Queue = server_data_dict.get("command_queue")
    command = (writer, request_command, orders)
    await command_queue.put(command)
    return {"response_status": "order queued"}

# 현재 server의 모든 order에 대해 cancel을 submit
async def handle_cancel_orders(request_command, request_data_dict, writer, **server_data_dict):
    command_queue: asyncio.Queue = server_data_dict.get("command_queue")
    command = (writer, request_command, None)
    await command_queue.put(command)
    return {"response_status": "requested stop loop and cancel all orders"}

# 연결된 Agent를 Register함 (AgentCard가 ConnectedAgents에 연결)
async def handle_register_agent_card(request_command, request_data_dict, writer, **server_data_dict):
    agent_card: AgentCard = request_data_dict.get("request_data") 
    connected_agents: ConnectedAgents = server_data_dict.get('connected_agents')
    trenv = server_data_dict.get("trenv")
    agent_card.writer = writer
    agent_card.client_port = writer.get_extra_info("peername")[1] 
    msg, success = await connected_agents.add(agent_card)
    return {"response_status": msg, "response_success": success, "response_data": trenv}

# 연결된 Agent를 Remove함 - auto-remove (when disconnect)
# async def handle_remove_agent_card(request_command, request_data_dict, writer, **server_data_dict):
#     agent_card: AgentCard = request_data_dict.get("request_data") 
#     connected_agents: ConnectedAgents = server_data_dict.get('connected_agents')
#     res = await connected_agents.remove(agent_card)
#     return {"response_status": res}

# Agent의 관리 종목(code) 실시간 시세에 대해 subscribe / unsubscribe
async def handle_subscribe_trp_by_agent_card(request_command, request_data_dict, writer, **server_data_dict):
    agent_card: AgentCard = request_data_dict.get("request_data") 
    trenv = server_data_dict.get("trenv")
    subs_manager: SubscriptionManager = server_data_dict.get("subs_manager")
    if trenv.env_dv == 'demo':
        await subs_manager.add(ccnl_krx, agent_card)
    else: 
        await subs_manager.add(ccnl_total, agent_card) # 모의투자 미지원

    return {"response_status": f"{agent_card.code} subscribed by {agent_card.id}"}

# auto-unsubscribe (when disconnect)
# async def handle_unsubscribe_trp_by_agent_card(request_command, request_data_dict, writer, **server_data_dict):
#     agent_card: AgentCard = request_data_dict.get("request_data") 
#     trenv = server_data_dict.get("trenv")
#     subs_manager: SubscriptionManager = server_data_dict.get("subs_manager")
#     if trenv.env_dv == 'demo':
#         await subs_manager.remove(ccnl_krx, agent_card)
#     else: 
#         await subs_manager.remove(ccnl_total, agent_card) # 모의투자 미지원

#     return {"response_status": f"{agent_card.code} unsubscribed by {agent_card.id}"}

async def handle_get_psbl_order(request_command, request_data_dict, writer, **server_data_dict):
    trenv = server_data_dict.get("trenv")
    code, ord_dvsn, price = request_data_dict.get('request_data')
    await asyncio.sleep(trenv.sleep)
    a_, q_, p_ = get_psbl_order(trenv, code, ord_dvsn, price)
    return {"response_status": None, "response_data": (a_, q_, p_)}

# ------------------------------------------------------------
# Command registry - UNIQUE PLACE TO REGISTER
# ------------------------------------------------------------
COMMAND_HANDLERS = {
    "submit_orders": handle_submit_orders, 
    "CANCEL_orders": handle_cancel_orders, # note the cap letters
    "register_agent_card": handle_register_agent_card, 
    # "remove_agent_card": handle_remove_agent_card, # auto-remove (when disconnect)
    "subscribe_trp_by_agent_card": handle_subscribe_trp_by_agent_card, 
    # "unsubscribe_trp_by_agent_card": handle_unsubscribe_trp_by_agent_card, # auto-unsubscribe (when disconnect)
    "get_psbl_order": handle_get_psbl_order,
}

def validate_client_request(client_sent_data: bytes):
    try:
        obj = pickle.loads(client_sent_data)
    except (pickle.UnpicklingError, EOFError, AttributeError,
        ValueError, ImportError, IndexError) as e:
        return False, None, f"Invalid pickle data: {e}"
    if not isinstance(obj, dict):
        return False, None, "Unpickled object must be a dict"
    if set(obj.keys()) != {"request_id", "request_command", "request_data_dict"}:
        return False, None, "Command dict must contain exactly 'request_id', 'request_command' and 'request_data_dict' keys"
    if obj["request_command"] not in COMMAND_HANDLERS:
        return False, None, "request_command is unknown"
    if obj["request_data_dict"] is not None:
        if not isinstance(obj["request_data_dict"], dict):
            return False, None, "request_data_dict must be None or a dict"
        if 'request_data' not in obj["request_data_dict"]:
            return False, None, "request_data_dict must contain 'request_data' key"
    return True, obj, ""

async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, **server_data_dict):
    while True:
        # Read length + body
        length_bytes = await reader.read(4)
        if not length_bytes: 
            break
        length = int.from_bytes(length_bytes, "big")
        client_bytes = await reader.readexactly(length)
        valid, client_request, err_msg = validate_client_request(client_bytes)
        port = writer.get_extra_info("peername")[1] 
        agent = server_data_dict['connected_agents'].get_agent_card_by_port(port)
        if agent:
            cid = agent.id # connected client id
        else: 
            cid = port
        if valid:
            request_id: str = client_request.get("request_id")
            request_command: str = client_request.get("request_command")
            request_data_dict: dict | None = client_request.get("request_data_dict")

            optlog.info(f"Request received: {request_command}", name=cid) 
            if request_data_dict is not None:
                rd = request_data_dict.get("request_data")
                if isinstance(rd, list): 
                    if len(rd) > 1:
                        optlog.info(f"Request data: list of {len(rd)} items", name=cid)
                        for o in rd: 
                            optlog.debug(o, name=cid)
                    else: 
                        optlog.info(f"Request data: {rd[0]}", name=cid)
                else:
                    optlog.info(f"Request data: {rd}", name=cid)

            handler = COMMAND_HANDLERS.get(request_command)
            response = await handler(request_command, request_data_dict, writer, **server_data_dict)
            response['request_id'] = request_id
        else: 
            optlog.warning(f"Invalid request received - {err_msg}", name=cid)
            response = {"response_status": "Invalid request: " + err_msg}

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
            optlog.error(f"Unexpected dispatch error: {e}", name=agent.id)

