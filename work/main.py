import sys
import logging
import kis_auth as ka
from domestic_stock_functions_ws import *
from domestic_stock_functions import *
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd
# ---------------------------------
# Key parameters
# ---------------------------------

svr_to_use = 'vps' # prod, auto, vps

# ---------------------------------
# 인증 and Set-up
# ---------------------------------
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ka.auth(svr=svr_to_use)  # renew_token=True
ka.auth_ws(svr=svr_to_use)
trenv = ka.getTREnv()

ENV_DV = 'demo' if svr_to_use == "vps" else 'real'

# ---------------------------------
# Data structure
# ---------------------------------

@dataclass 
class Holding:  # Stock Holding
    name: str
    code: str
    quantity: int
    amount: int
    avg_price: float = 0.0   # 기본값 추가 (없으면 생성시 필요)

    def __str__(self):
        return (
            f"  name: {self.name}\n"
            f"  code: {self.code}\n"
            f"  quantity: {self.quantity}"
            f"  amount: {self.amount}"
            f"  avg_price: {self.avg_price}"
        )

@dataclass
class CashBalance:
    available: int = 0      # 현재 예수금 (T+0)
    t_1: int = 0            # T+1 예수금
    t_2: int = 0            # T+2 예수금

    def __str__(self):
        return (
            f"CashBalance:\n"
            f"  Available (T+0): {self.available}\n"
            f"  T+1: {self.t_1}\n"
            f"  T+2: {self.t_2}"
        )

@dataclass
class Account:
    holdings: list[Holding] = field(default_factory=list)
    cash: CashBalance = None

    def __post_init__(self): 
        self.acc_load()

    def acc_load(self):
        ptf, acc = inquire_balance(
            cano=trenv.my_acct,
            env_dv=ENV_DV,
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

    def status_check(self):
        try:
            res = inquire_psbl_rvsecncl(cano=trenv.my_acct, acnt_prdt_cd=trenv.my_prod, inqr_dvsn_1="1", inqr_dvsn_2="0")
            print(res)
        except Exception as e:
            print("Order status_check didn't work.")
            raise Exception(e)

@dataclass
class Order:
    code: str
    side: str
    quantity: int
    mode: str
    price: Optional[int] = None
    market: str = "SOR" # Smart Order Routing

    submitted: bool = False

    org_no: str = ""
    order_no: str = ""
    submitted_time: str = ""

    processed: str = ""
    completed: bool = False
    cancelled: bool = False


    def __post_init__(self):
        if self.side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        if self.mode not in ("market", "limit"):
            raise ValueError("mode must be 'market' or 'limit'")

        if self.mode == "limit" and self.price is None:
            raise ValueError("Limit orders require a price")
        if self.mode == "market" and self.price is not None:
            raise ValueError("Market orders should not have a price")
    
    def submit(self):
        if self.mode == "limit": 
            ord_dvsn = "00"
        elif self.mode == "market":
            ord_dvsn = "01"
        else: 
            ord_dvsn = "##"  # there are many other options

        try:
            res = order_cash(env_dv=ENV_DV, ord_dv=self.side, cano=trenv.my_acct, acnt_prdt_cd=trenv.my_prod, pdno=self.code, ord_dvsn=ord_dvsn, ord_qty=str(self.quantity), ord_unpr=str(self.price), excg_id_dvsn_cd=self.market)
        except Exception as e:
            print("Order didn't submitted.")
            raise Exception(e)

        self.submitted = True
        if res.empty :
            print('Fail')
            print(res)
        else: 
            print('Success')
            self.org_no = res.KRX_FWDG_ORD_ORGNO.iloc[0]
            self.order_no = res.ODNO.iloc[0]
            self.submitted_time = res.ORD_TMD.iloc[0]
            print(res)


class TradingModel:
    pass

# ---------------------------------
# Key variables
# ---------------------------------

the_account = Account()
print(the_account.cash)
print(the_account.holdings)

time.sleep(0.5)

# result = inquire_ccnl(env_dv=ENV_DV, fid_cond_mrkt_div_code="J", fid_input_iscd="000660")
# result = inquire_asking_price_exp_ccn(env_dv=ENV_DV, fid_cond_mrkt_div_code="J", fid_input_iscd="000660")
# print(result[0].T.to_string())
# print(result[1].T.to_string())

# code = '018000'
# quantity = 10
# price = 1210
# order = Order(code, 'buy', quantity, 'limit', price)
# order.submit()

# -----------------------------------
# sys.exit() 
# -----------------------------------

the_account.acc_load()
print(the_account.cash)
print(the_account.holdings)

# sell_price = 269000
# buy_price = 268500

# 웹소켓 선언
kws = ka.KISWebSocket(api_url="/tryitout")

# subscribes
# kws.subscribe(request=asking_price_total, data=["316140", code])
kws.subscribe(request=ccnl_notice, data=[trenv.my_htsid])

def on_result(ws, tr_id, result, data_info):

    print(result)

    # print('BID:', result['BIDP1'].iloc[0])
    # if result['MKSC_SHRN_ISCD'].iloc[0] == code and int(result['BIDP1'].iloc[0]) >= sell_price: 
    #     print("SELL -------------------------------------------------") 
    #     result = order_cash(env_dv=ENV_DV, ord_dv="sell", cano=trenv.my_acct, acnt_prdt_cd=trenv.my_prod, pdno=code,
    #                         ord_dvsn="00", ord_qty="1", ord_unpr=str(sell_price), excg_id_dvsn_cd="SOR")

    # print('ASK:', result['ASKP1'].iloc[0])
    # if result['MKSC_SHRN_ISCD'].iloc[0] == code and int(result['ASKP1'].iloc[0]) <= buy_price: 
    #     print("BUY **************************************************") 
    #     result = order_cash(env_dv=ENV_DV, ord_dv="buy", cano=trenv.my_acct, acnt_prdt_cd=trenv.my_prod, pdno=code,
    #                         ord_dvsn="00", ord_qty="1", ord_unpr=str(buy_price), excg_id_dvsn_cd="SOR")
    #     time.sleep(0.5)


kws.start(on_result=on_result)

