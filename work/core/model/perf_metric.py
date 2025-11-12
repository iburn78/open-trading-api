from dataclasses import dataclass
from datetime import datetime

@dataclass
class PerformanceMetric:
    # agent managed data
    agent_id: str | None = None
    code: str | None = None

    # initial setup data (set through agent)
    total_allocated_cash: int | None = None # this is pure cash, not including the initial holding
    initial_holding: int | None = None
    avg_price_initial_holding: int | None = None
    bep_price_initial_holding: int | None = None 

    # OrderBook managed data
    # - on buy/sell order amounts not accounted
    # - snapshot
    holding: int | None = None
    avg_price: int | None = None 
    bep_price: int | None = None
    # - history reflected
    principle_cash_used: int | None = None # (purchased - sold) excluding fee and tax: so negative possible (e.g., profit or sold from initial holding)
    total_cost_incurred: int | None = None # cumulative tax and fee
    total_cash_used: int | None = None # principle + total_cost: likewise

    # MarketPrices managed data
    cur_price: int | None = None
    cur_time: datetime | None = None

    # Value에 Cost 반영 원칙: 내가 초래한 Cost만 반영함 
    # - initial holding의 Purchase cost는 미반영
    # - holding의 미래 Selling cost는 추후 반영

    # Cost recognition principle in value: Only costs caused by the agent are recognized
    # - The purchase cost of the initial holding is not included
    # - The future selling cost of the holding is not (yet) included, and to be considered

    # stats for on holdings (snapshot)
    holding_return_rate: float | None = None # before tax and fee
    holding_bep_return_rate: float | None = None # does not account for all cumulative tax / fee
    holding_abs_return: int | None = None # after fee and tax

    # stats for overall performance from initiation
    total_allocated_value: int | None = None 
    current_value: int | None = None 
    abs_return: int | None = None
    cap_return_rate: float | None = None
    cash_portion: float | None = None

    def calc(self):
        self.holding_return_rate = (self.cur_price-self.avg_price)/self.avg_price if self.avg_price > 0 else None 
        self.holding_bep_return_rate = (self.cur_price-self.bep_price)/self.bep_price if self.bep_price > 0 else None
        self.holding_abs_return = (self.cur_price-self.bep_price)*self.holding

        self.total_allocated_value = self.total_allocated_cash + self.initial_holding*self.cur_price
        self.current_value = self.total_allocated_cash - self.total_cash_used + self.holding*self.cur_price
        self.abs_return = self.current_value - self.total_allocated_value
        self.cap_return_rate = self.abs_return/self.total_allocated_value if self.total_allocated_value > 0 else None
        self.cash_portion = (self.total_allocated_cash - self.total_cash_used)/self.current_value if self.current_value > 0 else None
