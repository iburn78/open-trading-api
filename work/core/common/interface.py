from dataclasses import dataclass, field
from enum import Enum, auto
import uuid

from .optlog import log_raise
from ..kis.kis_auth import KISEnv

class RequestCommand(Enum):
    SUBMIT_ORDERS = auto()
    REGISTER_AGENT_CARD = auto()
    SYNC_ORDER_HISTORY = auto()
    SYNC_COMPLETE_NOTICE = auto()
    SUBSCRIBE_TRP_BY_AGENT_CARD = auto()
    GET_PSBL_ORDER = auto()

@dataclass
class ClientRequest:
    command: RequestCommand
    data_dict: dict = field(default_factory=dict)
    # if fire_forget is set True, ClientRequest does not wait for ServerResponse
    fire_forget: bool = False
    request_id: str | None = None

    def __post_init__(self):
        self.request_id = str(uuid.uuid4())
        self.data_dict.setdefault('request_data', None) # must have 'request_data' key

    def __str__(self):
        return self.command.name

    def set_request_data(self, request_data: object):
        self.data_dict['request_data'] = request_data

        # minimum validation logic for request_data
        if self.command == RequestCommand.SUBMIT_ORDERS:
            if not isinstance(request_data, list): 
                log_raise('invalid request_data type')
        
        elif self.command == RequestCommand.SYNC_ORDER_HISTORY:
            if not isinstance(request_data, tuple): 
                log_raise('invalid request_data type')
        
        elif self.command == RequestCommand.SYNC_COMPLETE_NOTICE: 
            if not isinstance(request_data, str): 
                log_raise('invalid request_data type')

    def get_request_data(self):
        return self.data_dict['request_data']

@dataclass
class ServerResponse:
    success: bool
    status: str
    data_dict: object = field(default_factory=dict)
    fire_forget: bool = False
    request_id: str | None = None

    def __str__(self):
        if self.success:
            return '[Success] '+ self.status 
        else:
            return '[Fail] '+ self.status
    
    def set_attr(self, client_request: ClientRequest):
        self.fire_forget = client_request.fire_forget
        self.request_id = client_request.request_id

@dataclass
class Sync:
    agent_id: str | None = None
    # -----------------------------------------------------
    # for below dicts, keys may be duplicated, in such a case, keys will have trailing "#" marks... so if needed take them out.
    # -----------------------------------------------------
    # prev days - has to be dealt like completed orders; i.e., need to set order.quantity == order.processed
    # more fundamentally, prev_ios shouldn't exist if handled well, but this allows more flexibility
    prev_incompleted_orders: dict | None = None
    # today
    incompleted_orders: dict | None = None
    # all days
    completed_orders: dict | None = None
    # today
    pending_trns: dict | None = None
    trenv: KISEnv | None = None

    def __str__(self):
        res = ''
        for k, v in (self.prev_incompleted_orders or {}).items():
            res += f'p-inc {v}\n'
        for k, v in (self.incompleted_orders or {}).items():
            res += f't-inc {v}\n'
        for k, v in (self.completed_orders or {}).items():
            res += f'comp  {v}\n'
        for k, v in (self.pending_trns or {}).items():
            res += f'ptrns {k}: {v}\n' ###_ how many not just all
        
        if res: res = '\n'+res 
        else: res = "sync data empty"

        return res