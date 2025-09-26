import pickle
from kis_tools import *

HOST = "127.0.0.1"   # Localhost
PORT = 5001

class CancelOrder: pass
CANCEL = CancelOrder()


# Return Data Format:
# {"valid": bool, "status": str, "data": obj}
async def identify_agent(params, command_queue, **kwargs):
    ###
    return {"valid": True, "status": "---"}

async def handle_get_orders(params, command_queue, **kwargs):
    trenv = kwargs.get("trenv", None)
    main_orderlist = kwargs.get("main_orderlist", None)
    return {"valid": True, "status": "orders retrieved", "data": main_orderlist}

async def handle_cancel(params, command_queue, **kwargs):
    await command_queue.put(CANCEL)
    return {"valid": True, "status": "stop loop and cancel all orders requested"}

async def handle_submit_order(params, command_queue, **kwargs):
    data = params.get("data") # orders
    await command_queue.put(data)
    return {"valid": True, "status": "order queued"}

async def handle_get_account(params, command_queue, **kwargs):
    trenv = kwargs.get("trenv", None)
    return {"valid": True, "status": "account info retrieved", "data": Account().acc_load(trenv)}

# Command registry
COMMAND_HANDLERS: dict[str, callable] = {
    "agent_identify": identify_agent,
    "get_orders": handle_get_orders,
    "cancel_orders": handle_cancel,
    "submit_orders": handle_submit_order,
    "get_account": handle_get_account,
}

ALLOWED_DATA_TYPES = (Order, )  

# client request format should be only dict 
# --------------------------------------------------
# {"command": str, "params": param_dict | None}
# --------------------------------------------------
# param_dict should be either None or only
# {'data': [obj, ... ], ... }
# --------------------------------------------------
# allowed obj in 'data' is defined in ALLOWED_DATA_TYPES
# --------------------------------------------------
def load_and_validate_command(data: bytes) -> dict[str, any]:
    try:
        obj = pickle.loads(data)
    except (pickle.UnpicklingError, EOFError, AttributeError,
        ValueError, ImportError, IndexError) as e:
        return {"valid": False, "error": f"Invalid pickle data: {e}"}

    if not isinstance(obj, dict):
        return {"valid": False, "error": "Unpickled object must be a dict"}

    if set(obj.keys()) != {"command", "params"}:
        return {"valid": False, "error": "Command dict must contain exactly 'command' and 'params' keys"}

    if not isinstance(obj["command"], str):
        return {"valid": False, "error": "'command' must be a string"}
    elif obj["command"] not in COMMAND_HANDLERS:
        return {"valid": False, "error": "'command' is unknown"}

    if obj["params"] is not None:
        if not isinstance(obj["params"], dict):
            return {"valid": False, "error": "'params' must be None or a dict"}

        param_data = obj["params"].get('data')
        if not param_data:
            return {"valid": False, "error": "'params' dict must contain 'data' key"}
    
        if not isinstance(param_data, list):
            return {"valid": False, "error": "'params' dict 'data' obj must be a list"}

        if not all(isinstance(item, ALLOWED_DATA_TYPES) for item in param_data):
            return {"valid": False, "error": "'data' list must contain only allowed objects in ALLOWED_DATA_TYPES"}

    # above failed-to-pass return is send back to client
    # the following passed return is processed in server
    return {"valid": True, "command": obj["command"], "params": obj["params"]}

# server side
async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, **kwargs):
    addr = writer.get_extra_info("peername") # peername: network term / unique in a session
    print(f"Connected by {addr}")
    try:
        while True:
            # Read length + data
            length_bytes = await reader.read(4)
            if not length_bytes: 
                break
            length = int.from_bytes(length_bytes, "big")

            data = await reader.read(length)
            validity = load_and_validate_command(data)
            if validity['valid']:
                cmd = validity.get("command")
                params = validity.get("params")
                optlog.info(f"Server received command: {cmd}")
                optlog.info(f"with params: {params}")
                handler = COMMAND_HANDLERS.get(cmd)
                response = await handler(params, command_queue=kwargs.get("command_queue"), main_orderlist=kwargs.get("main_orderlist"), trenv=kwargs.get("trenv"))
            else: 
                optlog.info(f"Invalid request: {validity}")
                response = validity 

            # Send response back
            resp_bytes = pickle.dumps(response)
            writer.write(len(resp_bytes).to_bytes(4, "big"))
            writer.write(resp_bytes)
            await writer.drain()
    finally:
        writer.close() # marks the stream as closed.
        await writer.wait_closed() # actual close

# client side
async def send_command(cmd: str, params: dict | None = None):
    reader, writer = await asyncio.open_connection(HOST, PORT) # creates a new socket

    request = {"command": cmd, "params": params} 
    req_bytes = pickle.dumps(request)
    # checker
    validity =  load_and_validate_command(req_bytes)
    if not validity["valid"]:
        optlog.info('Check request format. Command not sent ---')
        return None

    # Send length + data
    writer.write(len(req_bytes).to_bytes(4, "big"))
    writer.write(req_bytes)
    await writer.drain()

    # Read length first
    length_bytes = await reader.read(4)
    length = int.from_bytes(length_bytes, "big")

    # Read full response
    data = b""
    while len(data) < length:
        chunk = await reader.read(length - len(data))
        if not chunk:
            log_raise("Connection closed prematurely")
        data += chunk

    try:
        resp = pickle.loads(data)
        optlog.info("Received:")
        optlog.info(resp)
    except Exception as e:
        log_raise("INVALID RESPONSE: {e}\n" + data.decode())
    finally:
        writer.close()
        await writer.wait_closed()

    return resp
    

