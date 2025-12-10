from dataclasses import dataclass

from .order_book import OrderBook
from .price import MarketPrices
from .cost import CostCalculator
from ..common.setup import TradePrinciples
from ..common.optlog import optlog, LOG_INDENT
from ..common.tools import excel_round
from ..model.dashboard import DashBoard

@dataclass
class PerformanceMetric:
    # -------------------------------------------------------
    # agent managed data: set by agent
    # -------------------------------------------------------
    agent_id: str | None = None
    code: str | None = None
    listed_market: str | None = None
    order_book: OrderBook | None = None
    market_prices: MarketPrices | None = None
    # - set after agent registration
    my_svr: str | None = None
    dashboard: DashBoard | None = None

    # -------------------------------------------------------
    # initial value setup: set through agent
    # -------------------------------------------------------
    init_cash_allocated: int | None = None # this is pure cash, not including the initial holding
    init_holding_qty: int | None = None
    init_avg_price: float | None = None 

    # -------------------------------------------------------
    # OrderBook managed data: set by the 'setter' below
    # -------------------------------------------------------
    orderbook_holding_qty: int | None = None # quantity, can not be negative 
    orderbook_holding_avg_price: float | None = None 
    initial_holding_sold_qty: int | None = None 
    # - 주문 상태
    pending_buy_qty: int | None = None  # quantity (미체결 매수 주문 수량: limit and market quantity)
    pending_limit_buy_amt: int | None = None # amount (지정가 주문 금액)
    pending_market_buy_qty: int | None = None # quantity (시장가 주문 수량)
    pending_sell_qty: int | None = None # quantity (미체결 매도 주문 수량)
    # - 체결된 사항
    cumul_buy_qty: int | None = None # quantity (누적 매수량)
    cumul_sell_qty: int | None = None # quantity (누적 매도량)

    net_cash_used: int | None = None # negative: profit, positive: loss or on stock holding (누적 순매수 금액)
    cumul_cost: int | None = None # cumulative tax and fee (누적 발생 비용)
    total_cash_used: int | None = None # net_cash_used + cumul_cost (총 소요 현금)

    # -------------------------------------------------------
    # MarketPrices managed data: set by the 'setter' below
    # -------------------------------------------------------
    cur_price: int | None = None 

    # -----------------------------------------------------------------------------
    # stats, values and returns: set by update()
    # - cost 반영 원칙: 내가 초래한 cost만 반영함 
    #   * initial_holding의 purchase cost는 미반영
    #   * cash에 holding의 미래 selling cost는 미반영 (selling price dependent)
    #   * BEP 계산에는 매도 비용까지 반영: 보유 주식에 대해서만 감안, 즉 평균가의 특정 비율
    # -----------------------------------------------------------------------------
    cash_on_hold: int | None = None # order margin considered (현재 매수 주문으로 Account 에서 묶인 현금)
    cash_available: int | None = None # init_allocated - total_cash_used - cash_on_hold (매수 주문에 사용 가능한 현금)
    holding_qty: int | None = None # total holding (보유 주식 수)

    max_market_buy_amt: int | None = None # (시장가 매수 가능 금액)
    max_limit_buy_amt: int | None = None # (지정가 매수 가능 금액)
    max_sell_qty: int | None = None # (매도 가능 수량)

    holding_value: int | None = None # (init_holding_qty + orderbook_holding_qty) x cur_price (보유 주식 가치: 현재가 반영, 비용 미반영)
    cash_balance: int | None = None # allocated - total_used (보유 현금, T+2 예수금)
    
    avg_price: float | None = None # (보유 주식 평단가)
    bep_price: float | None = None # (보유 주식 BEP 평단가: 보유 주식 관련 Cost만 감안)

    return_rate: float | None = None # before tax and fee (보유 주식의 현재가 대비 수익률)
    bep_return_rate: float | None = None # only account cost for total holding (보유 주식의 현재가 대비 BEP 수익률)

    init_value: int | None = None # (시작가치)
    cur_value: int | None = None # after cumulative cost since initialization (보유주식 가치 + 보유 현금: 시작 시점부터 해당 시점까지 비용 감안됨)
    unrealized_gain: int | None = None # after cumulative cost since initialization (시작시점부터의 평가 이익)
    cap_return_rate: float | None = None # after cumulative cost since initialization (시작가치 대비, 시작시점부터의 평가 이익률)

    def __str__(self):
        try: 
            text = (
                f"[PM] dashboard ({self.code}): {self.cur_price:>5,d}, agent {self.agent_id}\n"
                f"{LOG_INDENT}----------------------------------------------------\n"
                f"{LOG_INDENT}holding / init / orderbook   : {self.holding_qty:,d} / {self.init_holding_qty:,d} / {self.orderbook_holding_qty:,d}\n"
                f"{LOG_INDENT}pending b (lmt a, mkt q) / s : {self.pending_buy_qty:,d} ({self.pending_limit_buy_amt:,d}, {self.pending_market_buy_qty:,d}) / {self.pending_sell_qty:,d}\n"
                f"{LOG_INDENT}cumul buy / sell             : {self.cumul_buy_qty:>,d} / {self.cumul_sell_qty:>,d}\n"
                f"{LOG_INDENT}----------------------------------------------------\n"
                f"{LOG_INDENT}holding / init / ordbook avp : {self.avg_price:,.0f} / {self.init_avg_price:,.0f} / {self.orderbook_holding_avg_price:,.0f}\n"
                f"{LOG_INDENT}bep price                    : {self.bep_price:,.0f}\n"
                f"{LOG_INDENT}----------------------------------------------------\n"
                f"{LOG_INDENT}cash avail / init / on hold  : {self.cash_available:,d} / {self.init_cash_allocated:,d} / {self.cash_on_hold:,d}\n"
                f"{LOG_INDENT}cumul cost / total used      : {self.cumul_cost:,d} / {self.total_cash_used:,d}\n"
                f"{LOG_INDENT}----------------------------------------------------\n"
                f"{LOG_INDENT}return rate / bep return rate: {self.return_rate*100:.2f}% / {self.bep_return_rate*100:.2f}%\n"
                f"{LOG_INDENT}cur value / init / gain      : {self.cur_value:,d} / {self.init_value:,d} / {self.unrealized_gain:,d}\n"
                f"{LOG_INDENT}cap return rate              : {self.cap_return_rate*100:.2f}%\n"
                f"{LOG_INDENT}----------------------------------------------------"
            )
        except:
            text = f"[PM] not initialized: ({self.code}), agent {self.agent_id}"
        finally: 
            return text
    
    # this lets Strategy to use data from pm only
    # should reflect changes in the variables defined above
    def _feed_in_ob_managed_data(self, pending_orders=False):
        # get data from order_book
        self.pending_buy_qty = self.order_book.pending_buy_qty
        self.pending_limit_buy_amt = self.order_book.pending_limit_buy_amt
        self.pending_market_buy_qty = self.order_book.pending_market_buy_qty
        self.pending_sell_qty = self.order_book.pending_sell_qty

        if not pending_orders: 
            self.orderbook_holding_qty = self.order_book.orderbook_holding_qty
            self.orderbook_holding_avg_price = self.order_book.orderbook_holding_avg_price
            self.initial_holding_sold_qty= self.order_book.initial_holding_sold_qty
            self.cumul_buy_qty = self.order_book.cumul_buy_qty
            self.cumul_sell_qty = self.order_book.cumul_sell_qty
            self.net_cash_used= self.order_book.net_cash_used
            self.cumul_cost = self.order_book.cumul_cost
            self.total_cash_used = self.order_book.total_cash_used

    # called highly frequently, so has to be light O(1)
    # - called only in strategy (to prevent double access from multiple coroutines)
    def update(self, pending_orders=False):
        self._feed_in_ob_managed_data(pending_orders)

        # get data from market_prices
        self.cur_price = self.market_prices.current_price

        _pending_limit_order_amount = excel_round(self.pending_limit_buy_amt*(1+TradePrinciples.LIMIT_ORDER_SAFETY_MARGIN))
        _pending_market_order_amount = excel_round(self.pending_market_buy_qty*self.cur_price*(1+TradePrinciples.MARKET_ORDER_SAFETY_MARGIN))

        self.cash_on_hold = _pending_limit_order_amount + _pending_market_order_amount
        self.cash_available = self.init_cash_allocated - self.total_cash_used - self.cash_on_hold

        self.max_market_buy_amt = excel_round(self.cash_available*(1-TradePrinciples.MARKET_ORDER_SAFETY_MARGIN))
        self.max_limit_buy_amt = excel_round(self.cash_available*(1-TradePrinciples.LIMIT_ORDER_SAFETY_MARGIN))

        self.holding_qty = self.init_holding_qty - self.initial_holding_sold_qty + self.orderbook_holding_qty
        self.max_sell_qty = self.holding_qty - self.pending_sell_qty

        if not pending_orders: 
            self.holding_value = self.holding_qty*self.cur_price 
            self.cash_balance = self.init_cash_allocated - self.total_cash_used
    
            self.avg_price = ((self.init_holding_qty-self.initial_holding_sold_qty)*self.init_avg_price + self.orderbook_holding_qty*self.orderbook_holding_avg_price)/self.holding_qty if self.holding_qty > 0 else 0
            _, self.bep_price = CostCalculator.bep_cost_calculate(self.holding_qty, self.avg_price, self.listed_market, self.my_svr)

            self.return_rate = (self.cur_price-self.avg_price)/self.avg_price if self.avg_price > 0 else 0
            self.bep_return_rate = (self.cur_price-self.bep_price)/self.bep_price if self.bep_price > 0 else 0

            self.init_value = self.init_cash_allocated + self.init_holding_qty*self.init_avg_price
            self.cur_value = self.cash_balance + self.holding_value
            self.unrealized_gain = self.cur_value - self.init_value                      
            self.cap_return_rate = self.unrealized_gain / self.init_value if self.init_value > 0 else 0 

        self.dashboard.enqueue(self)
