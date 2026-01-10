import pickle
import asyncio

from ..base.settings import HOST
from ..comm.comm_interface import ClientRequest, ServerResponse, OM_Dispatch, Dispatch_ACK

class PersistentClient:
    def __init__(self, host=HOST, port=None, on_dispatch=None):
        self.host = host
        self.port = port
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None

        # TGs for short-lived tasks (dispatch + requests)
        self._tg: asyncio.TaskGroup | None = None
        self.connected: asyncio.Event = asyncio.Event()

        self.pending_requests: dict[str, asyncio.Future] = {}
        self.on_dispatch = on_dispatch

        self.agent_id = None
        self.logger = None

    async def connect(self):
        """Connect and start the listener within the caller's TG."""
        if self.is_connected:
            return
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        self.logger.info(f"[Client] connected to {self.host}:{self.port}", extra={"owner": self.agent_id})

        # listener + dispatch + requests live inside this TG
        async with asyncio.TaskGroup() as tg:
            self._tg = tg
            self.connected.set()
            await self.listen_server()  # never returns until cancelled

        self._tg = None
        self.connected.clear()

    async def listen_server(self):
        """Main listener for server messages."""
        try:
            while True:
                length_bytes = await self.reader.readexactly(4)
                length = int.from_bytes(length_bytes, "big")
                data = await self.reader.readexactly(length)
                msg = pickle.loads(data)

                # handle server_responses to client_requests
                if isinstance(msg, ServerResponse):
                    fut = self.pending_requests.pop(msg.request_id, None)
                    if fut:
                        fut.set_result(msg)
                    continue

                # handle order_manager-to-agent dispatch messages
                elif isinstance(msg, OM_Dispatch):
                    ack_bytes = pickle.dumps(Dispatch_ACK(id=msg.id, agent_id=self.agent_id))
                    self.writer.write(len(ack_bytes).to_bytes(4, "big") + ack_bytes)
                    await self.writer.drain()
                    msg = msg.data 

                # dispatch via TG
                if self._tg is not None:
                    self._tg.create_task(self.on_dispatch(msg))

        except asyncio.IncompleteReadError:
            self.logger.error("[Client] server closed connection", extra={"owner": self.agent_id})
        except Exception as e:
            self.logger.error(f"[Client] unexpected error in listen_server: {e}", extra={"owner": self.agent_id}, exc_info=True)

    async def send_client_request(self, client_request: ClientRequest, timeout: float = None) -> ServerResponse:
        """Send a request; short-lived task under the same TG."""
        if not self.is_connected or not self.connected.is_set():
            raise RuntimeError("Client not connected: no active request TaskGroup")

        async def _send_and_wait():
            fut = asyncio.get_running_loop().create_future()
            self.pending_requests[client_request.request_id] = fut

            # Send request
            try:
                req_bytes = pickle.dumps(client_request)
                msg = len(req_bytes).to_bytes(4, "big") + req_bytes
                self.writer.write(msg)
                await self.writer.drain()

                # Wait for response
                return await asyncio.wait_for(fut, timeout) if timeout else await fut
            finally:
                self.pending_requests.pop(client_request.request_id, None)

        return await self._tg.create_task(_send_and_wait())

    async def close_writer(self):
        """Close connection; TG tasks are cancelled automatically if parent TG is cancelled."""
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
        self.logger.info("[Client] server connection closed", extra={"owner": self.agent_id})

    @property
    def is_connected(self) -> bool:
        """Check if client is connected and listener is active."""
        return (
            self.writer is not None
            and not self.writer.is_closing()
            and self._tg is not None
        )
