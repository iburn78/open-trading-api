import asyncio
import websockets
import json

from ..common.optlog import optlog
from ..common.setup import HOST, dashboard_manager_port, dashboard_server_port

class DashBoard:
    def __init__(self, owner=None, port=None):
        self.owner: str = owner # agent (id), server or other object who owns this dashboard
        self.port: int =port # dashboard_port: 8010, 8011, ... etc

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

        # This handles closing server + connections cleanly
        await self._stop_server()

    # ---------------------------------------------------------
    # Internal
    # ---------------------------------------------------------

    async def _start_server(self):
        """Start WS server"""
        self._server = await websockets.serve(
            self._handler,
            HOST,
            self.port
        )

        optlog.info(f"[DashBoard] websocket broadcasting running on ws://{HOST}:{self.port}", name=self.owner)

        try:
            await asyncio.Future()  # run forever
        except asyncio.CancelledError:
            # task cancelled => clean exit
            pass

    async def _stop_server(self):
        # Close all active websocket connections
        for ws in list(self._dashboard_clients):
            try:
                await ws.close()
            except:
                pass

        self._dashboard_clients.clear()

        # Close server if it exists
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handler(self, ws):
        """Handle browser connections"""
        self._dashboard_clients.add(ws)
        try:
            async for _ in ws:
                pass  # just keep connection open
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass
        finally:
            self._dashboard_clients.discard(ws)

    async def _broadcaster_loop(self):
        """Continuously broadcast text from queue to all connected clients."""
        while True:
            try:
                text = await self._broadcast_queue.get()  # wait for next PM update
                for ws in list(self._dashboard_clients):
                    try:
                        await ws.send(text)
                    except:
                        self._dashboard_clients.discard(ws)
            except asyncio.CancelledError:
                break


class DashboardManager(DashBoard):
    """
    endpoints = {
        9000: "dashboard_manager", # dashboard_manager_port
        9001: "server", # dashboard_server_port
        8001: "agent 1"
        8002: "agent 2"
        8003: "agent 3"
        ...
    }
    # Owned by ConnectedAgent class
    # - will generate optlog.error if agent.dp is duplicated
    """
    def __init__(self):
        super().__init__()
        self.owner = "manager"
        self.port = dashboard_manager_port 
        self.endpoints = {}     # {id: port}
        self.endpoints[dashboard_manager_port] = "manager"
        self.endpoints[dashboard_server_port] = "server"
        self.broadcast_endpoints()

    def register_agent_dp(self, agent): # AgentCard
        ta = self.endpoints.get(agent.dp)
        if ta and ta != agent.id:
            optlog.error(f"[DashBoard Manager] new agent {agent.id}'s dashboard port {agent.dp} is already in use for agent {ta}")
        else: 
            self.endpoints[agent.dp] = agent.id
        self.broadcast_endpoints()

    def unregister_agent_dp(self, agent): # AgentCard
        self.endpoints.pop(agent.dp, None)
        self.broadcast_endpoints()

    def broadcast_endpoints(self):
        msg = json.dumps(self.endpoints)
        self.enqueue(msg)

    async def _handler(self, ws):
        """Handle browser connections"""
        self._dashboard_clients.add(ws)
        self.broadcast_endpoints()
        try:
            async for _ in ws:
                pass  # just keep connection open
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass
        finally:
            self._dashboard_clients.discard(ws)

