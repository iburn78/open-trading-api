from dataclasses import dataclass
from collections import deque
from datetime import datetime, timedelta

# market prices for a given code
# has moving window to record HLCV and weighted ma
@dataclass
class MovingBar:
    code: str = ""

    current_price: int | None = None # latest transaction price
    low_price: int | None = None # per window_size
    high_price: int | None = None # per window_size
    moving_avg: int | None = None # price, per window_size
    volume: int = 0 # per window (sum of quantities)
    window_duration: int = 5 # min


    def __str__(self):
        if self.current_price is None:
            return f"[MarketPrices] price record not initialized"
        return f"[MarketPrices] {self.code}, current {self.current_price}, {self.low_price}/{self.high_price}, ma {self.moving_avg}, vol {self.volume}, window {self.window_duration} min"

    def __post_init__(self):
        # initialize sliding windows for price, volume, and amount
        # deque is for O(1) operation at both ends
        self._price_quantity_data = deque()   # (timestamp, price, quantity)
        self._min_price_dq = deque()  # (timestamp, price)
        self._max_price_dq = deque()
        self._sum_prices = 0

    def update(self, price: int, quantity: int, tr_time: datetime):
        self.current_price = price

        cutoff = tr_time - timedelta(minutes=self.window_duration)
        while self._price_quantity_data and self._price_quantity_data[0][0] < cutoff:
            _, _p, _q  = self._price_quantity_data.popleft()
            self._sum_prices -= _p
            self.volume -= _q
        self._sum_prices += price
        self.volume += quantity
        self._price_quantity_data.append((tr_time, price, quantity))
        self.moving_avg = int(self._sum_prices / len(self._price_quantity_data)) if self._price_quantity_data else None

        # min deque
        while self._min_price_dq and self._min_price_dq[0][0] < cutoff:
            self._min_price_dq.popleft()
        while self._min_price_dq and self._min_price_dq[-1][1] >= price:
            self._min_price_dq.pop()
        self._min_price_dq.append((tr_time, price))
        self.low_price = self._min_price_dq[0][1] if self._min_price_dq else None

        # max deque
        while self._max_price_dq and self._max_price_dq[0][0] < cutoff:
            self._max_price_dq.popleft()
        while self._max_price_dq and self._max_price_dq[-1][1] <= price:
            self._max_price_dq.pop()
        self._max_price_dq.append((tr_time, price))
        self.high_price = self._max_price_dq[0][1] if self._max_price_dq else None

# slots = True: does not create __dict__ for each instance, so optimized for speed and memory (while, cannot have additional variables)
@dataclass(slots=True, frozen=True)
class Bar:
    start: datetime
    open: int
    high: int
    low: int
    close: int
    volume: int

class BarSeries:
    def __init__(self, bar_delta: timedelta, cover_duration: timedelta):
        self.bar_delta = bar_delta
        maxlen = cover_duration // bar_delta + 2 # 1 for misaligned origin (if any), 1 for current
        self.bars: deque[Bar] = deque(maxlen=maxlen)

        self._cur_start: datetime | None = None
        self._cur_open: int | None = None
        self._cur_high: int | None = None
        self._cur_low: int | None = None
        self._cur_close: int | None = None
        self._cur_volume: int = 0

        self.on_close = None # callback defined in bar_analyzer

    ###_ may define __str__

    # ---- public API ----
    def update(self, price: int, quantity: int, t: datetime):
        if self._cur_start is None:
            self._start_new_bar(self._align_start(t), price)

        while t >= self._cur_start + self.bar_delta:
            self._close_bar()
            self._start_new_bar(self._cur_start + self.bar_delta, price)

        self._cur_high = max(self._cur_high, price)
        self._cur_low = min(self._cur_low, price)
        self._cur_close = price
        self._cur_volume += quantity

    # ---- internals ----
    ORIGIN = datetime(2000, 1, 1) # alignment anchor, naive local time
    def _align_start(self, t: datetime) -> datetime:
        delta = t - self.ORIGIN
        steps = delta // self.bar_delta
        return self.ORIGIN + steps * self.bar_delta

    def _start_new_bar(self, start: datetime, price: int):
        self._cur_start = start
        self._cur_open = price
        self._cur_high = price
        self._cur_low = price
        self._cur_close = price
        self._cur_volume = 0

    def _close_bar(self):
        self.bars.append(
            Bar(
                start=self._cur_start,
                open=self._cur_open,
                high=self._cur_high,
                low=self._cur_low,
                close=self._cur_close,
                volume=self._cur_volume,
            )
        )
        self.on_close()
    
    @staticmethod
    def aggregate(bars: list[Bar]) -> Bar | None:
        if not bars:
            return None

        return Bar(
            start=bars[0].start,
            open=bars[0].open,
            high=max(b.high for b in bars),
            low=min(b.low for b in bars),
            close=bars[-1].close,
            volume=sum(b.volume for b in bars),
        )