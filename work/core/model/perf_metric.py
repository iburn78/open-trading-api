from dataclasses import dataclass
from datetime import datetime

from .order_book import OrderBook
from .price import MarketPrices
from ..common.setup import TradePrinciples
from ..common.tools import adj_int

@dataclass
class PerformanceMetric:
    # agent managed data
    agent_id: str | None = None
    code: str | None = None
    order_book: OrderBook | None = None
    market_prices: MarketPrices | None = None

    # initial setup data (set through agent)
    initial_allocated_cash: int | None = None # this is pure cash, not including the initial holding
    initial_holding: int | None = None
    avg_price_initial_holding: int | None = None
    bep_price_initial_holding: int | None = None 

    # OrderBook managed data 
    orderbook_holding: int | None = None # quantity, can be negative 
    # - 주문 상태
    on_buy_order: int | None = None  # quantity
    on_LIMIT_buy_amount: int | None = None # amount 
    on_MARKET_buy_quantity: int | None = None # quantity
    on_sell_order: int | None = None # quantity
    # - 체결된 사항
    total_purchased: int | None = None # quantity
    total_sold: int | None = None # quantity
    principle_cash_used: int | None = None # negative: profit, positive: loss or on stock holding
    total_cost_incurred: int | None = None # cumulative tax and fee
    total_cash_used: int | None = None # principle + total_cost_incurred

    # MarketPrices managed data
    cur_price: int | None = None
    cur_time: datetime | None = None

    # -------------------------------------------------------
    # stats, values and returns
    # cost 반영 원칙: 내가 초래한 Cost만 반영함 
    # - initial holding의 Purchase cost는 미반영
    # - holding의 미래 Selling cost는 미반영 (selling price dependent)
    # -------------------------------------------------------
    on_order_cash: int | None = None # order margin considered
    available_cash: int | None = None # allocated - total_used - on_order

    max_MARKET_buy_amount: int | None = None
    max_LIMIT_buy_amount: int | None = None
    max_sell_quantity: int | None = None

    current_holding_value: int | None = None # (initial_holding + orderbook_holding) x cur_price
    cash_in_hand: int | None = None # allocated - total_used
    
    holding_avg_price: int | None = None
    holding_bep_price: int | None = None

    holding_return_rate: float | None = None # before tax and fee
    holding_bep_return_rate: float | None = None # only account cost for current holding (initial + orderbook)

    agent_abs_value: int | None = None # after cumulative cost since initialization
    agent_abs_return: int | None = None # after cumulative cost since initialization

    # this lets Strategy to use data from pm only
    def _feed_in_ob_mp_managed_data(self):
        # get data from order_book
        self.orderbook_holding = self.order_book.orderbook_holding
        self.on_buy_order = self.order_book.on_buy_order
        self.on_LIMIT_buy_amount = self.order_book.on_LIMIT_buy_amount
        self.on_MARKET_buy_quantity = self.order_book.on_MARKET_buy_quantity
        self.on_sell_order = self.order_book.on_sell_order
        self.total_purchased = self.order_book.total_purchased
        self.total_sold = self.order_book.total_sold
        self.principle_cash_used = self.order_book.principle_cash_used
        self.total_cost_incurred = self.order_book.total_cost_incurred
        self.total_cash_used = self.order_book.total_cash_used

        # get data from market_prices
        self.cur_price = self.market_prices.current_price
        self.cur_time = self.market_prices.current_time

    # called very frequently, so has to be light O(1)
    # - called upon Strategy init and every dispatch of order, trn, trp in Agent
    def update(self):
        self._feed_in_ob_mp_managed_data()

        on_LIMIT_order_amount = self.on_LIMIT_buy_amount*(1+TradePrinciples.LIMIT_ORDER_SAFETY_MARGIN)
        on_MARKET_order_amount = self.on_MARKET_buy_quantity*self.cur_price*(1+TradePrinciples.MARKET_ORDER_SAFETY_MARGIN)

        self.on_order_cash = on_LIMIT_order_amount + on_MARKET_order_amount
        self.available_cash = self.initial_allocated_cash - self.total_cash_used - self.on_order_cash

        self.max_MARKET_buy_amount = adj_int(self.available_cash*(1-TradePrinciples.MARKET_ORDER_SAFETY_MARGIN))
        self.max_LIMIT_buy_amount = adj_int(self.available_cash*(1-TradePrinciples.LIMIT_ORDER_SAFETY_MARGIN))
        self.max_sell_quantity = self.initial_holding + self.orderbook_holding - self.on_sell_order

    ###_ rethink if pm.update() is necesssary
    ###_ reduce frequent calling
    ###_ if called here and there, should _lock necessary? 
    ###_ separate logic


    