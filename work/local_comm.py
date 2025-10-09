import pickle
from kis_tools import *
from agent import AgentManager

HOST = "127.0.0.1"   # Localhost
# later can variate port 1) for order making, 2) getting readtime data (esp, prices)
PORT = 5001   

# ---------------------------------------------------------------------------------
# Parameters:
#     - request_data_dict.get("request_data"): from client
#     - server_data_dict: from server 
# Generating responses:
#     - command_queue put(): tuple (request_command: str, request_data: obj)
#     - return: dict {"response_status": str, "response_data": obj}
# ---------------------------------------------------------------------------------

# 현재 server에서 관리하는 the_account를 return
async def handle_get_account(request_command, request_data_dict, **server_data_dict):
    the_account = server_data_dict.get("the_account")
    return {"response_status": "account info retrieved", "response_data": the_account}

# main_order_list return
async def handle_get_orderlist(request_command, request_data_dict, **server_data_dict):
    main_orderlist = server_data_dict.get("main_orderlist", None)
    return {"response_status": "orders retrieved", "response_data": main_orderlist}

# [order, ...]를 받아서 submit
async def handle_submit_order(request_command, request_data_dict, **server_data_dict):
    orderlist = request_data_dict.get("request_data") # list [order, order, ... ]
    command_queue = server_data_dict.get("command_queue")
    command = (request_command, orderlist)
    await command_queue.put(command)
    return {"response_status": "order queued"}

# 현재 server의 모든 order에 대해 cancel을 submit
async def handle_cancel_orders(request_command, request_data_dict, **server_data_dict):
    command_queue = server_data_dict.get("command_queue")
    command = (request_command, None)
    await command_queue.put(command)
    return {"response_status": "stop loop and cancel all orders requested"}

# code를 받아서 agent를 return
async def handle_get_agent(request_command, request_data_dict, **server_data_dict):
    code = request_data_dict.get("request_data") 
    agent_manager = server_data_dict.get("agent_manager") # type: AgentManager
    target_agent = agent_manager.get_agent(code)
    return {"response_status": "agent retrieved", 'response_data': target_agent}

# Command registry - UNIQUE PLACE TO REGISTER
COMMAND_HANDLERS = {
    "get_account": handle_get_account, 
    "get_orderlist": handle_get_orderlist, 
    "submit_orders": handle_submit_order, 
    "cancel_orders": handle_cancel_orders, 
    "get_agent": handle_get_agent, 
}

# ---------------------------------------------------------------------------------
# client request format should be:
# {"request_command": str, "request_data_dict": {'request_data': ..., } | None}
# ---------------------------------------------------------------------------------
def validate_client_request(client_sent_data: bytes) -> dict[str, any]:
    try:
        obj = pickle.loads(client_sent_data)
    except (pickle.UnpicklingError, EOFError, AttributeError,
        ValueError, ImportError, IndexError) as e:
        return False, f"Invalid pickle data: {e}"
    if not isinstance(obj, dict):
        return False, "Unpickled object must be a dict"
    if set(obj.keys()) != {"request_command", "request_data_dict"}:
        return False, "Command dict must contain exactly 'request_command' and 'request_data_dict' keys"
    if obj["request_command"] not in COMMAND_HANDLERS:
        return False, "request_command is unknown"
    if obj["request_data_dict"] is not None:
        if not isinstance(obj["request_data_dict"], dict):
            return False, "request_data_dict must be None or a dict"
        if 'request_data' not in obj["request_data_dict"]:
            return False, "request_data_dict must contain 'request_data' key"
    return True, obj

# ---------------------------------------------------------------------------------
# server side
# ---------------------------------------------------------------------------------
async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, **server_data_dict):
    addr = writer.get_extra_info("peername") # peername: network term / unique in a session
    print(f"Connected by {addr}")
    try:
        while True:
            # Read length + body
            length_bytes = await reader.read(4)
            if not length_bytes: 
                break
            length = int.from_bytes(length_bytes, "big")
            client_bytes = await reader.read(length)
            valid, client_request = validate_client_request(client_bytes)
            if valid:
                request_command = client_request.get("request_command")
                request_data_dict = client_request.get("request_data_dict")
                optlog.info(f"Server received request_command: {request_command}")
                optlog.info(f"with request_data dict: {request_data_dict}")
                handler = COMMAND_HANDLERS.get(request_command)
                response = await handler(request_command, request_data_dict, **server_data_dict)
            else: 
                optlog.warning(f"Invalid request received: {client_request}")
                response = {"response_status": "Invalid request: " + client_request}

            # Send response back
            resp_bytes = pickle.dumps(response)
            writer.write(len(resp_bytes).to_bytes(4, "big"))
            writer.write(resp_bytes)
            await writer.drain()
    finally:
        writer.close() # marks the stream as closed.
        await writer.wait_closed() # actual close

# ---------------------------------------------------------------------------------
# client side
# ---------------------------------------------------------------------------------
async def send_command(request_command: str, request_data = None, **other_kwargs):
    reader, writer = await asyncio.open_connection(HOST, PORT) # creates a new socket

    # building client request format to comply
    request_data_dict = {
        'request_data': request_data,
        **other_kwargs
    }
    client_request = {"request_command": request_command, "request_data_dict": request_data_dict} 

    req_bytes = pickle.dumps(client_request)
    # Send length + body
    writer.write(len(req_bytes).to_bytes(4, "big"))
    writer.write(req_bytes)
    await writer.drain()

    # Read length first
    length_bytes = await reader.read(4)
    length = int.from_bytes(length_bytes, "big")

    # Read full response
    response_data = b""
    while len(response_data) < length:
        chunk = await reader.read(length - len(response_data))
        if not chunk:
            log_raise("Connection closed prematurely ---")
        response_data += chunk
    try:
        response = pickle.loads(response_data)
        optlog.info("Response received:")
        optlog.info(response)
    except Exception as e:
        log_raise(f"Invalid response received: {e}\n" + f"* response_data: {response_data.decode()} ---")
    finally:
        writer.close()
        await writer.wait_closed()

    return response
    

