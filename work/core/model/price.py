from dataclasses import dataclass, field
from collections import deque
from datetime import datetime, timedelta

from ..common.tools import adj_int
from ..kis.ws_data import TransactionPrices
from ..model.perf_metric import PerformanceMetric

# market prices for a given code
@dataclass
class MarketPrices:
    code: str = ""

    current_price: int | None = None
    current_time: datetime | None = None # current price time
    low_price: int | None = None # per window_size
    high_price: int | None = None # per window_size
    moving_avg: int | None = None # per window_size

    # volume: 거래량 (quantity: 개별 거래건 수량)
    cumulative_volume: int | None = None
    moving_volume: int | None = None # per window_size
    
    # amount: 거래대금
    cumulative_amount: int | None = None 
    moving_amount: int | None = None # per window_size

    # to be only modified using set_window_size() after initialization
    window_size: int = 5 # min

    def __str__(self):
        if not self.current_price:
            return "price record not initialized"
        return (
            f"MarketPrices {self.code}, current {self.current_price}, "
            f"l/h {self.low_price}/{self.high_price}, ma {self.moving_avg}, "
            f"m_amt {adj_int(self.moving_amount/10**6)}M, cum_amt {adj_int(self.cumulative_amount/10**6)}M, "
            f"window {self.window_size} min"
        )

    def __post_init__(self):
        # initialize sliding windows for price, volume, and amount
        self._price_window = deque()   # (timestamp, price)
        self._volume_window = deque()  # (timestamp, volume)
        self._amount_window = deque()  # (timestamp, amount)

        # running sums for O(1) updates
        self._sum_price = 0.0
        self._sum_volume = 0
        self._sum_amount = 0

        # initialize cumulative trackers
        self.cumulative_volume = 0
        self.cumulative_amount = 0

    def _trim_and_update_sum(self, dq, total_attr, value, tr_time):
        """Shared logic for adding new value and trimming old ones."""
        cutoff = tr_time - timedelta(minutes=self.window_size)
        total = getattr(self, total_attr) # getattr is appropriate, as otherwise if directly var is used, then its values are passed by value (not reference)
        while dq and dq[0][0] < cutoff:
            _, old_val = dq.popleft()
            total -= old_val
        dq.append((tr_time, value))
        total += value
        setattr(self, total_attr, total)

    def update(self, price: int, quantity: int, tr_time: datetime, _window_resize: bool = False):
        """Main update — handles trimming and recalculating all moving metrics."""
        self._trim_and_update_sum(self._price_window, "_sum_price", price, tr_time)
        self._trim_and_update_sum(self._volume_window, "_sum_volume", quantity, tr_time)
        self._trim_and_update_sum(self._amount_window, "_sum_amount", price * quantity, tr_time)

        self.current_price = price
        self.current_time = tr_time

        # update derived metrics
        if self._price_window:
            prices = [p for _, p in self._price_window]
            self.low_price = min(prices)
            self.high_price = max(prices)
            self.moving_avg = int(self._sum_price / len(prices))
        else:
            self.low_price = self.high_price = self.moving_avg = None

        # update cumulative and moving values
        if not _window_resize:
            self.cumulative_volume += quantity
            self.cumulative_amount += price * quantity
        self.moving_volume = self._sum_volume
        self.moving_amount = self._sum_amount

    def set_window_size(self, new_size: int): 
        """Change window size and refresh metrics using the last known record."""
        if new_size == self.window_size:
            return
        self.window_size = new_size
        if self._price_window:
            # Re-run update using last record to re-trim based on new window
            last_time, last_price = self._price_window[-1]
            last_qty = self._volume_window[-1][1] if self._volume_window else 0
            self.update(last_price, last_qty, last_time, _window_resize=True)

    def update_from_trp(self, trp: TransactionPrices):
        p, q, t = trp.get_price_quantity_time()
        self.update(p, q, t)

    def update_performance_metric(self, pm: PerformanceMetric):
        # if pm.code != self.code: return None
        pm.cur_return = self.current_price
        pm.cur_time = self.current_time