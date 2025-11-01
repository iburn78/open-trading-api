from dataclasses import dataclass, field
from enum import Enum, auto
import uuid

from .agent import AgentCard
from ..common.optlog import log_raise

class RequestCommand(Enum):
    SUBMIT_ORDERS = auto()
    CANCEL_ORDERS = auto() # sepcial kind of submit_orders in fact - no need to provide RC orders instead (logic implemented)
    REGISTER_AGENT_CARD = auto()
    SUBSCRIBE_TRP_BY_AGENT_CARD = auto()
    GET_PSBL_ORDER = auto()

@dataclass
class ClientRequest:
    command: RequestCommand
    data: dict = field(default_factory=dict)
    _request_id: str = ''

    def __post_init__(self):
        self._request_id = str(uuid.uuid4())
        self.data.setdefault('request_data', None) # must have 'request_data' key

    def __str__(self):
        return self.command.name

    def set_request_data(self, request_data: object):
        self.data['request_data'] = request_data

        # validation logic for request_data
        if self.command == RequestCommand.SUBMIT_ORDERS:
            if not isinstance(request_data, list): 
                log_raise('invalid request_data type')
    
        elif self.command == RequestCommand.REGISTER_AGENT_CARD or self.command == RequestCommand.SUBSCRIBE_TRP_BY_AGENT_CARD:
            if not isinstance(request_data, AgentCard): 
                log_raise('invalid request_data type')
        
        elif self.command == RequestCommand.GET_PSBL_ORDER: 
            if not isinstance(request_data, tuple): 
                log_raise('invalid request_data type')


    def get_request_data(self):
        return self.data['request_data']

    def set_additional_data(self, additional_data: dict):
        self.data.update(additional_data)  # append dict
    
    def get_id(self): 
        return self._request_id

@dataclass
class ServerResponse:
    success: bool
    status: str
    data: object = field(default_factory=dict)

    def __str__(self):
        if self.success:
            return 'Success '+ self.status
        else:
            return 'Fail ' + self.status

@dataclass
class CommandQueueInput:
    writer: object
    client_request: ClientRequest
