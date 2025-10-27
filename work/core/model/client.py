import pickle
import asyncio
import uuid
from typing import Callable

from ..common.setup import HOST, PORT
from ..common.optlog import optlog, log_raise

# ---------------------------------------------------------------------------------
# client side
# ---------------------------------------------------------------------------------
# client request format should be:
# {"request_id": str, "request_command": str, "request_data_dict": {'request_data': obj, ... } | None}
# ---------------------------------------------------------------------------------

# client remains connected
class PersistentClient:
    def __init__(self, host=HOST, port=PORT, on_dispatch: Callable=None):
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
            optlog.error(f"Connection refused: {self.host}:{self.port} → {e}", name=self.agent_id)
            return
        except Exception as e:
            optlog.error(f"Unexpected error connecting to {self.host}:{self.port}: {e}", name=self.agent_id)
            return

        self.listen_task = asyncio.create_task(self.listen_server())
        optlog.info(f"Connected to {self.host}:{self.port}", name=self.agent_id)

    async def listen_server(self):
        try:
            while True:
                # read length prefix
                length_bytes = await self.reader.readexactly(4)
                length = int.from_bytes(length_bytes, "big")

                # read message
                data = await self.reader.readexactly(length)
                msg = pickle.loads(data)

                # route to the correct pending request
                if isinstance(msg, dict):
                    req_id = msg.get("request_id")
                    if req_id and req_id in self.pending_requests:
                        fut = self.pending_requests.pop(req_id)
                        if not fut.done():
                            fut.set_result(msg)
                            continue
                        else:
                            optlog.warning(f"Received response for already completed request_id {req_id}, received: {msg}", name=self.agent_id)
                            continue
                # handle dispatch message
                if self.on_dispatch:
                    await self.on_dispatch(msg)
                else:
                    optlog.warning(f"Dispatched but no receiver - {msg}", name=self.agent_id)

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
            log_raise(f"Error in listening: {e}", name=self.agent_id)
            # optlog.error(f"Error in listening: {e}", name=self.agent_id)

    async def send_command(self, request_command: str, request_data=None, **other_kwargs):
        if not self.is_connected:
            optlog.error(f"Client is not connected for command {request_command}", name=self.agent_id)
            return {}  

        # create unique request ID
        request_id = str(uuid.uuid4())
        payload = {
            "request_id": request_id,
            "request_command": request_command,
            "request_data_dict": {"request_data": request_data, **other_kwargs},
        }

        req_bytes = pickle.dumps(payload)
        msg = len(req_bytes).to_bytes(4, "big") + req_bytes

        # create a future and store it for response matching
        # future: a tool that makes a coroutine wait
        fut = asyncio.get_running_loop().create_future()
        self.pending_requests[request_id] = fut

        # send request
        self.writer.write(msg)
        await self.writer.drain()

        # wait for the specific response
        response = await fut
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
