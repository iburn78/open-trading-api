from dataclasses import dataclass
from datetime import datetime

@dataclass
class PerformanceMetric:
    # agent managed data
    agent_id: str | None = None
    code: str | None = None

    # initial setup data
    total_allocated_cash: int = 0
    initial_holding: int = 0
    bep_price_initial_holding: int = 0 # bep of initial holding: to be conservative, it includes of cost of selling.

    # OrderBook managed data
    holding: int = 0
    avg_price: int = 0
    bep_price: int = 0
    total_cash_used: int = 0

    # MarketPrices managed data
    cur_price: int = 0
    cur_time: datetime | None = None

    # calc
    cur_return: float = 0.0 # before tax and fee
    bep_return: float = 0.0
    abs_gain: int = 0 # after fee and tax
    cap_return: float = 0.0 # after fee and tax

    def calc(self):
        self.cur_return = (self.cur_price-self.avg_price)/self.avg_price if self.avg_price > 0 else 0
        self.bep_return = (self.cur_price-self.bep_price)/self.bep_price if self.bep_price > 0 else 0
        self.abs_gain = (self.cur_price-self.bep_price)*self.holding
        self.cap_return = self.abs_gain/self.total_cash_used if self.total_cash_used > 0 else 0
