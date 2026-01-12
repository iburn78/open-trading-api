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
        try: 
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        except ConnectionRefusedError as e:
            self.logger.error(f"[Client] connection failed: {e}", extra={"owner": self.agent_id}, exc_info=True)
            return
        self.logger.info(f"[Client] connected to {self.host}:{self.port}", extra={"owner": self.agent_id})

        try:
            # listener + dispatch + requests live inside this TG
            async with asyncio.TaskGroup() as tg:
                self._tg = tg
                self.connected.set()
                await self.listen_server()  # never returns until cancelled
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError) as e:
            self.logger.warning(f"[Client] connection error {e}", extra={"owner": self.agent_id})

            
        finally:
            self._tg = None
            self.connected.clear()

            # cancelling futures is necessary because pending / unfulfilled request
            # state must be handled at a higher (protocol/application) layer.
            # the client object is transport-only and must not own request truth.
            for fut in self.pending_requests.values():
                if not fut.done():
                    fut.cancel()
            self.pending_requests.clear()

            if self.writer:
                self.writer.close()
                try:
                    await self.writer.wait_closed()
                except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as e:
                    pass # suppress windows errors
            self.logger.info("[Client] server connection closed", extra={"owner": self.agent_id})

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
                tg = self._tg
                if tg is not None:
                    tg.create_task(self.on_dispatch(msg))

        except asyncio.IncompleteReadError:
            self.logger.warning("[Client] server closed connection", extra={"owner": self.agent_id}, exc_info=True)

        except Exception as e:
            self.logger.error(f"[Client] unexpected error in listen_server: {e}", extra={"owner": self.agent_id}, exc_info=True)

    # send_client_request will return server_response or None on failure
    async def send_client_request(self, client_request: ClientRequest, timeout: float = None) -> ServerResponse | None:
        """Send a request; short-lived task under the same TG."""
        tg = self._tg # copying object reference as connect() might assign self._tg == None
        if not self.is_connected or tg is None:
            self.logger.error(f"[Client] not connected", extra={"owner": self.agent_id})
            return None

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
                self.pending_requests.pop(client_request.request_id, None) # in case of timeout, cancel, failure etc

        return await tg.create_task(_send_and_wait())

    @property
    def is_connected(self) -> bool:
        return self.connected.is_set()