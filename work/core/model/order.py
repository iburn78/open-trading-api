import json
import pandas as pd
from dataclasses import dataclass, field, asdict

from .cost import CostCalculator
from ..common.optlog import optlog, log_raise
from ..common.tools import get_market, excel_round_int 
from ..kis.domestic_stock_functions import order_cash, order_rvsecncl
from ..kis.ws_data import SIDE, ORD_DVSN, EXCHANGE, RCtype, AllYN, TransactionNotice

@dataclass
class Order:
    agent_id: str 

    code: str
    side: SIDE 
    ord_dvsn: ORD_DVSN 
    quantity: int
    price: int
    exchange: EXCHANGE 

    # auto gen
    unique_id: str = field(default_factory=lambda: pd.Timestamp.now().strftime('%Y%m%d%H%M%S%f'))

    # to be filled by server upon submission
    org_no: str | None = None
    order_no: str | None = None
    submitted_time: str | None = None

    # control flags
    submitted: bool = False
    accepted: bool = False
    completed: bool = False
    cancelled: bool = False 

    # for tax and fee calculation
    amount: int = 0 # total purchased/sold cumulative amount (sum of quantity x price)
    avg_price: float = 0.0
    bep_cost: int = 0
    bep_price: float = 0.0
    market: str = None # KOSPI, KOSDAQ, etc

    # - as the order is fullfilled, cost_occured should refect exact cost up to that moment
    # - round only done when the order is fully fullfilled
    processed: int = 0
    fee_occured: float = 0.0
    tax_occured: float = 0.0
    fee_rounded: int = 0   # if completed or cancelled, this is final 
    tax_rounded: int = 0   # if completed or cancelled, this is final 

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

        self.market = get_market(self.code)

        if not self.ord_dvsn.is_allowed_in(self.exchange):
            log_raise(f"Order type {self.ord_dvsn.name} not allowed on exchange {self.exchange} ---", name=self.agent_id)

        if self.market not in ['KOSPI', 'KOSDAQ']:
            log_raise("Check the market of the stock: KOSPI or KOSDAQ ---", name=self.agent_id)
        
    def __str__(self):
        return (
            f"Order {self.code}, agent {self.agent_id}, odno: {self.order_no}, "
            f"{self.side.name}, {self.ord_dvsn.name}, {self.exchange.name}, "
            f"Q {self.quantity}, P {self.price}, processed {self.processed}, "
            f"{'submitted' if self.submitted else 'not_submitted'}, "
            f"{'accepted' if self.accepted else 'not_accepted'}, "
            f"{'completed' if self.completed else 'not_completed'}, "
            f"{'cancelled' if self.cancelled else 'not_cancelled'}"
        )

    # async submit is handled in order_manager in the server side
    def submit(self, trenv):
        if self.completed or self.cancelled:
            log_raise('A completed or cancelled order submitted ---', name=self.agent_id)

        ord_qty = str(self.quantity)
        ord_unpr = str(self.price)
        res = order_cash(env_dv=trenv.env_dv, ord_dv=self.side, cano=trenv.my_acct, acnt_prdt_cd=trenv.my_prod, pdno=self.code, ord_dvsn=self.ord_dvsn, ord_qty=ord_qty, ord_unpr=ord_unpr, excg_id_dvsn_cd=self.exchange)

        if res.empty:
            log_raise('Order submit response empty ---', name=self.agent_id)
        else: 
            if pd.isna(res.loc[0, ["ODNO", "ORD_TMD", "KRX_FWDG_ORD_ORGNO"]]).any():
                log_raise("Check submission response ---", name=self.agent_id)
            self.order_no = res.ODNO.iloc[0]
            self.submitted_time = res.ORD_TMD.iloc[0]
            self.org_no = res.KRX_FWDG_ORD_ORGNO.iloc[0]
            self.submitted = True
            optlog.info(f"Order {self.order_no} submitted", name=self.agent_id)

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

                fee_float, tax_float, fee_rd, tax_rd = CostCalculator.calculate(
                    side = notice.seln_byov_cls,
                    quantity = notice.cntg_qty, 
                    price = notice.cntg_unpr,
                    market = self.market, 
                    svr = trenv.my_svr,
                    traded_exchange = notice.traded_exchange
                )
                self.fee_occured += fee_float
                self.tax_occured += tax_float
                self.fee_rounded = excel_round_int(self.fee_occured, fee_rd)
                self.tax_rounded = excel_round_int(self.tax_occured, tax_rd)

                self.bep_cost, self.bep_price = CostCalculator.bep_cost_calculate(self.processed, self.avg_price, self.market, trenv.my_svr)

                if self.processed > self.quantity:
                    log_raise('Check order processed quantity ---', name=self.agent_id)
                if self.processed == self.quantity:
                    self.completed = True
                    optlog.info(f"Order {self.order_no} completed", name=self.agent_id)
            else: 
                log_raise("Check logic ---", name=self.agent_id)

    def update_rc_specific(self):
        # to be overrided by ReviseCancelOrder
        # no need to define any here
        pass

    def make_revise_cancel_order(self, rc, ord_dvsn, qty, pr, all_yn): # ord_dvsn could changed, e.g., from limit to market
        if not self.submitted:
            log_raise(f"Order {self.order_no} not submitted yet but revise-cancel tried / instead modify order itself ---", name=self.agent_id)
        return ReviseCancelOrder(agent_id=self.agent_id, code=self.code, side=self.side, ord_dvsn=ord_dvsn, quantity=qty, price=pr, rc=rc, all_yn=all_yn, original_order=self)

@dataclass
class ReviseCancelOrder(Order):
    """
    revise is cancel + re-order
    new order_no is assigned both for revise and cancel
    command rule/sequence: ----------------------
    - check order_no 
    - check revise or cancel
    - check all or partial 
    - if all and revise:
    -     check ord_dvsn (market or limit etc)
    -     check price (quantity can be any, at least "0" required)
    - if all and cancel:
    -     nothing matters (can be any, at least "0" required)
    - if partial and revise:
    -     check ord_dvsn (market or limit etc)
    -     check price and quantity
    - if partial and cancel:
    -     check quantity (price can be any, at least "0" required)
    """
    rc: RCtype = None # '01': revise, '02': cancel
    all_yn: AllYN = None # 잔량 전부 주문 - Y:전부, N: 일부 
    original_order: Order = None

    def __post_init__(self):
        super().__post_init__()  # need to call explicitly 
        if self.original_order is None: 
            log_raise("Check revise-cancel original order ---", name=self.agent_id)

    def submit(self, trenv):
        ord_qty = str(self.quantity)
        ord_unpr = str(self.price)
        res = order_rvsecncl(
            env_dv=trenv.env_dv,
            cano=trenv.my_acct,
            acnt_prdt_cd=trenv.my_prod,
            krx_fwdg_ord_orgno=self.original_order.org_no,
            orgn_odno=self.original_order.order_no,
            ord_dvsn=self.ord_dvsn, 
            rvse_cncl_dvsn_cd=self.rc, 
            ord_qty=ord_qty,
            ord_unpr=ord_unpr, 
            qty_all_ord_yn=self.all_yn, 
            excg_id_dvsn_cd=self.exchange
        )
        if res.empty:
            log_raise(f'Order {self.order_no} revise-cancel failed ---', name=self.agent_id)
        else: 
            if pd.isna(res.loc[0, ["ODNO", "ORD_TMD", "KRX_FWDG_ORD_ORGNO"]]).any():
                log_raise("Check revise-cancel response ---", name=self.agent_id)
            self.order_no = res.ODNO.iloc[0]
            self.submitted_time = res.ORD_TMD.iloc[0]
            self.org_no = res.KRX_FWDG_ORD_ORGNO.iloc[0]
            self.submitted = True

            if self.rc == RCtype.REVISE:
                optlog.info(f"Order {self.original_order.order_no}'s revise order {self.order_no} submitted", name=self.agent_id)
            else: # cancel
                optlog.info(f"Order {self.original_order.order_no}'s {'full' if self.all_yn == AllYN.ALL else 'partial'} cancellation order {self.order_no} submitted", name=self.agent_id)

    # internal update logic for revise-cancel order
    def update_rc_specific(self):
        if self.original_order.completed or self.original_order.cancelled: 
            log_raise("Check update_original, as original order is completed or cancelled ---", name=self.agent_id)

        if self.all_yn == AllYN.ALL: 
            self.quantity = self.original_order.quantity - self.original_order.processed
            self.original_order.quantity = self.original_order.processed
            self.original_order.completed = True
        else: 
            self.original_order.quantity = self.original_order.quantity - self.quantity
            if self.original_order.quantity == self.original_order.processed:
                self.original_order.completed = True
            elif self.original_order.quantity < self.original_order.processed:
                log_raise('Check partial order revise-cancel logic ---', name=self.agent_id)
        
        if self.rc == RCtype.CANCEL: 
            self.cancelled = True
