from __future__ import annotations
from gen_tools import *
from domestic_stock_functions_ws import *
from domestic_stock_functions import *
import json
from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum
import asyncio
from kis_auth import _smartSleep, _demoSleep
from collections import defaultdict

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
    cost: int = 0         # 제비용 (금일 발생????)

    def __str__(self):
        return (
            f"----------------------------------------------------------------\n"
            f"CashBalance: {self.available:,} / T+1: {self.t_1:,} / T+2: {self.t_2:,}\n"
            f"Cost: {self.cost:,}\n"
            f"----------------------------------------------------------------"
        )

@dataclass 
class Holding: # Stock Holding
    name: str
    code: str
    quantity: int
    amount: int # 수량*체결가
    avg_price: float = 0.0  # fee/tax not considered
    bep_cost: int = 0 # cost if gain is 0 after fee/tax
    bep_price: float = 0.0  # fee/tax considered
    market: str = None  # to assign later (for fee calculation), e.g., KOSPI, KOSDAQ... 

    def __str__(self):
        return (
            f"{self.code} / {self.quantity:,} / {self.name}\n"
            f"total amount: {self.amount:,}, avg price: {self.avg_price:,}, bep price: {self.bep_price:,}\n"
        )

# -------------------------------------------------
# -------------------------------------------------
# -------------------------------------------------
# Book keeping, choronological order 
# update cash and account
@dataclass
class TransactionRecord: # 
    record = pd.DataFrame() 
# -------------------------------------------------
# -------------------------------------------------
# -------------------------------------------------


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

        if ptf.empty or acc.empty:
            log_raise("Inquire balance error ---")

        # 예수금 할당
        self.cash = self.cash or CashBalance()
        self.cash.available = int(acc["dnca_tot_amt"].iat[0])
        self.cash.t_1 = int(acc["nxdy_excc_amt"].iat[0])
        self.cash.t_2 = int(acc["prvs_rcdl_excc_amt"].iat[0])
        self.cash.cost = int(acc["thdt_tlex_amt"].iat[0])
        
        # 보유 종목 Sync
        # 있으면 update, 없으면 add
        new_holdings = [] 
        for _, row in ptf.iterrows():  # DataFrame에서 row 반복
            code = row.pdno
            holding = next((h for h in self.holdings if h.code == code), None)
            quantity = int(row.hldg_qty) 
            amount = int(row.pchs_amt)
            avg_price = amount/quantity
            market = get_market(code)
            bep_cost, bep_price = CostCalculator.bep_cost_calculate(quantity, avg_price, market, trenv.my_svr)
            if holding:
                holding.quantity = quantity
                holding.amount = amount
                holding.avg_price = avg_price
                holding.bep_cost = bep_cost
                holding.bep_price = bep_price
            else: 
                holding = Holding(
                        name = row.prdt_name, 
                        code = row.pdno,
                        quantity = quantity,
                        amount = amount,
                        avg_price = avg_price,
                        bep_cost = bep_cost, 
                        bep_price = bep_price, 
                        market = market,
                )
            new_holdings.append(holding)
        self.holdings = new_holdings
        return self

class ORD_DVSN(str, Enum):
    LIMIT = '00'
    MARKET = '01'

class CostCalculator:
    # All data: percent
    # 한투수수료 (유관기관수수료 포함)
    FEE = {
        'KRX': 0.0140527, 
        'NXT': {
            'maker': 0.0130527, 
            'taker': 0.0130527, 
            'settle': 0.0130527, 
        } 
    }

    # 유관기관수수료
    MIN_FEE = {
        'KRX': 0.0036396, 
        'NXT': {
            'maker': 0.0031833, 
            'taker': 0.0031833, 
            'settle': 0.0031833, 
        } 
    }  

    # Percent
    TAX = {  
        # On-exchange (장내)
        'KOSPI': {
            'TransactionTax': 0, 
            'RuralDevTax': 0.15,
        },
        'KOSDAQ': {
            'TransactionTax': 0.15, 
            'RuralDevTax': 0,
        },
        # OTC (장외) including 비상장
        # Below is not allowed in this code yet... 
        'OTC': {
            'TransactionTax': 0.35, 
            'RuralDevTax': 0,
        }
        # KONEX, K-OTC ... 
    }

    # Rounding Rule 
    RD_rule = { 
        # 0: # 1원 미만 rounding
        # -1: # 10원 미만 rounding 
        'FEE': -1, 
        'MIN_FEE': 0, 
        'TAX': 0, 
    }

    @classmethod
    def get_fee_table(cls, account):
        if account == "prod":  # 국내주식수수료 면제 (유관기관수수료만 부담)
            return cls.MIN_FEE, cls.RD_rule['MIN_FEE'], cls.RD_rule['TAX']
        elif account == "auto":
            return cls.FEE, cls.RD_rule['FEE'], cls.RD_rule['TAX']
        elif account == "vps":
            return cls.FEE, cls.RD_rule['FEE'], cls.RD_rule['TAX']
        else:
            log_raise("Check ---")

    # 각각의 Order가 중간 체결 될때는 각 Fee 및 Tax를 float로 합산하고, 매 순간 Excel Rounding (int) 진행함
    # 완료되거나 중단될 경우, rounded 값 사용
    # 보수적 접근으로 실제 증권사 Logic을 정확히 알 수 없으므로 근사치임 (체결간 시간 간격등 추가 Rule이 있을 수 있음)
    @classmethod
    def calculate(cls, side, quantity, price, market, svr, exchange=None, maker_taker="taker"): # default to be conservative
        if exchange is None: 
            exchange = "KRX"  # default to be conservative

        fee_table, fee_rd_rule, tax_rd_rule = cls.get_fee_table(svr)
        if exchange == "KRX":
            fee = fee_table[exchange]
        else:
            fee = fee_table[exchange][maker_taker]

        if side == 'buy':
            tax = 0
        else: 
            tax = cls.TAX[market]['TransactionTax'] + cls.TAX[market]['RuralDevTax']
        
        fee_float = quantity*price*fee/100
        tax_float = quantity*price*tax/100

        return fee_float, tax_float, fee_rd_rule, tax_rd_rule

    # 보수적으로 보았을때에 매각시 수익이 0가 되는 total cost의 계산
    # 일단 전체 보유 Amount로만 추정... 
    # 하나의 order quantity에 매수/매도가 여러번 있을수 있다보니, rounding 에러가 발생, 오차 발생 가능
    @classmethod
    def bep_cost_calculate(cls, quantity, avg_price, market, svr): 
        exchange = "KRX"  # default to be conservative
        fee_table, fee_rd_rule, tax_rd_rule = cls.get_fee_table(svr)
        fee_percent = fee_table[exchange]
        tax_percent = cls.TAX[market]['TransactionTax'] + cls.TAX[market]['RuralDevTax']

        bep_rate = (2*fee_percent/100+tax_percent/100)/(1-(fee_percent/100+tax_percent/100))
        bep_cost = excel_round_int(quantity*avg_price*bep_rate)
        bep_price = (quantity*avg_price + bep_cost)/quantity

        return bep_cost, bep_price

@dataclass
class Order:
    code: str
    side: str # 'buy' or 'sell'
    quantity: int
    ord_dvsn: ORD_DVSN # market or limit
    price: int
    amount: int = 0 # total purchased cumulative amount (sum of quantity x price)
    avg_price: float = 0.0
    bep_cost: int = 0
    bep_price: float = 0.0
    market: str = None # KOSPI, KOSDAQ, etc
    exchange: str = "SOR" # Smart Order Routing - KRX, NXT, etc.

    org_no: Optional[str] = None
    order_no: Optional[str] = None
    submitted_time: Optional[str] = None

    submitted: bool = False
    accepted: bool = False
    completed: bool = False
    cancelled: bool = False 

    # as the order is fullfilled, cost_occured should refect exact cost up to that moment
    # round only done when the order is fully fullfilled
    processed: int = 0
    fee_occured: float = 0.0
    tax_occured: float = 0.0
    fee_rounded: int = 0   # if completed or cancelled, this is final 
    tax_rounded: int = 0   # if completed or cancelled, this is final 

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

        self.market = get_market(self.code)

        if self.market not in ['KOSPI', 'KOSDAQ']:
            log_raise("Check the market of the stock: KOSPI or KOSDAQ")
        
    
    def __str__(self):
        return "Order:" + json.dumps(asdict(self), indent=4, default=str)

    def submit(self, trenv):
        if self.completed or self.cancelled:
            log_raise('A completed or cancelled order submitted ---')

        ord_qty = str(self.quantity)
        ord_unpr = str(self.price)
        res = order_cash(env_dv=trenv.env_dv, ord_dv=self.side, cano=trenv.my_acct, acnt_prdt_cd=trenv.my_prod, pdno=self.code, ord_dvsn=self.ord_dvsn, ord_qty=ord_qty, ord_unpr=ord_unpr, excg_id_dvsn_cd=self.exchange)

        if res.empty:
            log_raise('Order submission failed ---')
        else: 
            if pd.isna(res.loc[0, ["ODNO", "ORD_TMD", "KRX_FWDG_ORD_ORGNO"]]).any():
                log_raise("Check submission response ---")
            self.order_no = res.ODNO.iloc[0]
            self.submitted_time = res.ORD_TMD.iloc[0]
            self.org_no = res.KRX_FWDG_ORD_ORGNO.iloc[0]
            self.submitted = True
            optlog.info(f"Order {self.order_no} submitted")
    
    def update(self, notice: TradeNotice, trenv):
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
                self.amount += notice.cntg_qty*notice.cntg_unpr
                self.avg_price = self.amount/self.processed

                fee_float, tax_float, fee_rd, tax_rd = CostCalculator.calculate(
                    side = notice.seln_byov_cls,
                    quantity = notice.cntg_qty, 
                    price = notice.cntg_unpr,
                    market = self.market, 
                    svr = trenv.my_svr,
                    exchange = notice.exchange
                )
                self.fee_occured += fee_float
                self.tax_occured += tax_float
                self.fee_rounded = excel_round_int(self.fee_occured, fee_rd)
                self.tax_rounded = excel_round_int(self.tax_occured, tax_rd)

                self.bep_cost, self.bep_price = CostCalculator.bep_cost_calculate(self.processed, self.avg_price, self.market, trenv.my_svr)

                if self.processed > self.quantity:
                    log_raise('Check order processed quantity ---')
                if self.processed == self.quantity:
                    self.completed = True
                    optlog.info(f"Order {self.order_no} completed")
            else: 
                log_raise("Check logic ---")

    def update_rc_specific(self):
        # to be overrided by ReviseCancelOrder
        # no need to define any here
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
            excg_id_dvsn_cd=self.exchange
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
                optlog.info(f"Order {self.original_order.order_no}'s revise order {self.order_no} submitted")
            else: # cancel
                optlog.info(f"Order {self.original_order.order_no}'s {'full' if self.all_yn == AllYN.ALL else 'partial'} cancellation order {self.order_no} submitted")

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
    # If order size grows, consider making all as a dict for faster lookup O(1)
    # @dataclass need to define default values with care (e.g., field(...))
    all: list[Order] = field(default_factory=list) 

    # defaultdict(list) is useful when there is 1 to N relationship, e.g., multiple notices to one order
    # simple access to defaultdict would generate key inside with empty list - handle with care
    _pending_notices_by_order: dict[str, list[TradeNotice]] = field(
        default_factory=lambda: defaultdict(list)
    )
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __str__(self):
        if not self.all:
            return "<no orders>"
        return "\n".join(str(order) for order in self.all)

    async def process_notice(self, notice: TradeNotice, trenv):
        # reroute notice to corresponding order
        # notice content handling logic should reside in Order class
        # process notice could arrive faster than order submit result - should not use order_no
        async with self._lock:
            order = next((o for o in self.all if o.order_no is not None and o.order_no == notice.oder_no), None)
            if order is not None:
                order.update(notice, trenv)
            else:
                self._pending_notices_by_order[notice.oder_no].append(notice)

    async def try_process_pending(self, order:Order, trenv):
        # Retry unmatched notices when new orders get order_no
        async with self._lock:
            to_process = self._pending_notices_by_order.get(order.order_no, [])
            for notice in to_process:
                order.update(notice, trenv)
            self._pending_notices_by_order.pop(order.order_no, None)

    async def submit_orders_and_register(self, orders:list, trenv): # only accepts new orders not submitted.
        if len([o for o in orders if o.submitted]) > 0: log_raise('Orders should not have been submitted ---')
        for order in orders:
            await asyncio.to_thread(order.submit, trenv)
            async with self._lock:
                self.all.append(order)
            await self.try_process_pending(order, trenv) # catch notices that are delivered before registration into order list
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
        
        optlog.info(f'Cancelling all outstanding {len(to_cancel_list)} orders:')
        await self.submit_orders_and_register(to_cancel_list, trenv)

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
        if self._pending_notices_by_order:
            l = len(self._pending_notices_by_order)
            count = sum(len(v) for v in self._pending_notices_by_order.values())
            log_raise(f"Cannot close: pending notices dict has {l} items, with total {count} pending notices")

        optlog.info("[v] closing check successful")
        # #########################################
        # MAY SAVE STATUS or .... follow-up
        # #########################################

def pd_nan_chker_(casttype, val):
    # values are always str
    return None if pd.isna(val) else {"str": str, "int": int, "float": float}[casttype](val)

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
    cntg_unpr: Optional[int] = None # traded price
    stck_cntg_hour: Optional[str] = None # traded time (HHMMSS)
    rfus_yn: Optional[str] = None # 0: 승인, 1: 거부 
    cntg_yn: Optional[str] = None # 1: 주문, 정정, 취소, 거부, 2: 체결 
    acpt_yn: Optional[str] = None # 1: 주문접수, 2: 확인, 3: 취소(IOC/FOK)
    brnc_no: Optional[str] = None # 지점번호
    oder_qty: Optional[int] = None # total order quantity  
    exg_yn: Optional[str] = None # 1:KRX, 2:NXT, 3:SOR-KRX, 4:SOR-NXT + 실시간체결창 표시여부(Y/N)
    crdt_cls: Optional[str] = None # 신용구분 
    oder_prc: Optional[int] = None # order price    

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
        self.cntg_unpr      = pd_nan_chker_("int", row["CNTG_UNPR"])
        self.stck_cntg_hour = pd_nan_chker_("str", row["STCK_CNTG_HOUR"])
        self.rfus_yn        = pd_nan_chker_("str", row["RFUS_YN"])
        self.cntg_yn        = pd_nan_chker_("str", row["CNTG_YN"])
        self.acpt_yn        = pd_nan_chker_("str", row["ACPT_YN"])
        self.brnc_no        = pd_nan_chker_("str", row["BRNC_NO"])
        self.oder_qty       = pd_nan_chker_("int", row["ODER_QTY"])
        self.exg_yn         = pd_nan_chker_("str", row["EXG_YN"])
        self.exchange       = None if self.exg_yn is None else 'KRX' if self.exg_yn[0] in ['1', '3'] else 'NXT' if self.exg_yn[0] in ['2', '4'] else None
        self.crdt_cls       = pd_nan_chker_("str", row["CRDT_CLS"])
        self.oder_prc       = pd_nan_chker_("int", row["ODER_PRC"]) 

    @classmethod
    def from_response(cls, res):
        obj = cls()
        obj._set_data(res)
        return obj
    

