from dataclasses import dataclass, field
from enum import Enum, auto
import uuid

from .optlog import log_raise
from ..kis.kis_auth import KISEnv

class RequestCommand(Enum):
    SUBMIT_ORDERS = auto()
    CANCEL_ALL_ORDERS_BY_AGENT = auto() # sepcial kind of submit_orders in fact - no need to provide RC orders instead (logic implemented)
    REGISTER_AGENT_CARD = auto()
    SYNC_ORDER_HISTORY = auto()
    SYNC_COMPLETE_NOTICE = auto()
    SUBSCRIBE_TRP_BY_AGENT_CARD = auto()
    GET_PSBL_ORDER = auto()

@dataclass
class ClientRequest:
    command: RequestCommand
    data_dict: dict = field(default_factory=dict)
    _request_id: str | None = None

    def __post_init__(self):
        self._request_id = str(uuid.uuid4())
        self.data_dict.setdefault('request_data', None) # must have 'request_data' key

    def __str__(self):
        return self.command.name

    def set_request_data(self, request_data: object):
        self.data_dict['request_data'] = request_data

        # minimum validation logic for request_data
        if self.command == RequestCommand.SUBMIT_ORDERS:
            if not isinstance(request_data, list): 
                log_raise('invalid request_data type')
        
        elif self.command == RequestCommand.SYNC_ORDER_HISTORY or self.command == RequestCommand.SYNC_COMPLETE_NOTICE: 
            if not isinstance(request_data, str): 
                log_raise('invalid request_data type')

        elif self.command == RequestCommand.GET_PSBL_ORDER: 
            if not isinstance(request_data, tuple): 
                log_raise('invalid request_data type')

    def get_request_data(self):
        return self.data_dict['request_data']

    def set_additional_data(self, additional_data: dict):
        self.data_dict.update(additional_data)  # append dict
    
    def get_id(self): 
        return self._request_id

@dataclass
class ServerResponse:
    success: bool
    status: str
    data_dict: object = field(default_factory=dict)
    _request_id: str | None = None

    def __str__(self):
        if self.success:
            return '[Success] '+ self.status
        else:
            return '[Fail] ' + self.status
    
    def set_id(self, client_request: ClientRequest):
        self._request_id = client_request.get_id()

    def get_id(self): 
        return self._request_id

@dataclass
class Sync:
    agent_id: str | None = None
    incompleted_orders: dict | None = None
    completed_orders: dict | None = None
    pending_trns: dict | None = None
    trenv: KISEnv | None = None