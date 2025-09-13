from __future__ import annotations
from domestic_stock_functions_ws import *
from domestic_stock_functions import *
import overseas_stock_functions as osf 
import json
from dataclasses import dataclass, field, asdict
from typing import Optional
from decimal import Decimal
from enum import Enum
import asyncio
from kis_auth import _smartSleep, _demoSleep
import logging

logging.basicConfig(
    level=logging.INFO,  # 최소 출력 레벨
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("opt.log"),  # 파일 출력
        logging.StreamHandler()           # 콘솔 출력
    ]
)

optlogger = logging.getLogger(__name__)

def log_raise(msg):
    optlogger.error(msg)
    raise Exception(msg) from None  # suppress pointing this exact log_raise function

tr_id_dict = {
    'TradeNotice': {'demo': 'H0STCNI9', 'real': 'H0STCNI0',},
    # to add more...
}

rev_tr_id_dict = {
    (env, tr): name
    for name, env_dict in tr_id_dict.items()
    for env, tr in env_dict.items()
}

def get_tr(trenv, tr_id, rev_tr_id_dict = rev_tr_id_dict):
    return rev_tr_id_dict.get((trenv.env_dv, tr_id))

async def async_sleep(trenv):
    if trenv.env_dv == 'demo':
        await asyncio.sleep(_demoSleep)
    else: 
        await asyncio.sleep(_smartSleep)

@dataclass
class CashBalance:
    available: int = 0      # 현재 예수금 (T+0)
    t_1: int = 0            # T+1 예수금
    t_2: int = 0            # T+2 예수금

    def __str__(self):
        return (
            f"----------------------------------------------------------------\n"
            f"CashBalance: {self.available:,} / T+1: {self.t_1:,} / T+2: {self.t_2:,}\n"
            f"----------------------------------------------------------------"
        )

@dataclass 
class Holding:  # Stock Holding
    name: str
    code: str
    quantity: int
    amount: int
    avg_price: float = 0.0   

    def __str__(self):
        return (
            f"{self.code} / {self.quantity:,} / {self.name}\n"
            f"total amount: {self.amount:,}, avg price: {self.avg_price:,}\n"
        )

@dataclass
class Account:
    holdings: list[Holding] = field(default_factory=list)
    cash: CashBalance = None

    def __str__(self):
        parts = [str(self.cash)] if self.cash else []
        parts.extend(str(h) for h in self.holdings)
        return "\n".join(parts)

    def acc_load(self, trenv):
        ptf, acc = inquire_balance(
            cano=trenv.my_acct,
            env_dv=trenv.env_dv,
            acnt_prdt_cd=trenv.my_prod,
            afhr_flpr_yn="N",
            inqr_dvsn="01",
            unpr_dvsn="01",
            fund_sttl_icld_yn="N",
            fncg_amt_auto_rdpt_yn="N",
            prcs_dvsn="00"
        )

        # 예수금 할당
        self.cash = self.cash or CashBalance()
        self.cash.available = int(acc["dnca_tot_amt"].iloc[0])
        self.cash.t_1 = int(acc["nxdy_excc_amt"].iloc[0])
        self.cash.t_2 = int(acc["prvs_rcdl_excc_amt"].iloc[0])
        
        # Just checking for making it sure
        for col in ["dnca_tot_amt", "nxdy_excc_amt", "prvs_rcdl_excc_amt"]:
            if acc[col].nunique() != 1:
                log_raise("Return value of account cash is not unique ---")

        # 보유 종목 Sync
        new_holdings = [] 
        for _, row in ptf.iterrows():  # DataFrame에서 row 반복
            code = row.pdno
            holding = next((h for h in self.holdings if h.code == code), None)

            if holding:
                holding.quantity = int(row.hldg_qty)
                holding.amount = int(row.pchs_amt)
            else: 
                holding = Holding(
                        name = row.prdt_name, 
                        code = row.pdno,
                        quantity = int(row.hldg_qty), 
                        amount = int(row.pchs_amt)
                )
            new_holdings.append(holding)
        self.holdings = new_holdings
        return self

class ORD_DVSN(str, Enum):
    LIMIT = '00'
    MARKET = '01'

@dataclass
class Order:
    code: str
    side: str # 'buy' or 'sell'
    quantity: int
    ord_dvsn: ORD_DVSN # market or limit
    price: int
    market: str = "SOR" # Smart Order Routing

    org_no: Optional[str] = None
    order_no: Optional[str] = None
    submitted_time: Optional[str] = None

    submitted: bool = False
    accepted: bool = False
    processed: int = 0
    completed: bool = False
    cancelled: bool = False 

    # NEED TO CLARIFY CALCELLED LOGIC
    # IOC, FOK, End of day cancellation etc
    # even not completed, remainder of order not to be processed

    def __post_init__(self):
        if type(self.quantity) != int or type(self.price) != int:
            log_raise("submit with quantity and/or price as int")
        if self.side not in ("buy", "sell"):
            log_raise("side must be 'buy' or 'sell'")

        if self.ord_dvsn == ORD_DVSN.LIMIT and self.price == 0:
            log_raise("Limit orders require a price")
        if self.ord_dvsn == ORD_DVSN.MARKET and self.price != 0:
            log_raise("Market orders should not have a price")
    
    def __str__(self):
        return "Order:" + json.dumps(asdict(self), indent=4, default=str)

    def submit(self, trenv):
        if self.completed or self.cancelled:
            log_raise('A completed or cancelled order submitted ---')

        ord_qty = str(self.quantity)
        ord_unpr = str(self.price)
        res = order_cash(env_dv=trenv.env_dv, ord_dv=self.side, cano=trenv.my_acct, acnt_prdt_cd=trenv.my_prod, pdno=self.code, ord_dvsn=self.ord_dvsn, ord_qty=ord_qty, ord_unpr=ord_unpr, excg_id_dvsn_cd=self.market)

        if res.empty:
            log_raise('Order submission failed ---')
        else: 
            if pd.isna(res.loc[0, ["ODNO", "ORD_TMD", "KRX_FWDG_ORD_ORGNO"]]).any():
                log_raise("Check submission response ---")
            self.order_no = res.ODNO.iloc[0]
            self.submitted_time = res.ORD_TMD.iloc[0]
            self.org_no = res.KRX_FWDG_ORD_ORGNO.iloc[0]
            self.submitted = True
            optlogger.info(f"Order {self.order_no} submitted")
    
    def update(self, notice: TradeNotice):
        if self.order_no != notice.oder_no: # checking order_no (or double-checking)
            log_raise(f"Notice does not match with order {self.order_no} ---")
        if self.completed or self.cancelled: 
            log_raise(f"Notice for completed or cancelled order {self.order_no} arrived ---")
        if notice.rfus_yn != "0": # "0": 승인
            log_raise(f"Order {self.order_no} refused ---")

        if notice.cntg_yn == "1": # 주문, 정정, 취소, 거부
            if notice.acpt_yn == "1": # 주문접수 (최초 주문)
                self.accepted = True
            elif notice.acpt_yn == "2": # 확인
                if notice.ooder_no is None:
                    log_raise("Check logic (original order no of notice) ---")
                self.accepted = True
                self.update_rc_specific()
            else: # notice.acpt_yn == "3": # 취소(FOK/IOC)
                log_raise("Not implemented yet ---")

        else: # notice.cntg_yn == "2": # 체결
            if notice.acpt_yn == "2": # 확인
                self.processed += notice.cntg_qty
                if self.processed > self.quantity:
                    log_raise('Check order processed quantity ---')
                if self.processed == self.quantity:
                    self.completed = True
                    optlogger.info(f"Order {self.order_no} completed")
            else: 
                log_raise("Check logic ---")

    def update_rc_specific(self):
        # to be overrided by ReviseCancelOrder
        pass

    def make_revise_cancel_order(self, rc, qty, ord_dvsn, pr, all_yn):   # ord_dvsn could changed, e.g., from limit to market
        if not self.submitted:
            log_raise(f"Order {self.order_no} not submitted yet but revise-cancel tried / instead modify order itself ---")
        return ReviseCancelOrder(self.code, self.side, qty, ord_dvsn, pr, rc=rc, all_yn=all_yn, original_order=self)

class RCtype(str, Enum):
    REVISE = '01'
    CANCEL = '02'

class AllYN(str, Enum):
    ALL = 'Y'
    PARTIAL = 'N'

@dataclass
class ReviseCancelOrder(Order):
    rc: RCtype = None # '01': revise, '02': cancel
    all_yn: AllYN = None # 잔량 전부 주문 - Y:전부, N: 일부 
    original_order: Order = None

    def __post_init__(self):
        super().__post_init__()  # need to call explicitly 
        if self.original_order is None: 
            log_raise(f"Check revise-cancel original order ---")

    # revise is cancel + re-order
    # new order_no is assigned both for revise and cancel
    # command rule/sequence: ----------------------
    # - check order_no 
    # - check revise or cancel
    # - check all or partial 
    # - if all and revise:
    # -     check ord_dvsn (market or limit etc)
    # -     check price (quantity can be any, at least "0" required)
    # - if all and cancel:
    # -     nothing matters (can be any, at least "0" required)
    # - if partial and revise:
    # -     check ord_dvsn (market or limit etc)
    # -     check price and quantity
    # - if partial and cancel:
    # -     check quantity (price can be any, at least "0" required)
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
            excg_id_dvsn_cd=self.market
        )
        if res.empty:
            log_raise(f'Order {self.order_no} revise-cancel failed ---')
        else: 
            if pd.isna(res.loc[0, ["ODNO", "ORD_TMD", "KRX_FWDG_ORD_ORGNO"]]).any():
                log_raise("Check revise-cancel response ---")
            self.order_no = res.ODNO.iloc[0]
            self.submitted_time = res.ORD_TMD.iloc[0]
            self.org_no = res.KRX_FWDG_ORD_ORGNO.iloc[0]
            self.submitted = True

            if self.rc == RCtype.REVISE:
                optlogger.info(f"Order {self.original_order.order_no}'s revise order {self.order_no} submitted")
            else: # cancel
                optlogger.info(f"Order {self.original_order.order_no}'s {'full' if self.all_yn == AllYN.ALL else 'partial'} cancellation order {self.order_no} submitted")

    def update_rc_specific(self):
        if self.original_order.completed or self.original_order.cancelled: 
            log_raise("Check update_original, as original order is completed or cancelled ---")

        if self.all_yn == AllYN.ALL: 
            self.quantity = self.original_order.quantity - self.original_order.processed
            self.original_order.quantity = self.original_order.processed
            self.original_order.completed = True
        else: 
            self.original_order.quantity = self.original_order.quantity - self.quantity
            if self.original_order.quantity == self.original_order.processed:
                self.original_order.completed = True
            elif self.original_order.quantity < self.original_order.processed:
                log_raise('Check partial order revise-cancel logic ---')
        
        if self.rc == RCtype.CANCEL: 
            self.cancelled = True
                
@dataclass
class OrderList: # submitted order list
    all: list[Order] = field(default_factory=list) 
    _pending_notices: list[TradeNotice] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __str__(self):
        if not self.all:
            return "<no orders>"
        return "\n".join(str(order) for order in self.all)

    async def process_notice(self, notice: TradeNotice):
        # reroute notice to corresponding order
        # (notice content handling logic should reside in Order class)
        # process notice could arrive faster than order submit result - should not use order_no
        async with self._lock:
            order = next((o for o in self.all if o.order_no is not None and o.order_no == notice.oder_no), None)
            if order is not None:
                order.update(notice)
            else:
                self._pending_notices.append(notice)
                # log_raise(f"No order found for notice {notice.oder_no} ---")

    async def try_process_pending(self, order:Order):
        # Retry unmatched notices when new orders get order_no
        async with self._lock:
            to_process = [n for n in self._pending_notices if n.oder_no == order.order_no]
            for notice in to_process:
                order.update(notice)
                self._pending_notices.remove(notice)

    async def submit_orders_and_register(self, trenv, orders:list): # only accepts new orders not submitted.
        if len([o for o in orders if o.submitted]) > 0: log_raise('Orders should not have been submitted ---')
        for order in orders:
            await asyncio.to_thread(order.submit, trenv)
            async with self._lock:
                self.all.append(order)
                await self.try_process_pending(order) # catch notices that are delivered before registration into order list
            await async_sleep(trenv)
    
    async def cancel_all_outstanding(self, trenv):
        # submitted but not accepted oreders: cannot cancel... should try later again... 
        not_accepted_orders = [o for o in self.all if not o.accepted]
        if not_accepted_orders: 
            log_raise('Submitted but not accepted orders exist; should try later again ---')
        to_cancel = [o for o in self.all if not o.completed and not o.cancelled]
        to_cancel_list = []
        for o in to_cancel:
            cancel_order = ReviseCancelOrder(o.code, o.side, o.quantity, o.ord_dvsn, o.price, rc=RCtype.CANCEL, all_yn=AllYN.ALL, original_order=o)
            to_cancel_list.append(cancel_order)
        
        optlogger.info(f'Cancelling all outstanding {len(to_cancel_list)} orders:')
        await self.submit_orders_and_register(trenv, to_cancel_list)


    async def closing_check(self, delay=5): 
        await asyncio.sleep(delay)
        # 1. check if any order not yet submitted or accepted
        not_submitted = [o for o in self.all if not o.submitted]
        not_accepted = [o for o in self.all if not o.accepted]
        if not_submitted:
            log_raise(f"Cannot close: {len(not_submitted)} orders not yet submitted ---")
        if not_accepted:
            log_raise(f"Cannot close: {len(not_submitted)} orders not yet accepted ---")

        # 2. check if any pending notices remain
        if self._pending_notices:
            log_raise(f"Cannot close: {len(self._pending_notices)} unprocessed notices remain ---")
        optlogger.info("[v] closing check successful")
        # #########################################
        # #########################################
        # #########################################
        # MAY SAVE STATUS or .... follow-up
        # #########################################
        # #########################################
        # #########################################

def pd_nan_chker_(casttype, val):
    # values are always str
    # Decimal needs input as str (especially when it is float)
    return None if pd.isna(val) else {"str": str, "int": int, "float": float, "Decimal": Decimal}[casttype](val)

@dataclass
class TradeNotice: # 국내주식 실시간체결통보
    acnt_no: Optional[str] = None # account number
    oder_no: Optional[str] = None # order number
    ooder_no: Optional[str] = None # original order number 
    seln_byov_cls: Optional[str] = None # 01: sell, 02: buy
    rctf_cls: Optional[str] = None # 0:정상, 1:정정, 2:취소
    oder_kind: Optional[ORD_DVSN] = None # 00: limit, 01: market
    oder_cond: Optional[str] = None # 0: None, 1: IOC (Immediate or Cancel), 2: FOK (Fill or Kill)
    code: Optional[str] = None     
    cntg_qty: Optional[int] = None # traded quantity
    cntg_unpr: Optional[Decimal] = None # traded price
    stck_cntg_hour: Optional[str] = None # traded time (HHMMSS)
    rfus_yn: Optional[str] = None # 0: 승인, 1: 거부 
    cntg_yn: Optional[str] = None # 1: 주문, 정정, 취소, 거부, 2: 체결 
    acpt_yn: Optional[str] = None # 1: 주문접수, 2: 확인, 3: 취소(IOC/FOK)
    brnc_no: Optional[str] = None # 지점번호
    oder_qty: Optional[int] = None # total order quantity  
    exg_yn: Optional[str] = None # 1:KRX, 2:NXT, 3:SOR-KRX, 4:SOR-NXT + 실시간체결창 표시여부(Y/N)
    crdt_cls: Optional[str] = None # 신용구분 
    oder_prc: Optional[Decimal] = None # order price    

    def __str__(self):
        return "TradeNotice:" + json.dumps(asdict(self), indent=4, default=str)

    def _set_data(self, res):
        if res.empty:
            log_raise("Empty response in TradeNotice.from_response ---")
        row = res.iloc[0] 
        self.acnt_no        = pd_nan_chker_("str", row["ACNT_NO"])
        self.oder_no        = pd_nan_chker_("str", row["ODER_NO"])
        self.ooder_no       = pd_nan_chker_("str", row["OODER_NO"])
        bs                  = pd_nan_chker_("str", row["SELN_BYOV_CLS"])
        self.seln_byov_cls  = None if bs is None else 'sell' if bs == '01' else 'buy' if bs == '02' else bs
        self.rctf_cls       = pd_nan_chker_("str", row["RCTF_CLS"])
        ok                  = pd_nan_chker_("str", row["ODER_KIND"])
        self.oder_kind      = None if ok is None else ORD_DVSN(ok).name
        self.oder_cond      = pd_nan_chker_("str", row["ODER_COND"])
        self.code           = pd_nan_chker_("str", row["STCK_SHRN_ISCD"])
        self.cntg_qty       = pd_nan_chker_("int", row["CNTG_QTY"])
        self.cntg_unpr      = pd_nan_chker_("Decimal", row["CNTG_UNPR"])
        self.stck_cntg_hour = pd_nan_chker_("str", row["STCK_CNTG_HOUR"])
        self.rfus_yn        = pd_nan_chker_("str", row["RFUS_YN"])
        self.cntg_yn        = pd_nan_chker_("str", row["CNTG_YN"])
        self.acpt_yn        = pd_nan_chker_("str", row["ACPT_YN"])
        self.brnc_no        = pd_nan_chker_("str", row["BRNC_NO"])
        self.oder_qty       = pd_nan_chker_("int", row["ODER_QTY"])
        self.exg_yn         = pd_nan_chker_("str", row["EXG_YN"])
        self.crdt_cls       = pd_nan_chker_("str", row["CRDT_CLS"])
        self.oder_prc       = pd_nan_chker_("Decimal", row["ODER_PRC"]) 

    @classmethod
    def from_response(cls, res):
        obj = cls()
        obj._set_data(res)
        return obj
    

