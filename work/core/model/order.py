import pandas as pd
from dataclasses import dataclass, field 
import uuid

from .cost import CostCalculator
from ..common.optlog import optlog, log_raise, LOG_INDENT
from ..kis.ws_data import SIDE, ORD_DVSN, EXCHANGE, TransactionNotice
from ..kis.custom_functions import order_cash_async, order_rvsecncl_async

@dataclass
class Order:
    # required vars
    agent_id: str 
    code: str
    side: SIDE 
    ord_dvsn: ORD_DVSN 
    quantity: int
    price: int # price sent for order submission
    exchange: EXCHANGE # KRX, NXT
    listed_market: str | None = None # KOSPI, KOSDAQ, etc 

    # auto gen
    unique_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    gen_time: str = field(default_factory=lambda: pd.Timestamp.now().strftime('%m%d%H%M%S.%f'))

    # to be filled by server upon submission
    org_no: str | None = None
    order_no: str | None = None
    submitted_time: str | None = None 

    # control flags
    is_regular_order: bool = True
    submitted: bool = False # if order_no is assgined by KIS, then submitted == True
    accepted: bool = False
    completed: bool = False

    # for tax and fee calculation
    amount: int = 0 # total purchased/sold cumulative amount (sum of quantity x price)
    avg_price: float = 0 # meaningful only when it is an market order

    # actual status
    processed: int = 0
    fee_: int = 0
    tax_: int = 0

    # Further develop needs:
    # - IOC, FOK, handling of end of day cancellation etc

    def __post_init__(self):
        if type(self.quantity) != int or type(self.price) != int:
            log_raise("submit with quantity and/or price as int ---", name=self.agent_id)
        if self.side not in ("buy", "sell"):
            log_raise("side must be 'buy' or 'sell' ---", name=self.agent_id)

        if self.ord_dvsn == ORD_DVSN.LIMIT and self.price == 0:
            log_raise("Limit orders require a price", name=self.agent_id)
        if self.ord_dvsn == ORD_DVSN.MARKET and self.price != 0: # for market orders, price has to be set to 0
            log_raise("Market orders should not have a price ---", name=self.agent_id)
        if self.ord_dvsn == ORD_DVSN.MIDDLE and self.price != 0: # for middle orders, price has to be set to 0
            log_raise("Middle orders should not have a price ---", name=self.agent_id)

        if not self.ord_dvsn.is_allowed_in(self.exchange):
            log_raise(f"Order type {self.ord_dvsn.name} not allowed on exchange {self.exchange} ---", name=self.agent_id)

    def _str_base(self):
        ordn = f"{int(self.order_no):>6d}" if self.order_no else f"  none"
        return (
            f"[O] {self.code} {self.agent_id:>5s} {ordn} "
            f"{self.gen_time[2:14]}({self.unique_id[:6]}) " # ddhhmmss.ff upto 1/10   00 sec
            f"P{self.price:>8,d} Q{self.quantity:>5,d} pr{self.processed:>5,d} "
            f"{self.side.name[:3]} {self.ord_dvsn.name[:3]} {self.exchange.name[:3]} "
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

    # async submit is handled in order_manager in the server side (so logging is in the server side)
    async def submit(self, trenv, _http):
        if self.completed:
            optlog.error(f"A completed order is submitted: order submission aborted {self.unique_id}", name=self.agent_id)
            return

        ord_qty = str(self.quantity)
        ord_unpr = str(self.price)
        res = await order_cash_async(
            _http=_http,
            env_dv=trenv.env_dv, 
            ord_dv=self.side, 
            cano=trenv.my_acct, 
            acnt_prdt_cd=trenv.my_prod, 
            pdno=self.code, 
            ord_dvsn=self.ord_dvsn, 
            ord_qty=ord_qty, 
            ord_unpr=ord_unpr, 
            excg_id_dvsn_cd=self.exchange
            )

        if res.empty:
            # order failed
            optlog.error(f"[Order] order submit response empty, uid {self.unique_id}", name=self.agent_id)
        elif pd.isna(res.loc[0, ["ODNO", "ORD_TMD", "KRX_FWDG_ORD_ORGNO"]]).any():
            optlog.error(f"[Order] check response {res}", name=self.agent_id)
        else:
            self.order_no = res.ODNO.iloc[0]
            self.submitted_time = res.ORD_TMD.iloc[0]
            self.org_no = res.KRX_FWDG_ORD_ORGNO.iloc[0]
            self.submitted = True
            optlog.info(f"[Order] order {self.order_no} submitted", name=self.agent_id)

    # internal update logic 
    # notice:
    # - oder_kind set to '00'(LIMIT) in 체결확인(022) reponses even when the order is otherwise 
    # rfus_yn / cntg_yn / acpt_yn 
    # - 011: order accepted
    # - 012: cancel or revise completed
    # - 022: order processed
    def update(self, notice: TransactionNotice, trenv):
        if self.order_no != notice.oder_no: # checking order_no (or double-checking)
            log_raise(f"Notice does not match with order {self.order_no} ---", name=self.agent_id)
        if self.completed: 
            log_raise(f"Notice for completed order {self.order_no} arrived ---", name=self.agent_id)
        if notice.rfus_yn != "0": # "0": 승인
            log_raise(f"Order {self.order_no} refused ---", name=self.agent_id)

        if notice.cntg_yn == "1": # 주문, 정정, 취소, 거부
            if notice.acpt_yn == "1": # 주문접수 (최초 주문)
                self.accepted = True
            elif notice.acpt_yn == "2": # 확인
                if notice.ooder_no is None:
                    log_raise("Check logic (original order no of notice) ---", name=self.agent_id)
                self.accepted = True
                self.update_cancel_specific(notice)
            else: # notice.acpt_yn == "3": # 취소(FOK/IOC)
                log_raise("Not implemented yet ---", name=self.agent_id)

        else: # notice.cntg_yn == "2": # 체결
            if notice.acpt_yn == "2": # 확인
                self.processed += notice.cntg_qty
                self.amount += notice.cntg_qty*notice.cntg_unpr
                self.avg_price = self.amount/self.processed

                fee_, tax_ = CostCalculator.calculate(
                    side = notice.seln_byov_cls,
                    quantity = notice.cntg_qty, 
                    price = notice.cntg_unpr,
                    svr = trenv.my_svr,
                    listed_market = self.listed_market, 
                    traded_exchange = notice.traded_exchange
                )
                # 개별 체결건에 대해 fee, tax가 누적됨
                self.fee_ += fee_
                self.tax_ += tax_

                if self.processed > self.quantity:
                    log_raise('Check order processed quantity ---', name=self.agent_id)
                if self.processed == self.quantity:
                    self.completed = True
                    optlog.info(f"[Order] order {self.order_no} completed\n{LOG_INDENT}{self}", name=self.agent_id)
            else: 
                log_raise("Check logic ---", name=self.agent_id)

    def update_cancel_specific(self):
        # to be overrided by CancelOrder
        pass

    def make_a_cancel_order(self, partial: bool = False, to_cancel_qty: int = 0): 
        if self.completed:
            optlog.warning(f"tried to make a cancel order for a completed order: {self}", name=self.agent_id)
            return None

        if partial: 
            qty_all_yn = "N"
        else: 
            qty_all_yn = "Y"

        return CancelOrder(
            agent_id=self.agent_id, 
            code = self.code,
            side = self.side,
            ord_dvsn = self.ord_dvsn,
            quantity = to_cancel_qty,
            price = self.price,
            exchange = self.exchange,
            o_order_org_no = self.org_no, 
            o_order_order_no = self.order_no, 
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
    -     check ord_dvsn (market/middle or limit etc)
    -     check price (quantity can be any, at least "0" required)
    - if all and cancel:
    -     nothing matters (can be any, at least "0" required)
    - if partial and revise:
    -     check ord_dvsn (market/middle or limit etc)
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

    o_order_org_no: str | None = None
    o_order_order_no: str | None = None
    qty_all_yn: str = "Y"

    def __post_init__(self):
        # doesn't call super() automatically
        self.is_regular_order = False 

        if self.o_order_order_no is None or self.o_order_org_no is None:
            optlog.error(f"[CancelOrder] original order info is missing {self}", name=self.agent_id)

    def __str__(self): 
        txt = self._str_base()
        ordn = f"{int(self.o_order_order_no):>6d}" if self.o_order_order_no else f"  none"
        FP = "F" if self.qty_all_yn == "Y" else "P"
        txt += (
            f"{FP}C {ordn}"
        )
        return txt

    async def submit(self, trenv, _http):
        res = await order_rvsecncl_async(
            _http=_http,
            env_dv=trenv.env_dv,
            cano=trenv.my_acct,
            acnt_prdt_cd=trenv.my_prod,
            krx_fwdg_ord_orgno=self.o_order_org_no,
            orgn_odno=self.o_order_order_no,
            ord_dvsn=self.ord_dvsn, 
            rvse_cncl_dvsn_cd='02', # cancel
            ord_qty=str(self.quantity), # to cancel quantity
            ord_unpr='0', # send it with 0 as cancel
            qty_all_ord_yn=self.qty_all_yn, 
            excg_id_dvsn_cd=self.exchange
        )
        if res.empty:
            # order failed: 수량 초과시 포함
            optlog.error(f'[CancelOrder] order submit response empty, uid {self.unique_id}', name=self.agent_id)
        elif pd.isna(res.loc[0, ["ODNO", "ORD_TMD", "KRX_FWDG_ORD_ORGNO"]]).any():
            optlog.error(f"[CancelOrder] check response: {res}", name=self.agent_id)
        else:
            self.order_no = res.ODNO.iloc[0]
            self.submitted_time = res.ORD_TMD.iloc[0]
            self.org_no = res.KRX_FWDG_ORD_ORGNO.iloc[0]
            self.submitted = True
            optlog.info(f"[CancelOrder] a cancel-order {self.order_no} submitted to cancel order {self.o_order_order_no}", name=self.agent_id)

    def update_cancel_specific(self, notice: TransactionNotice):
        self.completed = True
        self.quantity = notice.oder_qty # fill with to cancel quantity
        self.processed = notice.cntg_qty # fill with cancel processed
        optlog.info(f"[CancelOrder] {self.order_no} completed: original order {self.o_order_order_no}", name=self.agent_id)
