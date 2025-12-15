from enum import Enum, auto

class UpdateEvent(Enum):   
    INITIATE = auto()
    PRICE_UPDATE = auto()
    TRN_RECEIVE = auto()
    ORDER_RECEIVE = auto() 
