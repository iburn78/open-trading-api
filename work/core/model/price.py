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
    current_time: datetime | None = None # latest transaction time
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

    def update_from_trp(self, trp: TransactionPrices):
        p, q, t = trp.get_price_quantity_time()
        self.update(p, q, t)

    def update(self, price: int, quantity: int, tr_time: datetime):
        self.current_price = price
        self.current_time = tr_time

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

    # while: advances buckets until the current trade fits.
    def _advance_bucket(self, tr_time: datetime):
        while tr_time >= self._current_bucket_start + self._bucket_delta:
            # close current bucket
            self._volume_buckets.append(self._current_bucket_volume) # save before adding last transaction quantitiy
            self._on_bucket_close()

            # advance
            self._current_bucket_start += self._bucket_delta
            self._current_bucket_volume = 0

    def _on_bucket_close(self):
            # calculate status of the last buckets
            ###_ info and signaling
            ###_ use event queue from agent
            print(self.detect_volume_surge(ratio=2.0))
            print(self.detect_volume_trend(slope_ratio=1.3))
            print(self._current_bucket_volume)
            print(self._volume)
            print(self.current_time)
            print('--------------------------------------------------')

    # --------------------------------------------
    # volume status detect functions
    # --------------------------------------------

    def detect_volume_surge(self, ratio: float) -> bool:
        """
        Returns True if current bucket volume is significantly larger than bucket average
        """
        if len(self._volume_buckets) < self.num_buckets:
            return False

        avg_past = sum(self._volume_buckets) / len(self._volume_buckets)

        # protect against zero-volume periods
        if avg_past == 0:
            return False

        return self._current_bucket_volume >= ratio * avg_past
    
    def detect_volume_trend(self, slope_ratio: float, shift: int | None = None) -> bool: 
        """
        True/False if slope_ratio > (last N-shift buckets)/(first N-shift buckets)
        """
        if len(self._volume_buckets) < self.num_buckets:
            return False

        past = list(self._volume_buckets)

        if shift is None:
            shift = max(1, self.num_buckets // 4)

        early = past[:-shift]
        late = past[shift:]

        early_avg = sum(early) / len(early)
        late_avg = sum(late) / len(late)

        if early_avg == 0:
            return False

        return late_avg / early_avg >= slope_ratio