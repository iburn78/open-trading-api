import pickle
import asyncio
from gen_tools import optlog, log_raise
from kis_tools import Order, OrderList
from agent import ConnectedAgents, AgentCard
from domestic_stock_functions_ws import ccnl_krx, ccnl_total

# ---------------------------------------------------------------------------------
# Parameters:
#     - request_data_dict.get("request_data"): from client
#     - server_data_dict: from server 
# Generating responses:
#     - command_queue put(): tuple (request_command: str, request_data: obj)
#     - return: dict {"response_status": str, "response_data": obj}
# ---------------------------------------------------------------------------------

# ---------------------------------------------------------------------------------
# server side
# ---------------------------------------------------------------------------------
# 현재 server의 trenv를 return
async def handle_get_trenv(request_command, request_data_dict, **server_data_dict):
    trenv = server_data_dict.get("trenv")
    return {"response_status": "trenv info retrieved", "response_data": trenv}

# master_order_list return
async def handle_get_orderlist(request_command, request_data_dict, **server_data_dict):
    master_orderlist: OrderList = server_data_dict.get("master_orderlist", None)
    return {"response_status": "orders retrieved", "response_data": master_orderlist}

# list[Order]를 받아서 submit
async def handle_submit_order(request_command, request_data_dict, **server_data_dict):
    orderlist: list[Order] = request_data_dict.get("request_data") 
    command_queue: asyncio.Queue = server_data_dict.get("command_queue")
    command = (request_command, orderlist)
    await command_queue.put(command)
    return {"response_status": "order queued"}

# 현재 server의 모든 order에 대해 cancel을 submit
async def handle_cancel_orders(request_command, request_data_dict, **server_data_dict):
    command_queue: asyncio.Queue = server_data_dict.get("command_queue")
    command = (request_command, None)
    await command_queue.put(command)
    return {"response_status": "stop loop and cancel all orders requested"}

# 연결된 Agent를 Register함 (AgentCard가 ConnectedAgents에 연결)
async def handle_register_agent_card(request_command, request_data_dict, **server_data_dict):
    agent_card: AgentCard = request_data_dict.get("request_data") 
    connected_agents: ConnectedAgents = server_data_dict.get('connected_agents')
    res = await connected_agents.add(agent_card)
    return {"response_status": res}

# 연결된 Agent를 Remove함 
async def handle_remove_agent_card(request_command, request_data_dict, **server_data_dict):
    agent_card: AgentCard = request_data_dict.get("request_data") 
    connected_agents: ConnectedAgents = server_data_dict.get('connected_agents')
    res = await connected_agents.remove(agent_card)
    return {"response_status": res}

# Agent의 관리 종목(code) 실시간 시세에 대해 subscribe / unsubscribe
async def handle_subscribe_trp_by_agent_id(request_command, request_data_dict, **server_data_dict):
    trenv = server_data_dict.get("trenv")
    agent_id: str = request_data_dict.get("request_data") 
    connected_agents: ConnectedAgents = server_data_dict.get("connected_agents") 
    agent_card = connected_agents.get_agent_card_by_id(agent_id)
    if not agent_card:
        return {"response_status": f"Agent with id {agent_id} not exists."}
    kws = server_data_dict.get("_kws")
    if trenv.env_dv == 'demo':
        kws.subscribe(request=ccnl_krx, data=agent_card.code)
    else: 
        kws.subscribe(request=ccnl_total, data=agent_card.code) # 모의투자 미지원

    return {"response_status": f"{agent_card.code} subscribed by {agent_card.id}"}

async def handle_unsubscribe_trp_by_agent_id(request_command, request_data_dict, **server_data_dict):
    trenv = server_data_dict.get("trenv")
    agent_id: str = request_data_dict.get("request_data") 
    connected_agents: ConnectedAgents = server_data_dict.get("connected_agents") 
    agent_card = connected_agents.get_agent_card_by_id(agent_id)
    if not agent_card:
        return {"response_status": f"Agent with id {agent_id} not exists."}
    kws = server_data_dict.get("_kws")
    if trenv.env_dv == 'demo':
        kws.unsubscribe(request=ccnl_krx, data=agent_card.code)
    else: 
        kws.unsubscribe(request=ccnl_total, data=agent_card.code) # 모의투자 미지원

    return {"response_status": f"{agent_card.code} unsubscribed by {agent_card.id}"}

# Command registry - UNIQUE PLACE TO REGISTER
COMMAND_HANDLERS = {
    "get_trenv": handle_get_trenv, 
    "get_orderlist": handle_get_orderlist, 
    "submit_orders": handle_submit_order, 
    "CANCEL_orders": handle_cancel_orders, # note the cap letters
    "register_agent_card": handle_register_agent_card, 
    "remove_agent_card": handle_remove_agent_card,
    "subscribe_trp_by_agent_id": handle_subscribe_trp_by_agent_id, 
    "unsubscribe_trp_by_agent_id": handle_unsubscribe_trp_by_agent_id, 
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
        return False, None, "Command dict must contain exactly 'request_command' and 'request_data_dict' keys"
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
        if valid:
            request_id: str = client_request.get("request_id")
            request_command: str = client_request.get("request_command")
            request_data_dict: dict = client_request.get("request_data_dict")
            optlog.info(f"Request received - {request_command}")
            optlog.info(f"{request_data_dict}")
            handler = COMMAND_HANDLERS.get(request_command)
            response = await handler(request_command, request_data_dict, **server_data_dict)
            response['request_id'] = request_id
        else: 
            optlog.warning(f"Invalid request received - {err_msg}")
            response = {"response_status": "Invalid request: " + err_msg}

        # Send response back
        resp_bytes = pickle.dumps(response)
        writer.write(len(resp_bytes).to_bytes(4, "big"))
        writer.write(resp_bytes)
        await writer.drain()

async def send_to_client(writer: asyncio.StreamWriter, message: object):
    await broadcast(set(writer), message)

async def broadcast(target_clients: set[asyncio.StreamWriter], message: object):
    data = pickle.dumps(message)
    msg_bytes = len(data).to_bytes(4, 'big') + data

    for writer in target_clients:
        try:
            writer.write(msg_bytes)
            await writer.drain()  # await ensures exceptions are caught here
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            peer = writer.get_extra_info('peername')
            optlog.error(f"Client {peer} disconnected - broadcast failed.")
            ######## WRITER AND PEER AND AGENT ID SHOULD MATCH ##############
        except Exception as e:
            optlog.error(f"Unexpected broadcast error: {e}")