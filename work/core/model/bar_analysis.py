import asyncio
from dataclasses import dataclass
from abc import ABC, abstractmethod

from .bar import BarAggregator, Bar

class BarAnalyzer:
    NUM_BAR_TO_ANALYZE = 10

    def __init__(self, bar_aggr: BarAggregator, market_signals: asyncio.Queue):
        self.bar_aggr = bar_aggr
        self.bar_aggr.on_bar_close = self.on_bar_close()
        self.bars = self.bar_aggr.aggr_bars 

        self.market_signals = market_signals
        self.num_bar: int = self.NUM_BAR_TO_ANALYZE 

    def reset_num_bar(self, num_bar: int):
        self.num_bar = num_bar

    def on_bar_close(self):
        if len(self.bars) < self.num_bar:
            return

        bars = self.bars[-self.num_bar:]
        self.analysis_bars(bars)

    ###_ how to make this more flexible
    def analysis_bars(self, bars: list[Bar]):
        # example
        va = VolumeAnalysis.get_vol_to_avg(bars)
        svr = VolumeAnalysis.get_shifted_vol_ratio(bars)

        mkt_event = VolumeTrendEvent(va, svr)
        if mkt_event.is_event():
            self.market_signals.put(mkt_event)

class VolumeAnalysis:
    @staticmethod
    def get_vol_to_avg(bars: list[Bar]):
        avg_past = sum(b.volume for b in bars) / len(bars)
        if avg_past == 0: return None
        return bars[-1].volume / avg_past

    @staticmethod
    def get_shifted_vol_ratio(bars: list[Bar], shift: int | None = None):
        if shift is None: shift = max(1, len(bars) // 4)

        early = bars[:-shift]
        late = bars[shift:]
        early_avg = sum(b.volume for b in early) / len(early) # Bar
        late_avg = sum(b.volume for b in late) / len(late) # Bar

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

    # decision criteria
    VOLUME_RATIO: float = 2.0
    SLOPE_RATIO: float  = 1.3

    def __str__(self): 
        res = f"[VolumeTrendEvent] vta: {self.volume_to_avg}/{self.VOLUME_RATIO}, svr: {self.shifted_vol_ratio}/{self.SLOPE_RATIO}"
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
    
    def temp(self):
        pass