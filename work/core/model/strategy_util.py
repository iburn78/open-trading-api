from dataclasses import dataclass
from enum import Enum, auto

from ..model.order import Order
from ..kis.ws_data import SIDE, ORD_DVSN, EXCHANGE, RCtype, AllYN

class StrategyRequest(Enum):   
    ORDER = auto() 
    RC_ORDER = auto()

@dataclass
class StrategyCommand:
    request: StrategyRequest 

    # [StrategyRequest.ORDER]
    side: SIDE | None = None 
    exchange: EXCHANGE = EXCHANGE.SOR # optional

    # in case of ORDER, but also used in RC_ORDER if needed
    ord_dvsn: ORD_DVSN | None = None
    quantity: int | None = None
    price: int | None = None  

    # [StrategyRequest.RC_ORDER]
    rc: RCtype = None # '01': revise, '02': cancel
    all_yn: AllYN = None # 잔량 전부 주문 - Y:전부, N: 일부 
    original_order: Order = None  
    # - if ord_dvsn, quantity, price are None, they are assigned by agent as in the original_order
    # - refer to the agent.create_an_order()

    def __str__(self):
        parts = [f"[StrategyCommand] {self.request.name}:"]
        if self.side: parts.append(self.side.name)
        if self.ord_dvsn: parts.append(self.ord_dvsn.name)
        if self.quantity: parts.append(f"q: {self.quantity}")
        if self.price: parts.append(f"p: {self.price}")
        if self.rc: parts.append(self.rc)
        if self.all_yn: parts.append(self.all_yn)
        if self.original_order: parts.append(self.original_order.order_no) 
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
