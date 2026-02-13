import asyncio
import websockets
import json

from ..base.settings import HOST

class DashBoard:
    def __init__(self, logger, owner_name, port):
        self.logger = logger
        self.owner_name = owner_name
        self.host = HOST
        self.port = port

        self._clients = set()
        self._queue = asyncio.Queue()
        self._server = None
        
    def enqueue(self, msg):
        self._queue.put_nowait(str(msg))
    
    async def run(self):
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._start_server())
            tg.create_task(self._broadcaster_loop())

    async def _start_server(self):
        try: 
            self._server = await websockets.serve(self._handler, self.host, self.port)
        except OSError as e:
            self.logger.error(f"[DashBoard] ws error {e}", extra={"owner": self.owner_name})
            return

        self.logger.info(f"[DashBoard] websocket broadcasting running on ws://{self.host}:{self.port}", extra={"owner": self.owner_name})

        try:
            await asyncio.Future()
        finally:
            if self._server is not None:
                self._server.close()
                await self._server.wait_closed()

    async def _handler(self, ws):
        self._clients.add(ws)
        try:
            async for _ in ws:
                pass
        finally:
            self._clients.discard(ws)

    async def _broadcaster_loop(self):
        while True:
            msg = await self._queue.get()
            for ws in list(self._clients):
                try:
                    await ws.send(msg)
                except Exception:
                    self._clients.discard(ws)

    def send_bars(self, bars):
        payload = {
            "type": "bars",
            "bars": [
                {
                    "t": b.start.isoformat(),
                    "o": b.open,
                    "h": b.high,
                    "l": b.low,
                    "c": b.close,
                    "v": b.volume,
                    "price_event": b.price_event,
                    "volume_event": b.volume_event,
                    "barlist_event": b.barlist_event,
                }
                for b in bars
            ]
        }
        self.enqueue(json.dumps(payload))


class DashboardManager(DashBoard):
    """
    - differ by service type
    endpoints = {
        9000: "manager", # dashboard_manager_port
        9001: "server", # dashboard_server_port
        8001: "agent_id 1"
        8002: "agent_id 2"
        8003: "agent_id 3"
        ...
    endpoints let the browser client know what are the currently serving dashboard ports
    the brower client only need to connect to the manager
    }
    """
    def __init__(self, logger, owner_name, port):
        super().__init__(logger, owner_name, port)
        self.endpoints = {} 
        self.endpoints[port] = self.owner_name

    # done when agent is registerd to the conn_agents
    def register_dp(self, id, port): # id: "manager", "server" or agent.id
        tid = self.endpoints.get(port)
        if tid and tid != id: # port already in use
            return False
        self.endpoints[port] = id
        # keep dict always sorted by port
        self.endpoints = dict(sorted(self.endpoints.items()))
        self.broadcast_endpoints()
        return True

    def unregister_dp(self, port):
        del self.endpoints[port]

    def broadcast_endpoints(self):
        self.enqueue(json.dumps(self.endpoints))

    async def _handler(self, ws):
        self.broadcast_endpoints()
        await super()._handler(ws)