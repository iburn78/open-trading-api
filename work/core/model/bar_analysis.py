import asyncio
from dataclasses import dataclass
from abc import ABC, abstractmethod
from datetime import datetime
from itertools import islice

from .bar import MovingBar, BarSeries, Bar

class BarAnalyzer:
    # get data from agent
    def __init__(self, moving_bar: MovingBar, bar_series: BarSeries, market_signals: asyncio.Queue):
        self.moving_bar = moving_bar
        self.bar_series = bar_series
        self.bar_series.on_close = self.on_close
        self.market_signals = market_signals

        ###_ need to define variables
        ###_ below test
        self.num_bar = 10 # number of bars to analysis
        self.bar_list = None

    def on_close(self):
        if len(self.bar_series.bars) < self.num_bar: return
        # getting last N=num_bar bars 
        self.bar_list = list(islice(self.bar_series.bars, len(self.bar_series.bars) - self.num_bar, None))

        va = self.get_vol_to_avg()
        svr = self.get_shifted_vol_ratio()

        mkt_event = VolumeTrendEvent(va, svr)
        if mkt_event.is_event():
            mkt_event.event_time = self.bar_series._cur_start
            self.market_signals.put(mkt_event)

    def get_vol_to_avg(self):
        avg_past = sum(b.volume for b in self.bar_list) / self.num_bar
        if avg_past == 0: return None
        return self.bar_list[-1].volume / avg_past
    
    def get_shifted_vol_ratio(self, shift: int | None = None):
        if shift is None: shift = max(1, self.num_bar // 4)

        early = self.bar_list[:-shift]
        late = self.bar_list[shift:]
        early_avg = sum(b.volume for b in early) / len(early)
        late_avg = sum(b.volume for b in late) / len(late)

        if early_avg == 0: return None
        return late_avg / early_avg # (last N-shift bars)/(first N-shift bars) 

class MarketEvent(ABC):
    @abstractmethod
    def temp(self):
        pass

@dataclass
class VolumeTrendEvent(MarketEvent):
    volume_to_avg: float | None = None # vta
    shifted_vol_ratio: float | None = None # svr

    volume_surge: bool = False
    volume_up_trend: bool = False
    event_time: datetime | None = None

    # decision criteria
    VOLUME_RATIO: float = 2.0
    SLOPE_RATIO: float  = 1.3

    def __str__(self): 
        res = f"[VolumeTrendEvent] vta: {self.volume_to_avg}/{self.VOLUME_RATIO}, svr: {self.shifted_vol_ratio}/{self.SLOPE_RATIO} ({self.event_time.strftime('%M:%S')})"
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