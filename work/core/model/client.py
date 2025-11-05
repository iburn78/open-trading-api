import pickle
import asyncio
from typing import Optional, Callable, Awaitable

from ..common.interface import ClientRequest, ServerResponse
from ..common.setup import HOST, PORT
from ..common.optlog import optlog, log_raise

# client remains connected
class PersistentClient:
    def __init__(self, host=HOST, port=PORT, on_dispatch: Optional[Callable[[object], Awaitable[None]]] = None): # rigorous type-hinting, meaning it must be an async function(coroutine)
        self.host = host
        self.port = port
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.listen_task: asyncio.Task | None = None
        self.pending_requests: dict[str, asyncio.Future] = {}
        self.on_dispatch = on_dispatch  # callback for unsolicited server messages
        self._closing = False
        self.agent_id = None

    async def connect(self):
        if self.is_connected:
            optlog.warning(f"Already connected to {self.host}:{self.port}", name=self.agent_id)
            return
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        except ConnectionRefusedError as e:
            optlog.error(f"Connection refused: {self.host}:{self.port} → {e}", name=self.agent_id, exc_info=True)
            return
        except Exception as e:
            optlog.error(f"Unexpected error connecting to {self.host}:{self.port}: {e}", name=self.agent_id, exc_info=True)
            return

        self.listen_task = asyncio.create_task(self.listen_server())
        optlog.info(f"Connected to {self.host}:{self.port}", name=self.agent_id)

    async def listen_server(self): # listen to server command responses, and dispatches
        try:
            while True:
                # read length prefix
                length_bytes = await self.reader.readexactly(4)
                length = int.from_bytes(length_bytes, "big")

                # read message
                data = await self.reader.readexactly(length)
                msg = pickle.loads(data)
                # msg can be 1) ServerResponse, 2) TRN, 3) TRP, 4) Order, 5) etc
                
                # route to the correct pending client_request
                if isinstance(msg, ServerResponse):
                    req_id = msg.get_id()
                    if req_id is None:
                        optlog.error(f"server response with no request_id {msg}", name=self.agent_id)
                    elif req_id in self.pending_requests:
                        fut = self.pending_requests.pop(req_id)
                        fut.set_result(msg) # if fut.done() == True, then this will throw anyway
                        continue
                    else:
                        optlog.error(f"server response for non exist (or not anymore) request_id {req_id}: {msg}", name=self.agent_id)
                        continue

                # handle dispatch message for non ServerResponse objects
                if self.on_dispatch:   
                    # listner should not block listening
                    asyncio.create_task(self.on_dispatch(msg))
                else:
                    optlog.warning(f"Dispatched but no receiver: {msg}", name=self.agent_id)

        except asyncio.CancelledError:
            optlog.info("Listen task cancelled", name=self.agent_id)  # intentional
            raise  # usually propagate cancellation
        except asyncio.IncompleteReadError:
            if self._closing:
                pass
                # optlog.info("Listen task closed", name=self.agent_id)  
            elif not self.listen_task.cancelled(): # if not keyboard-interrupt
                optlog.warning("Server closed connection", name=self.agent_id)  # actual EOF / disconnect
        except Exception as e:
            # this is a local server-client communication
            # has to be perfeclty reliable, so no auto reconnection necessary
            log_raise(f"Error in listening: {e}", name=self.agent_id)

    async def send_client_request(self, client_request: ClientRequest):
        if not self.is_connected:
            msg = f"Client not connected: {client_request}"
            optlog.error(msg, name=self.agent_id)
            return ServerResponse(success=False, status=msg)  

        req_bytes = pickle.dumps(client_request)
        msg = len(req_bytes).to_bytes(4, "big") + req_bytes

        # create a future and store it for response matching
        # future: a tool that makes a coroutine wait
        fut = asyncio.get_running_loop().create_future()
        self.pending_requests[client_request.get_id()] = fut

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
        if self.listen_task:
            self.listen_task.cancel()
            try:
                await self.listen_task
            except asyncio.CancelledError as e:
                pass # expected so no need to log
        optlog.info("Client connection closed", name=self.agent_id)
    
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
