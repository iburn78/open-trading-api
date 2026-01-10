from dataclasses import dataclass, field
from enum import Enum, auto
import uuid

from ..base.tools import dict_key_number

class RequestCommand(Enum):
    SUBMIT_ORDERS = auto()
    REGISTER_AGENT_CARD = auto()
    SYNC_ORDER_HISTORY = auto()
    SYNC_COMPLETE_NOTICE = auto()
    SUBSCRIBE_TRP = auto()
    GET_PSBL_ORDER = auto()

@dataclass
class ClientRequest:
    command: RequestCommand
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    data_dict: dict = field(default_factory=lambda: {'request_data': None})

    def __str__(self):
        return self.command.name

    def set_request_data(self, request_data=None):
        self.data_dict['request_data'] = request_data

    def get_request_data(self):
        return self.data_dict['request_data']

@dataclass
class ServerResponse: # acknowledgement of client_request
    success: bool
    status: str
    data_dict: dict = field(default_factory=dict)
    request_id: str | None = None

    def __str__(self):
        if self.success:
            return '[Success] '+ self.status 
        else:
            return '[Fail] '+ self.status

@dataclass
class OM_Dispatch:
    data: object 
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

# on every OM_Dispatch, client sends Dispatch_ACK
@dataclass
class Dispatch_ACK:
    id: str 
    agent_id: str

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

    def __str__(self):
        res = ''
        for k, v in (self.prev_incompleted_orders or {}).items():
            res += f'p-inc {v}\n'
        for k, v in (self.incompleted_orders or {}).items():
            res += f't-inc {v}\n'
        for k, v in (self.completed_orders or {}).items():
            res += f'comp  {v}\n'
        res += dict_key_number(self.pending_trns) if self.pending_trns else ''
        
        if res: res = '\n'+res 
        else: res = "sync data empty"

        return res