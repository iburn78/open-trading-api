import pandas as pd
from dataclasses import dataclass, field 

from .cost import CostCalculator
from ..common.optlog import optlog, log_raise, LOG_INDENT
from ..kis.domestic_stock_functions import order_cash, order_rvsecncl
from ..kis.ws_data import SIDE, ORD_DVSN, EXCHANGE, TransactionNotice

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
    unique_id: str = field(default_factory=lambda: pd.Timestamp.now().strftime('%Y%m%d%H%M%S%f'))

    # to be filled by server upon submission
    org_no: str | None = None
    order_no: str | None = None
    submitted_time: str | None = None 

    # control flags
    submitted: bool = False # if order_no is assgined by KIS, then submitted == True
    accepted: bool = False
    completed: bool = False
    cancelled: bool = False 

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
        
    def __str__(self):
        ordn = f"{int(self.order_no):>6d}" if self.order_no else f"  none"
        return (
            f"[O] {self.code} {self.agent_id:>5s} {ordn} "
            f"{self.unique_id[6:14]}.{self.unique_id[14:16]} " # ddhhmmss.ff upto 1/100 sec
            f"P{self.price:>8,d} Q{self.quantity:>5,d} pr{self.processed:>5,d} "
            f"{self.side.name[:3]} {self.ord_dvsn.name[:3]} {self.exchange.name[:3]} "
            f"{'S' if self.submitted else '_'}"
            f"{'A' if self.accepted else '_'}"
            f"{'CP' if self.completed else '__'}"
            f"{'CL' if self.cancelled else '__'} "
            f"ftap:"
            f"{self.fee_:>6,d} "
            f"{self.tax_:>7,d} "
            f"{self.amount:>11,d} "
            f"{self.avg_price:>8,.0f}"
        )

    def __eq__(self, other):
        if not isinstance(other, Order): return False
        return self.unique_id == other.unique_id and self.order_no == other.order_no and self.processed == other.processed

    # async submit is handled in order_manager in the server side (so logging is in the server side)
    def submit(self, trenv):
        if self.completed or self.cancelled:
            log_raise('A completed or cancelled order is submitted ---', name=self.agent_id)

        ord_qty = str(self.quantity)
        ord_unpr = str(self.price)
        res = order_cash(
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
    def update(self, notice: TransactionNotice, trenv):
        if self.order_no != notice.oder_no: # checking order_no (or double-checking)
            log_raise(f"Notice does not match with order {self.order_no} ---", name=self.agent_id)
        if self.completed or self.cancelled: 
            log_raise(f"Notice for completed or cancelled order {self.order_no} arrived ---", name=self.agent_id)
        if notice.rfus_yn != "0": # "0": 승인
            log_raise(f"Order {self.order_no} refused ---", name=self.agent_id)

        if notice.cntg_yn == "1": # 주문, 정정, 취소, 거부
            if notice.acpt_yn == "1": # 주문접수 (최초 주문)
                self.accepted = True
            elif notice.acpt_yn == "2": # 확인
                if notice.ooder_no is None:
                    log_raise("Check logic (original order no of notice) ---", name=self.agent_id)
                self.accepted = True
                self.update_rc_specific()
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

    def update_rc_specific(self):
        # to be overrided by CancelOrder
        pass

    def make_a_cancel_order(self): 
        if not self.submitted or self.completed or self.cancelled:
            optlog.error(f"cannot make a cancel order for {self}", name=self.agent_id)
        return CancelOrder(
            agent_id=self.agent_id, 
            code = self.code,
            side = self.side,
            ord_dvsn = self.ord_dvsn,
            quantity = self.quantity,
            price = self.price,
            exchange = self.exchange,
            original_order=self)

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
    # Note: 
    - partial: 주식정정취소가능주문조회 상 정정취소가능수량(psbl_qty)을 Check 하라고 권고
    - 단, 해당 기능 모의투자 미지원
    - Race condition could occur (해당 기능 이용해도 역시 발생가능)
    """

    # for simplicity and clarity, only cancel / all is implemented
    # cancelled original orders are also set to "COMPLETED"
    original_order: Order | None = None

    def __post_init__(self):
        super().__post_init__()  # need to call explicitly 
        if self.original_order is None: 
            optlog.error(f"[CancelOrder] original order is missing {self}", name=self.agent_id)

    def submit(self, trenv):
        res = order_rvsecncl(
            env_dv=trenv.env_dv,
            cano=trenv.my_acct,
            acnt_prdt_cd=trenv.my_prod,
            krx_fwdg_ord_orgno=self.original_order.org_no,
            orgn_odno=self.original_order.order_no,
            ord_dvsn=self.ord_dvsn, 
            rvse_cncl_dvsn_cd='02', # cancel
            ord_qty='0',
            ord_unpr='0', 
            qty_all_ord_yn='Y', # all (잔량전부)
            excg_id_dvsn_cd=self.exchange
        )
        if res.empty:
            # maybe the case that fails to cancel
            optlog.warning(f'[CancelOrder] order submit response empty, uid {self.unique_id}', name=self.agent_id)
        elif pd.isna(res.loc[0, ["ODNO", "ORD_TMD", "KRX_FWDG_ORD_ORGNO"]]).any():
            # maybe the case that fails to cancel
            optlog.warning(f"[CancelOrder] check response: {res}", name=self.agent_id)
        else:
            self.order_no = res.ODNO.iloc[0]
            self.submitted_time = res.ORD_TMD.iloc[0]
            self.org_no = res.KRX_FWDG_ORD_ORGNO.iloc[0]
            self.submitted = True
            optlog.info(f"[CancelOrder] a cancel-order {self.order_no} submitted to cancel order {self.original_order.order_no}", name=self.agent_id)

    def update_rc_specific(self):
        self.original_order.cancelled = True
        self.original_order.completed = True # consider it completed
        self.completed = True
        optlog.info(f"[CancelOrder] {self.order_no} completed: original order {self.original_order.order_no} cancelled", name=self.agent_id)
