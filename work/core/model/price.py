from dataclasses import dataclass
from collections import deque
from datetime import datetime, timedelta
import asyncio

from ..kis.ws_data import TransactionPrices

# market prices for a given code
@dataclass
class MarketPrices:
    code: str = ""

    current_price: int | None = None # latest transaction price
    low_price: int | None = None # per window_size
    high_price: int | None = None # per window_size
    moving_avg: int | None = None # price, per window_size

    window_duration: int = 0.5 # min
    num_buckets: int = 12 # last N windows 

    # market price signal 
    ###_ further develop
    mp_signals: asyncio.Queue | None = None

    def __str__(self):
        if self.current_price is None:
            return f"[MarketPrices] price record not initialized"
        return f"[MarketPrices] {self.code}, current {self.current_price}, l/h {self.low_price}/{self.high_price}, ma {self.moving_avg}, window {self.window_duration} min"

    def __post_init__(self):
        # initialize sliding windows for price, volume, and amount
        # deque is for O(1) operation at both ends
        self._price_quantity_data = deque()   # (timestamp, price, quantity)
        self._min_price_dq = deque()  # (timestamp, price)
        self._max_price_dq = deque()

        # running sums for O(1) updates
        self._sum_prices = 0
        self._volume = 0 # per window (sum of quantities)

        # bucket config
        self._bucket_delta = timedelta(minutes=self.window_duration)

        # bucket storage
        self._volume_buckets = deque(maxlen=self.num_buckets)  # completed buckets
        self._current_bucket_start: datetime | None = None
        self._current_bucket_volume: int = 0   # not the same as _volume (moving volume) due to the last transaction

    ###_ suppose time is fom API and could be off by local time (rounded to sec)
    def update_from_trp(self, trp: TransactionPrices):
        p, q, t = trp.get_price_quantity_time()
        self.update(p, q, t)

    def update(self, price: int, quantity: int, tr_time: datetime):
        self.current_price = price

        cutoff = tr_time - timedelta(minutes=self.window_duration)
        while self._price_quantity_data and self._price_quantity_data[0][0] < cutoff:
            _, _p, _q  = self._price_quantity_data.popleft()
            self._sum_prices -= _p
            self._volume -= _q
        self._sum_prices += price
        self._volume += quantity
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

        # volume bucket update
        self._init_bucket(tr_time)
        self._advance_bucket(tr_time)
        self._current_bucket_volume += quantity

    # aligns time bucket to start from xx:xx:00.000 
    def _init_bucket(self, tr_time: datetime):
        if self._current_bucket_start is None:
            aligned = tr_time.replace(
                second=0, microsecond=0
            ) - timedelta(minutes=tr_time.minute % self.window_duration)
            self._current_bucket_start = aligned

    def _init_bucket(self, tr_time: datetime):
        if self._current_bucket_start is None:
            # Convert total time to seconds within the hour
            total_seconds = tr_time.minute * 60 + tr_time.second + tr_time.microsecond / 1e6

            # Align to nearest lower multiple of window_seconds
            aligned_seconds = total_seconds - (total_seconds % (self.window_duration*60))

            # Build aligned datetime
            self._current_bucket_start = tr_time.replace(minute=0, second=0, microsecond=0) + timedelta(seconds=aligned_seconds)

    # while: advances buckets until the current trade fits.
    def _advance_bucket(self, tr_time: datetime):
        while tr_time >= self._current_bucket_start + self._bucket_delta:
            # close current bucket
            self._volume_buckets.append(self._current_bucket_volume) # save before adding last transaction quantitiy

            # advance
            self._current_bucket_start += self._bucket_delta
            
            # assess and reset
            self._on_bucket_close()
            self._current_bucket_volume = 0

    # --------------------------------------------
    # volume status detect functions
    # --------------------------------------------
    # calculate status of the last buckets
    def _on_bucket_close(self):
            va = self.get_vol_to_avg()
            svr = self.get_shifted_vol_ratio()

            pte = PriceTrendEvent(va, svr)
            if pte.is_event(self):
                pte.event_time = self._current_bucket_start
                self.mp_signals.put(pte)

    def get_vol_to_avg(self):
        if len(self._volume_buckets) < self.num_buckets: return None
        avg_past = sum(self._volume_buckets) / len(self._volume_buckets)
        if avg_past == 0: return None

        return self._current_bucket_volume / avg_past
    
    def get_shifted_vol_ratio(self, shift: int | None = None):
        if len(self._volume_buckets) < self.num_buckets: return None
        if shift is None: shift = max(1, self.num_buckets // 4)

        past = list(self._volume_buckets)
        early = past[:-shift]
        late = past[shift:]
        early_avg = sum(early) / len(early)
        late_avg = sum(late) / len(late)

        if early_avg == 0: return None
        return late_avg / early_avg # (last N-shift buckets)/(first N-shift buckets) 

@dataclass
class PriceTrendEvent:
    volume_to_avg: float | None = None
    shifted_vol_ratio: float | None = None

    volume_surge: bool = False
    volume_up_trend: bool = False
    event_time: datetime | None = None

    # decision criteria
    VOLUME_RATIO: float = 2.0
    SLOPE_RATIO: float  = 1.3

    def __str__(self): 
        res = f"[PriceTrendEvent] vta: {self.volume_to_avg}/{self.VOLUME_RATIO}, svr: {self.shifted_vol_ratio}/{self.SLOPE_RATIO} ({self.event_time.strftime('%M:%S')})"
        if self.volume_surge: 
            res += f" | Volume Surge detected"
        if self.volume_up_trend: 
            res += f" | Volume Up Trend detected"
        return res

    def is_event(self):
        if self.volume_to_avg and self.volume_to_avg > self.VOLUME_RATIO:
            self.volume_surge = True
        if self.shifted_vol_ratio and self.shifted_vol_ratio > self.SLOPE_RATIO:
            self.volume_up_trend = True

        return self.volume_surge or self.volume_up_trend
