from dataclasses import dataclass, field 
from datetime import datetime
import uuid
import logging

from ..kis.ws_data import SIDE, MTYPE, EXG, TransactionNotice

@dataclass
class Order:
    # required vars
    agent_id: str 
    logger: logging.Logger
    code: str
    side: SIDE 
    mtype: MTYPE 
    quantity: int
    price: int # price sent for order submission
    exchange: EXG # KRX, NXT

    # auto gen
    unique_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    gen_time: str = field(default_factory=lambda: datetime.now().strftime('%m%d%H%M%S.%f'))

    # to be filled by server upon submission
    org_no: str | None = None # KIS specific (한국거래소전송주문조직번호)
    order_no: str | None = None # KIS specific 
    submitted_time: str | None = None 

    # control flags
    is_regular_order: bool = True # or CancelOrder
    submitted: bool = False # if order_no is assgined by KIS, then submitted = True
    accepted: bool = False
    completed: bool = False

    # for tax and fee calculation
    amount: int = 0 # total purchased/sold cumulative amount (sum of quantity x price)
    avg_price: float = 0 # meaningful only when it is an market order

    # actual status
    processed: int = 0
    fee_: int = 0
    tax_: int = 0

    def __post_init__(self):
        if type(self.quantity) != int or type(self.price) != int:
            self.logger.error("submit with quantity and/or price as int", extra={"owner":self.agent_id})
            raise ValueError
        if self.quantity < 0 or self.price  < 0:
            self.logger.error("negative quantity or price not allowed", extra={"owner":self.agent_id})
            raise ValueError
        if self.side not in ("buy", "sell"):
            self.logger.error("side must be 'buy' or 'sell'", extra={"owner":self.agent_id})
            raise ValueError
        if self.mtype == MTYPE.LIMIT and self.price == 0:
            self.logger.error("Limit orders require a price", extra={"owner":self.agent_id})
            raise ValueError
        if self.mtype == MTYPE.MARKET and self.price != 0: # for market orders, price has to be set to 0
            self.logger.error("Market orders should not have a price", extra={"owner":self.agent_id})
            raise ValueError
        if self.mtype == MTYPE.MIDDLE and self.price != 0: # for middle orders, price has to be set to 0
            self.logger.error("Middle orders should not have a price", extra={"owner":self.agent_id})
            raise ValueError
        if not self.mtype.is_allowed_in(self.exchange):
            self.logger.error(f"Order type {self.mtype.name} not allowed on exchange {self.exchange}", extra={"owner":self.agent_id})
            raise ValueError

    def _str_base(self):
        ordn = f"{int(self.order_no):>6d}" if self.order_no else f"  none"
        return (
            f"[O] {self.code} {self.agent_id:>5s} {ordn} "
            f"{self.gen_time[2:14]}({self.unique_id[:6]}) " # ddhhmmss.ff upto 1/10   00 sec
            f"P{self.price:>8,d} Q{self.quantity:>5,d} pr{self.processed:>5,d} "
            f"{self.side.name[:3]} {self.mtype.name[:3]} {self.exchange.name[:3]} "
            f"{'S' if self.submitted else '_'}"
            f"{'A' if self.accepted else '_'}"
            f"{'C' if self.completed else '_'}"
        )
    
    def __str__(self):
        txt = self._str_base()
        txt += (
            f"ftap:"
            f"{self.fee_:>6,d} "
            f"{self.tax_:>7,d} "
            f"{self.amount:>11,d} "
            f"{self.avg_price:>8,.0f}"
        )
        return txt

    def __eq__(self, other):
        if not isinstance(other, Order): return False
        return self.unique_id == other.unique_id and self.order_no == other.order_no and self.processed == other.processed

    def update_submit_response(self, order_no, submitted_time, org_no):
        self.order_no = order_no
        self.submitted_time = submitted_time
        self.org_no = org_no
        self.submitted = True
        self.logger.info(f"[Order] order {self.order_no} submitted", extra={"owner":self.agent_id})

    # internal update logic 
    # notice:
    # - oder_kind set to '00'(LIMIT) in 체결확인(022) reponses even when the order is otherwise 
    # rfus_yn / cntg_yn / acpt_yn 
    # - 011: order accepted
    # - 012: cancel or revise completed
    # - 022: order processed
    def update(self, notice: TransactionNotice):
        if self.order_no != notice.order_no: # checking order_no (or double-checking)
            self.logger.error(f"Notice does not match with order {self.order_no}", extra={"owner":self.agent_id})
            raise ValueError
        if self.completed: 
            print(self)
            self.logger.error(f"Notice for completed order {self.order_no} arrived", extra={"owner":self.agent_id})
            raise ValueError
        if notice.rfus_yn != "0": # "0": 승인
            self.logger.error(f"Order {self.order_no} refused", extra={"owner":self.agent_id})
            raise ValueError

        if notice.cntg_yn == "1": # 주문, 정정, 취소, 거부
            if notice.acpt_yn == "1": # 주문접수 (최초 주문)
                self.accepted = True
            elif notice.acpt_yn == "2": # 확인
                if notice.orignal_order_no is None:
                    self.logger.error("Check logic (original order no of notice)", extra={"owner":self.agent_id})
                    raise ValueError
                self.accepted = True
                self.update_cancel_specific(notice)
            else: # notice.acpt_yn == "3": # 취소(FOK/IOC)
                self.logger.error("Not implemented yet", extra={"owner":self.agent_id})
                raise ValueError

        else: # notice.cntg_yn == "2": # 체결
            if notice.acpt_yn == "2": # 확인
                self.processed += notice.cntg_qty
                self.amount += notice.cntg_qty*notice.cntg_unpr
                self.avg_price = self.amount/self.processed

                # 개별 체결건에 대해 fee, tax가 누적됨
                self.fee_ += notice.fee_
                self.tax_ += notice.tax_

                if self.processed > self.quantity:
                    self.logger.error("Check order processed quantity", extra={"owner":self.agent_id})
                    raise ValueError
                if self.processed == self.quantity:
                    self.completed = True
                    self.logger.info(f"[Order] order {self.order_no} completed\n    {self}", extra={"owner":self.agent_id})
            else: 
                self.logger.error("Check logic", extra={"owner":self.agent_id})
                raise ValueError

    def update_cancel_specific(self):
        # to be overrided by CancelOrder
        pass

    def make_a_cancel_order(self, partial: bool = False, to_cancel_qty: int = 0): 
        if self.completed:
            self.logger.error(f"[Order] tried to make a cancel order for a completed order: {self}", extra={"owner":self.agent_id})
            raise ValueError

        if partial: 
            qty_all_yn = "N"
        else: 
            qty_all_yn = "Y"

        return CancelOrder(
            agent_id=self.agent_id, 
            logger = self.logger, 
            code = self.code,
            side = self.side,
            mtype = self.mtype,
            quantity = to_cancel_qty,
            price = self.price,
            exchange = self.exchange,
            original_order_org_no = self.org_no, 
            original_order_no = self.order_no, 
            qty_all_yn=qty_all_yn, 
            )

@dataclass
class CancelOrder(Order):
    """
    revise is cancel + re-order
    new order_no is assigned both for revise and cancel
    command rule/sequence: ----------------------
    - check order_no 
    - check revise or cancel
    - check all or partial 
    - if all and revise:
    -     check mtype (market/middle or limit etc, previously ord_dvsn)
    -     check price (quantity can be any, at least "0" required)
    - if all and cancel:
    -     nothing matters (can be any, at least "0" required)
    - if partial and revise:
    -     check mtype 
    -     check price and quantity 
    - if partial and cancel:
    -     check quantity (price can be any, at least "0" required)

    partial revise/cancel
    - partial: 주식정정취소가능주문조회 상 정정취소가능수량(psbl_qty)을 Check 하라고 권고
    - 단, 해당 기능 모의투자 미지원 / API Call 소모 / Race condition could occur (해당 기능 이용해도 역시 발생가능)
    
    revise is only meaningful in 수량 축소: the same as partial cancel
    rule in matching sequence
    - 가격을 정정하면 새 주문으로 간주, 해당 가격대의 맨 뒤(가장 늦은 순위)로 이동
    - 수량만 줄이는 정정: 기존 순위 유지
    - 수량을 늘리는 정정: 새 주문 취급, 전체가 맨 뒤로 이동
    - 따라서, full or partial cancel 만 의미 있고, revise는 full / partial cancel + new order와 동일 
    - 본 Class는 full / partial cancel 만을 구현

    trn behavior
    - quantity: 취소 수량을 넣어야 함 (partial 의 경우)
    - 취소된 수량만큼 체결된 것처럼 trn이 보내짐, 코드는 012
    - 수량 초과시 그냥 trn이 오지 않음
    - KIS에서의 미체결량 = quantity - processed
    - KIS에서는 주문수량은 변치 않고 미체결량만 줄이나, 본 구현에서는 quantity를 줄이고, 원 주문수량은 없음
    """

    original_order_org_no: str | None = None
    original_order_no: str | None = None
    qty_all_yn: str = "Y"

    def __post_init__(self):
        # doesn't call super() automatically
        self.is_regular_order = False 

        if self.original_order_no is None or self.original_order_org_no is None:
            self.logger.error(f"[CancelOrder] original order info is missing {self}", extra={"owner":self.agent_id})
            raise ValueError

    def __str__(self): 
        txt = self._str_base()
        ordn = f"{int(self.original_order_no):>6d}" if self.original_order_no else f"  none"
        FP = "F" if self.qty_all_yn == "Y" else "P"
        txt += (
            f"{FP}C {ordn}"
        )
        return txt

    def update_submit_response(self, order_no, submitted_time, org_no):
        self.order_no = order_no
        self.submitted_time = submitted_time
        self.org_no = org_no
        self.submitted = True
        self.logger.info(f"[CancelOrder] a cancel-order {self.order_no} submitted to cancel order {self.original_order_no}", extra={"owner":self.agent_id})

    def update_cancel_specific(self, notice: TransactionNotice):
        self.completed = True
        self.quantity = notice.oder_qty # fill with to cancel quantity
        self.processed = notice.cntg_qty # fill with cancel processed
        self.logger.info(f"[CancelOrder] {self.order_no} completed: original order {self.original_order_no}", extra={"owner":self.agent_id})
