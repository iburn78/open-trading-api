import pickle
import asyncio

from ..base.settings import HOST, SERVER_PORT
from ..comm.comm_interface import ClientRequest, ServerResponse, OM_Dispatch, Dispatch_ACK

class PersistentClient:
    def __init__(self, host=HOST, port=None, on_dispatch = None): 
        self.host = host
        self.port = port
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.listen_task: asyncio.Task | None = None
        self.pending_requests: dict[str, asyncio.Future] = {}
        self.on_dispatch = on_dispatch  # callback for server messages
        self._closing = False
        self.agent_id = None
        self.logger = None

    async def connect(self):
        if self.is_connected:
            self.logger.error(f"[PersistentClient] already connected to {self.host}:{self.port}", extra={"owner":self.agent_id})
            return
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        except ConnectionRefusedError as e:
            self.logger.error(f"[PersistentClient] connection refused {self.host}:{self.port}: {e}", extra={"owner":self.agent_id}, exc_info=True)
            raise
        except Exception as e:
            self.logger.error(f"[PersistentClient] unexpected error {self.host}:{self.port}: {e}", extra={"owner":self.agent_id}, exc_info=True)
            raise

        self.listen_task = asyncio.create_task(self.listen_server())
        self.logger.info(f"[PersistentClient] connected to {self.host}:{self.port}", extra={"owner":self.agent_id})

    async def listen_server(self): # listen to server command responses, and dispatches
        try:
            while True:
                length_bytes = await self.reader.readexactly(4)
                length = int.from_bytes(length_bytes, "big")
                data = await self.reader.readexactly(length)
                msg = pickle.loads(data)

                if isinstance(msg, OM_Dispatch):
                    ack_bytes = pickle.dumps(Dispatch_ACK(id=msg.id, agent_id=self.agent_id))
                    ack = len(ack_bytes).to_bytes(4, "big") + ack_bytes
                    self.writer.write(ack)
                    await self.writer.drain()
                    msg = msg.data # continue to process to on_dispatch

                # route to the correct pending client_request
                elif isinstance(msg, ServerResponse):
                    fut = self.pending_requests.pop(msg.request_id)
                    fut.set_result(msg) 
                    continue

                # listner should not block listening
                asyncio.create_task(self.on_dispatch(msg))

        except asyncio.CancelledError as e: 
            self.logger.info(f"[PersistentClient] listen task cancelled {e}", extra={"owner":self.agent_id})  # intentional
            raise  
        except asyncio.IncompleteReadError as e:
            if self._closing:
                pass
            elif not self.listen_task.cancelled(): 
                self.logger.error(f"[PersistentClient] server closed connection {e}", extra={"owner":self.agent_id}, exc_info=True)  # actual EOF / disconnect
        except Exception as e:
            # this is a local server-client communication: to be reliable
            self.logger.error(f"[PersistentClient] Error in listening: {e}", extra={"owner":self.agent_id}, exc_info=True)

    async def send_client_request(self, client_request: ClientRequest):
        ###_ should not happen ... not unreliable 
        if not self.is_connected:
            msg = f"[PersistentClient] client not connected: {client_request}"
            self.logger.error(msg, extra={"owner":self.agent_id})
            return ServerResponse(success=False, status=msg)  

        req_bytes = pickle.dumps(client_request)
        msg = len(req_bytes).to_bytes(4, "big") + req_bytes

        # create a future and store it for response matching
        # future: a tool that makes a coroutine wait
        # make sure when response should arrive after future creation
        fut = asyncio.get_running_loop().create_future()
        self.pending_requests[client_request.request_id] = fut

        # send request
        self.writer.write(msg)
        await self.writer.drain()

        # wait for the specific response
        response: ServerResponse = await fut  
        return response

    # no need to check if already closed
    async def close(self):
        self._closing = True
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
        if self.listen_task is not None and not self.listen_task.done():
            self.listen_task.cancel()
            await self.listen_task
        self.logger.info("[PersistentClient] server connection closed", extra={"owner":self.agent_id})
    
    @property
    def is_connected(self) -> bool:
        """
        Returns True if the client is connected and listener is active.
        """
        return (
            self.writer is not None
            and not self.writer.is_closing()
            and self.listen_task is not None
            and not self.listen_task.done()
        )
