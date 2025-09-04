from __future__ import annotations
from domestic_stock_functions_ws import *
from domestic_stock_functions import *
import json
from dataclasses import dataclass, field, asdict
from typing import Optional
from decimal import Decimal

tr_id_dict = {
    'TradeNotice': {'demo': 'H0STCNI9', 'real': 'H0STCNI0',},
}

rev_tr_id_dict = {
    (env, tr): name
    for name, env_dict in tr_id_dict.items()
    for env, tr in env_dict.items()
}

def get_tr(trenv, tr_id, rev_tr_id_dict = rev_tr_id_dict):
    return rev_tr_id_dict.get((trenv.env_dv, tr_id))


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
    avg_price: float = 0.0   # 기본값 추가 (없으면 생성시 필요)

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
        print(self.cash)
        for h in self.holdings:
            print(h)
        return ""

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
        

@dataclass
class Order:
    code: str
    side: str
    quantity: int
    mode: str
    price: Optional[int] = None
    market: str = "SOR" # Smart Order Routing

    org_no: Optional[str] = None
    order_no: Optional[str] = None
    submitted_time: Optional[str] = None

    processed: int = 0
    completed: bool = False
    cancelled: bool = False

    def __post_init__(self):
        # validity check
        if self.side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        if self.mode not in ("market", "limit"):
            raise ValueError("mode must be 'market' or 'limit'")

        if self.mode == "limit" and self.price is None:
            raise ValueError("Limit orders require a price")
        if self.mode == "market" and self.price is not None:
            raise ValueError("Market orders should not have a price")
    
    def __str__(self):
        return "Order:" + json.dumps(asdict(self), indent=4, default=str)
    
    def submit(self, trenv):
        if self.completed or self.cancelled:
            raise Exception('A completed or cancelled order submitted')

        if self.mode == "limit": 
            ord_dvsn = "00"
        elif self.mode == "market":
            ord_dvsn = "01"
        else: 
            ord_dvsn = "##"  # there are many other options defined

        ord_qty = str(self.quantity)
        ord_unpr = "0" if (self.price is None or self.price == "") else str(self.price)
        res = order_cash(env_dv=trenv.env_dv, ord_dv=self.side, cano=trenv.my_acct, acnt_prdt_cd=trenv.my_prod, pdno=self.code, ord_dvsn=ord_dvsn, ord_qty=ord_qty, ord_unpr=ord_unpr, excg_id_dvsn_cd=self.market)

        if res.empty:
            raise Exception('Order submission failed')
        else: 
            self.order_no = res.ODNO.iloc[0]
            if self.order_no is None or len(self.order_no.strip()) > 5: raise Exception("Check submitted order_no ---")
            self.submitted_time = res.ORD_TMD.iloc[0]
            if self.submitted_time is None or len(self.submitted_time.strip()) > 5: raise Exception("Check submitted order_no ---")
            self.org_no = res.KRX_FWDG_ORD_ORGNO.iloc[0]
            print(f"Order {self.order_no} submitted")
    
    def update(self, notice: TradeNotice):
        if self.order_no != notice.oder_no: # checking order_no (or double-checking)
            return
        if self.completed or self.cancelled: 
            return 
        if notice.rfus_yn != "0": # 승인
            raise Exception(f"Order {self.order_no} refused ---")

        # BELOW CASE CHECK REQUIRED.... 정정 또는 취소를 해도, 주문접수 및 확인이 있을 있음
        # 정정은 안한다해도, 취소는 필요함
        if notice.cntg_yn == "1": # 주문, 정정, 취소, 거부
            if notice.acpt_yn == "1": # 주문접수
                # 정정(?) - not yet implemented
                # 취소(?) - not yet implemented
                pass
            elif notice.acpt_yn == "2": # 확인
                # 정정(?) - not yet implemented
                # 취소(?) - not yet implemented
                raise Exception("Check logic ---")
            else: # notice.acpt_yn == "3": # 취소(FOK/IOC only?)
                print(f"Order {self.order_no} cancelled")
                self.cancelled = True
                pass

        else: # notice.cntg_yn == "2": # 체결
            if notice.acpt_yn == "2": # 확인
                self.processed += notice.cntg_qty
                if self.processed > self.quantity:
                    raise Exception('Check order processed quantity ---')
                if self.processed == self.quantity:
                    self.completed = True
                    print(f"Order {self.order_no} completed")
            else: 
                raise Exception("Check logic ---")


@dataclass
class OrderList:
    all: list[Order] = field(default_factory=list) 

    def register(self, order):
        if order.submitted_time is None: 
            self.all.append(order)
        else:
            raise Exception('Register only new orders before submission...')

    def process_notice(self, notice: TradeNotice):
        # reroute notice to corresponding order
        # notice content handling logic should reside in Order class
        order = next((o for o in self.all if o.order_no is not None and o.order_no == notice.oder_no), None)
        if order is None:
            raise LookupError(f"No order found for notice {notice.oder_no}")
        order.update(notice)
    
    def get_new_orders(self):
        return [o for o in self.all if o.submitted_time is None]


@dataclass
class TradeNotice: # 국내주식 실시간체결통보
    acnt_no: Optional[str] = None # account number
    oder_no: Optional[str] = None # order number
    ooder_no: Optional[str] = None # original order number 
    seln_byov_cls: Optional[str] = None # 01: sell, 02: buy
    rctf_cls: Optional[str] = None # 0:정상, 1:정정, 2:취소
    oder_kind: Optional[str] = None # 00: limit, 01: market
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

    def set_data(self, res):
        row = res.iloc[0] 
        self.acnt_no        = row["ACNT_NO"]
        self.oder_no        = row["ODER_NO"]
        self.ooder_no       = row["OODER_NO"]
        self.seln_byov_cls  = row["SELN_BYOV_CLS"]
        self.rctf_cls       = row["RCTF_CLS"]
        self.oder_kind      = row["ODER_KIND"]
        self.oder_cond      = row["ODER_COND"]
        self.code           = row["STCK_SHRN_ISCD"]
        self.cntg_qty       = int(row["CNTG_QTY"])
        self.cntg_unpr      = Decimal(row["CNTG_UNPR"]) if row["CNTG_UNPR"] else None
        self.stck_cntg_hour = row["STCK_CNTG_HOUR"]
        self.rfus_yn        = row["RFUS_YN"]
        self.cntg_yn        = row["CNTG_YN"]
        self.acpt_yn        = row["ACPT_YN"]
        self.brnc_no        = row["BRNC_NO"]
        self.oder_qty       = int(row["ODER_QTY"])
        self.exg_yn         = row["EXG_YN"]
        self.crdt_cls       = row["CRDT_CLS"]
        self.oder_prc       = Decimal(row["ODER_PRC"]) if row["ODER_PRC"] else None

    @classmethod
    def from_response(cls, res):
        obj = cls()
        obj.set_data(res)
        return obj
    

class TradeModel:
    pass
