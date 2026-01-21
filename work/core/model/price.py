from dataclasses import dataclass
from collections import deque
from datetime import datetime, timedelta

from ..base.tools import excel_round
from ..kis.ws_data import TransactionPrices

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
    max_trans_per_sec: int = 10
    safety_margin: float = 0.1 

    # internal control
    _update_called: bool = False

    def __str__(self):
        if not self._update_called:
            return f"price record not initialized and current_price set at {self.current_price}"
        return (
            f"[MarketPrices] {self.code}, current {self.current_price}, "
            f"l/h {self.low_price}/{self.high_price}, ma {self.moving_avg}, "
            f"m_amt {excel_round(self.moving_amount/10**6)}M, cum_amt {excel_round(self.cumulative_amount/10**6)}M, "
            f"window {self.window_size} min"
        )

    def __post_init__(self):
        # initialize sliding windows for price, volume, and amount
        L = 10000 # reasonable - might be enough
        self.maxlen = int(min(L, self.window_size*60*self.max_trans_per_sec*(1+self.safety_margin)))
        self._price_ticks = deque(maxlen=self.maxlen)   # (timestamp, price)
        self._volume_window = deque(maxlen=self.maxlen)  # (timestamp, volume)
        self._amount_window = deque(maxlen=self.maxlen)  # (timestamp, amount)
        self._min_price_dq = deque()  # (timestamp, price)
        self._max_price_dq = deque()

        # running sums for O(1) updates
        self._sum_trade_price = 0
        self._sum_volume = 0
        self._sum_amount = 0

        # initialize cumulative trackers
        self.cumulative_volume = 0
        self.cumulative_amount = 0

    def _trim_and_update_sum(self, cutoff, dq, total_attr, value, tr_time):
        """Shared logic for adding new value and trimming old ones."""
        total = getattr(self, total_attr) # getattr is appropriate, as otherwise if directly var is used, then its values are passed by value (not reference)
        while dq and dq[0][0] < cutoff:
            _, old_val = dq.popleft()
            total -= old_val
        dq.append((tr_time, value))
        total += value
        if len(dq) > self.maxlen*(1-self.safety_margin):
            raise RuntimeError(f"[MarketPrices] {self.code} deque for {total_attr} length exceeds over {(1-self.safety_margin)*100}% of maxlen") 

        setattr(self, total_attr, total)

    ###_ dynamic window size change -> check ... shrink case 
    ###_ add deque to track volume per window (as discrete data, last N data...) => devise logic first, and then implement
    def update(self, price: int, quantity: int, tr_time: datetime, _window_resize: bool = False):
        """Main update — handles trimming and recalculating all moving metrics."""
        cutoff = tr_time - timedelta(minutes=self.window_size)
        self._trim_and_update_sum(cutoff, self._price_ticks, "_sum_price", price, tr_time)
        self._trim_and_update_sum(cutoff, self._volume_window, "_sum_volume", quantity, tr_time)
        self._trim_and_update_sum(cutoff, self._amount_window, "_sum_amount", price * quantity, tr_time)

        self.current_price = price
        self.current_time = tr_time

        while self._min_price_dq and self._min_price_dq[0][0] < cutoff:
            self._min_price_dq.popleft()

        while self._max_price_dq and self._max_price_dq[0][0] < cutoff:
            self._max_price_dq.popleft()

        # min deque
        while self._min_price_dq and self._min_price_dq[-1][1] >= price:
            self._min_price_dq.pop()
        self._min_price_dq.append((tr_time, price))

        # max deque
        while self._max_price_dq and self._max_price_dq[-1][1] <= price:
            self._max_price_dq.pop()
        self._max_price_dq.append((tr_time, price))

        self.low_price = self._min_price_dq[0][1] if self._min_price_dq else None
        self.high_price = self._max_price_dq[0][1] if self._max_price_dq else None
        self.moving_avg = int(self._sum_trade_price / len(self._price_ticks)) if self._price_ticks else None

        # update cumulative and moving values
        if not _window_resize:
            self.cumulative_volume += quantity
            self.cumulative_amount += price * quantity
        self.moving_volume = self._sum_volume
        self.moving_amount = self._sum_amount

        # initial value control
        self._update_called = True

    def set_window_size(self, new_size: int): 
        """Change window size and refresh metrics using the last known record."""
        if new_size == self.window_size:
            return
        self.window_size = new_size
        if self._price_ticks:
            # Re-run update using last record to re-trim based on new window
            last_time, last_price = self._price_ticks[-1]
            last_qty = self._volume_window[-1][1] if self._volume_window else 0
            self.update(last_price, last_qty, last_time, _window_resize=True)

    def update_from_trp(self, trp: TransactionPrices):
        p, q, t = trp.get_price_quantity_time()
        self.update(p, q, t)

        