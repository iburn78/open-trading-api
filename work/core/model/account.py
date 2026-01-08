from dataclasses import dataclass, field

from ..base.settings import Service
from ..base.logger import LogSetup
from ..kis.kis_connect import KIS_Connector
from ..kis.kis_tools import KIS_Functions

@dataclass
class CashBalance:
    cash_t0: int = 0      # 현재 예수금 (T+0)
    cash_t1: int = 0      # T+1 예수금
    cash_t2: int = 0      # T+2 예수금
    cost: int = 0         # 금일 제비용 금액

    def __str__(self):
        return (
            f"CashBalance: {self.cash_t0:,} / T+1: {self.cash_t1:,} / T+2: {self.cash_t2:,} / cost: {self.cost:,}"
        )

@dataclass 
class Holding: # Stock Holding / data is filled from the API server (e.g., actual)
    name: str
    code: str
    quantity: int
    amount: int # 수량x체결가

    def __str__(self):
        return (
            f"({self.code}) {self.name}: Q {self.quantity:,}, Amt {self.amount:,}"
        )

@dataclass
class Account:
    holdings: dict["code":str, Holding] = field(default_factory=dict)
    cash: CashBalance = None

    def __post_init__(self):
        self.logger = LogSetup().logger 
        self.kc = KIS_Connector(Service.DEMO, self.logger, None)
        self.kf = KIS_Functions(self.kc)

    def __str__(self):
        parts = [str(self.cash)] if self.cash else []
        parts.extend(str(h) for c, h in self.holdings.items())
        return "\n".join(parts)

    async def acc_load(self):
        ptf, acc = await self.kf.inquire_balance()

        if ptf.empty or acc.empty:
            # failed to load account
            return

        # 예수금 update
        self.cash = self.cash or CashBalance()
        self.cash.cash_t0 = int(acc["dnca_tot_amt"].iat[0])
        self.cash.cash_t1 = int(acc["nxdy_excc_amt"].iat[0])
        self.cash.cash_t2 = int(acc["prvs_rcdl_excc_amt"].iat[0])
        self.cash.cost = int(acc["thdt_tlex_amt"].iat[0])
        
        # 보유 종목 
        # 있으면 update, 없으면 add
        new_holdings = {} 
        for _, row in ptf.iterrows():  
            code = row.pdno
            holding = self.holdings.get(code)
            quantity = int(row.hldg_qty) 
            amount = int(row.pchs_amt)
            if holding:
                holding.quantity = quantity
                holding.amount = amount
            else: 
                holding = Holding(
                        name = row.prdt_name, 
                        code = row.pdno,
                        quantity = quantity,
                        amount = amount,
                )
            new_holdings[code] = holding
        self.holdings = new_holdings

import asyncio
if __name__ == "__main__":
    the_account = Account()
    asyncio.run(the_account.acc_load())
    print(the_account)