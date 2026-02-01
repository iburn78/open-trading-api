import asyncio
from dataclasses import dataclass
from abc import ABC, abstractmethod

from .bar import BarAggregator, Bar

# -------------------------------------------------------------------------
# BarAnalyzer: set-up analysis 
# -------------------------------------------------------------------------
# on_bar_update to be overrided in Strategy
class BarAnalyzer:
    NUM_BAR_TO_ANALYZE = 10

    def __init__(self, bar_aggr: BarAggregator, market_signals: asyncio.Queue):
        self.bar_aggr = bar_aggr
        self.bar_aggr.on_aggr_bar_close = self.on_aggr_bar_close
        self.market_signals = market_signals
        self.reset(self.NUM_BAR_TO_ANALYZE) # initialize

    # set to None to use all
    def reset(self, num_bar: int):
        self._num_bar = num_bar
        self.bars = self.bar_aggr.aggr_bars[-self._num_bar:] if self._num_bar else self.bar_aggr.aggr_bars

    def on_aggr_bar_close(self):
        self.bars = self.bar_aggr.aggr_bars[-self._num_bar:] if self._num_bar else self.bar_aggr.aggr_bars
        self.on_bar_update()

    def on_bar_update(self): # bar = aggr_bar
        # to be called back (or called instead) in Strategy subclass
        pass
    
    def handle_mkt_event(self, mkt_event): # MarketEvent
        if mkt_event.is_event():
            self.bars[-1].event_ = "Event" # simplest event notification to dashboard
            self.market_signals.put_nowait(mkt_event)

# -------------------------------------------------------------------------
# Analysis classes
# -------------------------------------------------------------------------

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
        if not late or not early: return None
        early_avg = sum(b.volume for b in early) / len(early) # Bar
        late_avg = sum(b.volume for b in late) / len(late) # Bar

        if early_avg == 0: return None
        return late_avg / early_avg # (last N-shift bars)/(first N-shift bars) 

class PriceAnalysis:
    ###_ add more analysis
    ###_ price surge with volume
    pass

# -------------------------------------------------------------------------
# MarketEvent definitions
# -------------------------------------------------------------------------
class MarketEvent(ABC):
    @abstractmethod
    def is_event(self) -> bool:
        pass

@dataclass
class VolumeTrendEvent(MarketEvent):
    volume_to_avg: float | None = None # vta
    shifted_vol_ratio: float | None = None # svr

    # decision criteria
    VOLUME_RATIO: float = 2.0
    SLOPE_RATIO: float  = 1.3

    # decision indicators
    volume_surge: bool = False
    volume_up_trend: bool = False

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
    