import asyncio
import websockets

from ..base.settings import HOST

class DashBoard:
    def __init__(self, logger=None, owner_name=None, port=None):
        self.logger = logger
        self.owner_name: str = owner_name # agent (id), server or other object who owns this dashboard
        self.host: int = HOST
        self.port: int = port # dashboard_port: 8010, 8011, ... etc

        self._dashboard_clients = set()
        self._server = None
        self._server_task = None
        self._broadcaster_task = None
        self._broadcast_queue = asyncio.Queue()

    # ---------------------------------------------------------
    # Public API
    # ---------------------------------------------------------
    def enqueue(self, msg):
        text = str(msg)
        self._broadcast_queue.put_nowait(text)

    async def start(self):
        self._server_task = asyncio.create_task(self._start_server())
        self._broadcaster_task = asyncio.create_task(self._broadcaster_loop())
    
    async def stop(self):
        # --- DASHBOARD CLEANUP ---
        if self._broadcaster_task:
            self._broadcaster_task.cancel()
            try:
                await self._broadcaster_task
            except asyncio.CancelledError:
                pass

        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass

        # close all active websocket connections
        for ws in list(self._dashboard_clients):
            try:
                await ws.close()
            except:
                pass

        self._dashboard_clients.clear()

        # close server if it exists
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
    # ---------------------------------------------------------
    # Internal
    # ---------------------------------------------------------
    async def _start_server(self):
        """start ws server"""
        self._server = await websockets.serve(
            self._handler,
            self.host,
            self.port
        )

        self.logger.info(f"[DashBoard] websocket broadcasting running on ws://{self.host}:{self.port}", extra={'owner': self.owner_name})

        try:
            await asyncio.Future()  # run forever
        except asyncio.CancelledError:
            # task cancelled -> clean exit
            pass

    async def _handler(self, ws):
        """handle browser connections"""
        self._dashboard_clients.add(ws)
        try:
            async for _ in ws:
                pass  # just keep connection open
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass
        finally:
            self._dashboard_clients.discard(ws)

    async def _broadcaster_loop(self):
        """continuously broadcast text from queue to all connected clients."""
        while True:
            try:
                text = await self._broadcast_queue.get()  # wait for next PM update
                for ws in list(self._dashboard_clients):
                    try:
                        await ws.send(text)
                    except:
                        self._dashboard_clients.discard(ws)
            except asyncio.CancelledError:
                # no need to reraise 
                break

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
    }
    """
    def __init__(self, logger, owner_name, port):
        super().__init__(logger, owner_name, port)
        self.endpoints = {} 
        self.register_dp(self.port, self.owner_name)
        self.broadcast_endpoints()

    def register_dp(self, port, id): # id: "manager", "server" or agent.id
        tid = self.endpoints.get(port)
        if tid and tid != id: # port already in use
            return False
        self.endpoints[port] = id
        self.broadcast_endpoints()
        return True

    def unregister_dp(self, port):
        del self.endpoints[port]
        self.broadcast_endpoints()

    def broadcast_endpoints(self):
        msg = "\n".join(f"{k}: {v}" for k, v in self.endpoints.items())
        self.enqueue(msg)

    async def _handler(self, ws):
        """handle browser connections"""
        self._dashboard_clients.add(ws)
        self.broadcast_endpoints()
        try:
            async for _ in ws:
                pass  # just keep connection open
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass
        finally:
            self._dashboard_clients.discard(ws)

