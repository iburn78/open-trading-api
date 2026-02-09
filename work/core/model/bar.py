from dataclasses import dataclass
from collections import deque
from datetime import datetime, timedelta

# market prices for a given code
# has moving window to record HLCV and weighted ma
@dataclass
class MovingBar:
    code: str 

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
        # deque is for O(1) operation at both ends (but inefficient when slicing)
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
@dataclass(slots=True, frozen=False) # frozen = False to set dashboard info
class Bar:
    start: datetime
    open: int
    high: int
    low: int
    close: int
    volume: int

    # for dashboard display
    price_event: str | None = None
    volume_event: str | None = None
    barlist_event: str | None = None

class RawBars:
    RAW_BAR_DELTA_SEC = 1 # sec

    def __init__(self):
        self.raw_bar_delta = timedelta(seconds=self.RAW_BAR_DELTA_SEC)
        self.raw_bars: list = [] # unbounded list | should not be a deque (which is not efficient when slicing)

        self._cur_start: datetime | None = None
        self._cur_open: int | None = None
        self._cur_high: int | None = None
        self._cur_low: int | None = None
        self._cur_close: int | None = None
        self._cur_volume: int = 0

    def __str__(self):
        NPRINT = 10
        res = []
        for b in self.raw_bars[-NPRINT:]:
            res.append(f"[Bar] ({b.start.strftime('%H%M%S')}) OHLCV {b.open} {b.high} {b.low} {b.close} {b.volume}")
        return '\n'.join(res)

    # ---- public API ----
    def update(self, price: int, quantity: int, t: datetime):
        if self._cur_start is None:
            self._start_new_bar(self._align_start(t), price)

        while t >= self._cur_start + self.raw_bar_delta:
            self._close_bar()
            self.on_raw_bar_close() 
            self._start_new_bar(self._cur_start + self.raw_bar_delta, price)

        self._cur_high = max(self._cur_high, price)
        self._cur_low = min(self._cur_low, price)
        self._cur_close = price
        self._cur_volume += quantity

    # ---- internals ----
    ORIGIN = datetime(2000, 1, 1) # alignment anchor, naive local time (meaning tz is not specifically set)
    def _align_start(self, t: datetime) -> datetime:
        delta = t - self.ORIGIN
        steps = delta // self.raw_bar_delta
        return self.ORIGIN + steps * self.raw_bar_delta

    def _start_new_bar(self, start: datetime, price: int):
        self._cur_start = start
        self._cur_open = price
        self._cur_high = price
        self._cur_low = price
        self._cur_close = price
        self._cur_volume = 0

    def _close_bar(self):
        self.raw_bars.append(
            Bar(
                start=self._cur_start,
                open=self._cur_open,
                high=self._cur_high,
                low=self._cur_low,
                close=self._cur_close,
                volume=self._cur_volume,
            )
        )

    def on_raw_bar_close(self): # callback
        pass
    
class BarBuilder:
    BAR_BUILD_DELTA_SEC = 20 # sec

    def __init__(self, raw_bars: RawBars):
        self.raw_bars = raw_bars
        self.raw_bars.on_raw_bar_close = self.on_raw_bar_close
        self.bar_build_delta = timedelta(seconds=self.BAR_BUILD_DELTA_SEC)
        self.bars: list[Bar] = []

        self._cur_start: datetime | None = None
        self._cur_bar: Bar | None = None

    def reset(self, bar_delta: int):
        res = None
        self.bar_build_delta = timedelta(seconds=bar_delta)
        if self.bar_build_delta < self.raw_bars.raw_bar_delta: 
            self.bar_build_delta = self.raw_bars.raw_bar_delta
            res = "[BarBuilder] bar_build_delta is set at raw_bar_delta, cannot go below raw_bar granularity"
        self.bars.clear() 
        self._cur_start = None
        self._cur_bar = None

        for b in self.raw_bars.raw_bars:
            self.consume(b, reset=True)
        return res

    def on_raw_bar_close(self):
        self.consume(self.raw_bars.raw_bars[-1])

    def consume(self, bar: Bar, reset: bool = False) -> Bar | None:
        if self._cur_start is None:
            self._start(bar)
            return 

        if bar.start >= self._cur_start + self.bar_build_delta:
            self.bars.append(self._cur_bar)
            self._start(bar)
            if not reset:
                self.on_bar_close() 
            return

        self._update(bar)

    def _start(self, bar: Bar):
        self._cur_start = bar.start
        self._cur_bar = Bar(
            start=bar.start,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )

    def _update(self, bar: Bar):
        b = self._cur_bar
        self._cur_bar = Bar(
            start=b.start,
            open=b.open,
            high=max(b.high, bar.high),
            low=min(b.low, bar.low),
            close=bar.close,
            volume=b.volume + bar.volume,
        )

    def on_bar_close(): # callback
        pass 

class BarList: # subset of bars to be used in analysis
    NUM_BAR_TO_ANALYZE = 50

    def __init__(self, bar_builder: BarBuilder):
        self.barlist = []
        self.bar_builder = bar_builder
        self.bar_builder.on_bar_close = self.on_bar_close
        self.reset(self.NUM_BAR_TO_ANALYZE) # initialize

    # if None; use all
    def reset(self, num_bar: int | None):
        self._num_bar = num_bar
        self._get_barlist()

    def on_bar_close(self):
        self._get_barlist()
        self.on_barlist_update()

    def on_barlist_update(self): # callback
        pass
    
    def _get_barlist(self):
        self.barlist = self.bar_builder.bars[-self._num_bar:] if self._num_bar else self.bar_builder.bars

    def mark_on_barlist(self, barlist_event): 
        bar_ = self.barlist[-1]
        bar_.price_event = barlist_event.price_event 
        bar_.volume_event = barlist_event.volume_event 
        bar_.barlist_event = barlist_event.barlist_event 