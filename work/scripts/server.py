from core.common.optlog import set_logger
set_logger()

import asyncio
import datetime
from core.common.optlog import optlog, log_raise
from core.common.setup import HOST, PORT
from core.model.agent import dispatch
import core.kis.kis_auth as ka
from core.kis.domestic_stock_functions_ws import ccnl_notice
from core.kis.ws_data import get_tr, TransactionNotice, TransactionPrices
from app.comm.comm_handler import handle_client
from app.comm.conn_agents import ConnectedAgents
from app.comm.subs_manager import SubscriptionManager
from app.comm.order_manager import OrderManager

# server.py -----------------------------------------------------------
# KIS와의 Communication
# - REST: 1 time request/response
# - WS: tradenotice 등 수신
# Localhost Server
# - local client의 request handle

# ---------------------------------
# auth and set-up
# ---------------------------------
svr = 'vps' # prod, auto, vps
if svr != 'vps':
    cfm_message = input("Running real trading mode, sure? (Enter svr name): ")
    if cfm_message != svr:
        log_raise("Check svr ---")

ka.auth(svr)
ka.auth_ws(svr)
trenv = ka.getTREnv()
ws_ready = asyncio.Event()
connected_agents = ConnectedAgents() 
subs_manager = SubscriptionManager()
order_manager = OrderManager()

# ---------------------------------
# Variables to be used in comm_handlers
# ---------------------------------
server_data_dict ={
    'trenv' : trenv,
    'connected_agents' : connected_agents,
    'subs_manager' : subs_manager, 
    'order_manager' : order_manager,
}

# ---------------------------------
# Websocket and response handling logic
# ---------------------------------
async def async_on_result(ws, tr_id, result, data_info):
    if tr_id is None or tr_id == '':
        log_raise(f"tr_id is None or '': {tr_id} ---")

    if get_tr(trenv, tr_id) == 'TransactionNotice': # Notices to the trade orders
        trn = TransactionNotice.create_object_from_response(result)
        # At this time, an agent who sent the order should already be initially registered in connected_agents.
        # But agent could already dropped out and removed from connected_agents.
        # So need to use order_manager, not the connected_agents directly.
        optlog.info(trn) # agent unknown yet
        await order_manager.process_tr_notice(trn, connected_agents, trenv)
        
    elif get_tr(trenv, tr_id) in ('TransactionPrices_KRX',  'TransactionPrices_Total'): # 실시간 체결가
        trp = TransactionPrices(trprices=result, trenv_env_dv=trenv.env_dv)
        await dispatch(connected_agents.get_target_agents_by_trp(trp), trp)

    # to add more tr_id ...
    else:
        log_raise(f"Unexpected tr_id {tr_id} received ---")

def on_result(ws, tr_id, result, data_info):
    asyncio.create_task(async_on_result(ws, tr_id, result, data_info))

async def websocket_loop():
    kws = ka.KISWebSocket(api_url="/tryitout")
    subs_manager.kws = kws

    # default subscriptions
    kws.subscribe(request=ccnl_notice, data=[trenv.my_htsid])

    # run websocket 
    asyncio.create_task(kws.start_async(on_result=on_result))
    ws_ready.set()

# ---------------------------------
# Local comm handlers, server 
# ---------------------------------
CLEANUP_TIMEOUTS = {
    'unsubscribe': 5,          # just WS unsubscribe
    'agent_removal': 5,        # dict operations
    'writer_close': 2,         # network close
}

async def handler_shell(reader, writer):
    addr = writer.get_extra_info("peername") # peername: network term / unique in a session
    optlog.info(f"Client connected {addr}")
    try:
        await handle_client(reader, writer, **server_data_dict)
    except Exception as e:
        optlog.error(f"Handler crashed: {e}", name=addr[1])
    finally:
        await client_disconnect_clean_up(addr, writer)


async def client_disconnect_clean_up(addr, writer):
    port = addr[1]
    agent = connected_agents.get_agent_card_by_port(port)

    if agent:
        optlog.info(f"Starting cleanup for {agent.id}", name=agent.id)
        await _safe_run("Unsubscription", subs_manager.remove_agent(agent), "unsubscribe", agent.id)
        await _safe_run("Agent removal", connected_agents.remove(agent), "agent_removal", agent.id)
        await _safe_close_writer(writer, agent.id)
    else:     
        optlog.warning(f"No agent found (not registered) for port {port} during cleanup")
        await _safe_close_writer(writer)

async def _safe_run(desc, coro, timeout_key, agent_id=None):
    """Run a coroutine safely with timeout and structured logging."""
    try:
        async with asyncio.timeout(CLEANUP_TIMEOUTS[timeout_key]):
            msg = await coro
            optlog.info(f"{desc}: {msg}", name=agent_id)
    except asyncio.TimeoutError:
        optlog.error(f"{desc} timeout", name=agent_id)
    except Exception as e:
        optlog.error(f"{desc} failed: {e}", name=agent_id, exc_info=True)


async def _safe_close_writer(writer, agent_id=None):
    """Safely close an asyncio StreamWriter with timeout and log suppression."""
    try:
        writer.close()
        await asyncio.wait_for(writer.wait_closed(), timeout=CLEANUP_TIMEOUTS["writer_close"])
    except asyncio.TimeoutError:
        if agent_id:
            optlog.warning("Writer close timeout", name=agent_id)
    except Exception:
        pass
    finally:
        if not writer.is_closing():
            writer.close()

async def start_server():
    await ws_ready.wait()
    server = await asyncio.start_server(handler_shell, HOST, PORT)  
    optlog.info(f"Server listening on {HOST}:{PORT}")
    async with server:  # ensures graceful shutdown
        await server.serve_forever()

async def broadcast(shutdown_event: asyncio.Event):
    await ws_ready.wait()
    INTERVAL = 15
    while not shutdown_event.is_set():
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=INTERVAL)
            break
        except asyncio.TimeoutError:
            message = datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S")
            message += ' ping from the server --- '
            optlog.info(message)
            await dispatch(connected_agents.get_all_agents(), message)
            _status_check(True)

def _status_check(show=False, include_ka=True):
    if show:
        optlog.debug('------------------------------------------------------------')
        optlog.debug(connected_agents)
        optlog.debug(subs_manager)
        optlog.debug(order_manager)
        if include_ka:
            optlog.debug('ka.open_map:')
            for k, d in ka.open_map.items(): 
                optlog.debug(f"{k}: {d['items']}")
            optlog.debug('ka.data_map:')
            optlog.debug(ka.data_map.keys())
        optlog.debug('------------------------------------------------------------')

async def server(shutdown_event: asyncio.Event):
    async with asyncio.TaskGroup() as tg: 
        tg.create_task(websocket_loop())
        tg.create_task(start_server())
        tg.create_task(broadcast(shutdown_event))

        # later expand this to save other statics, clean-up, sanity checks, etc
        tg.create_task(order_manager.persist_to_disk())
        tg.create_task(order_manager.check_pending_trns_timeout())

if __name__ == "__main__":
    sep = "\n======================================================================================"
    optlog.info("Server initiated..."+sep)
    shutdown_event = asyncio.Event()
    try:
        asyncio.run(server(shutdown_event))
    except KeyboardInterrupt:
        optlog.info("Server stopped by user (Ctrl+C)"+sep)
        shutdown_event.set()


