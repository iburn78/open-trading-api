from dataclasses import dataclass, field

from .cost import CostCalculator
from common.optlog import log_raise
from common.tools import get_market
from kis.domestic_stock_functions import inquire_balance

@dataclass
class CashBalance:
    available: int = 0      # 현재 예수금 (T+0)
    t_1: int = 0            # T+1 예수금
    t_2: int = 0            # T+2 예수금
    cost: int = 0         # 제비용 (금일 발생)

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