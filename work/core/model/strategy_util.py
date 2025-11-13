from dataclasses import dataclass, field
from enum import Enum, auto
import uuid

from ..kis.ws_data import SIDE, ORD_DVSN, EXCHANGE

class StrategyRequest(Enum):   
    ORDER = auto() # create an order and submit
    PSBL_QUANTITY = auto() # API check for psbl buy quantity through agent

@dataclass
class StrategyCommand:
    # set default to StrategyRequest.ORDER
    request: StrategyRequest = field(default_factory=lambda: StrategyRequest.ORDER)

    # incase of StrategyRequest.ORDER and PSBL_QUANTITY
    side: SIDE | None = None 
    ord_dvsn: ORD_DVSN | None = None
    quantity: int = 0
    price: int = 0 
    exchange: EXCHANGE = EXCHANGE.SOR # optional

    # uid
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __str__(self):
        parts = [f"[StrategyCommand] {self.request.name}:"]
        if self.side: parts.append(self.side.name)
        if self.ord_dvsn: parts.append(self.ord_dvsn.name)
        if self.quantity: parts.append(f"q: {self.quantity}")
        if self.price: parts.append(f"p: {self.price}")
        return " ".join(parts)

@dataclass
class StrategyResponse():   
    request: StrategyRequest 
    response_data: object | None = None

class UpdateEvent(Enum):   
    INITIATE = auto()
    PRICE_UPDATE = auto()
    TRN_RECEIVE = auto()
    ORDER_RECEIVE = auto() 