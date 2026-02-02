import asyncio
from dataclasses import dataclass
from abc import ABC, abstractmethod
from enum import StrEnum

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
    
    def handle_mkt_event(self, price_mkt_event, volume_mkt_event): # MarketEvents
        tag_ = False
        if price_mkt_event.is_event():
            self.bars[-1].price_event_ = price_mkt_event.get_event_str()
            tag_ = True
        if volume_mkt_event.is_event():
            self.bars[-1].volume_event_ = volume_mkt_event.get_event_str()
            tag_ = True
        if tag_: 
            self.market_signals.put_nowait(price_mkt_event) ###_

# -------------------------------------------------------------------------
# Analysis classes
# -------------------------------------------------------------------------

class AnalysisTarget(StrEnum):
    PRICE = 'close' # either PRICE or CLOSE
    CLOSE = 'close'
    VOLUME = 'volume'

###_ price is bi-directional. 
class SeriesAnalysis:
    @staticmethod
    def get_last_to_avg(bars: list[Bar], attr: AnalysisTarget): # attr: "close", "volume", etc
        avg_past = sum(getattr(b, attr) for b in bars) / len(bars)
        if avg_past == 0: return None
        return getattr(bars[-1], attr) / avg_past

    @staticmethod
    def get_shifted_trend(bars, attr: AnalysisTarget, shift=None): # attr: "close", "volume", etc
        if shift is None:
            shift = max(1, len(bars) // 3)

        early = bars[:-shift]
        late  = bars[shift:]

        if not early or not late:
            return None

        early_avg = sum(getattr(b, attr) for b in early) / len(early)
        late_avg  = sum(getattr(b, attr) for b in late) / len(late)

        if early_avg == 0:
            return None

        return late_avg / early_avg

# -------------------------------------------------------------------------
# MarketEvent definitions
# -------------------------------------------------------------------------
class MarketEvent(ABC):
    @abstractmethod
    def is_event(self) -> bool:
        pass
    def get_event_str(self) -> bool:
        pass

class EventCategory(StrEnum):
    NONE = ""
    SURGE = "Sg"
    UPTREND = 'Up'
    SURGE_UPTREND = "SU"

@dataclass
class TrendEvent(MarketEvent):
    category: AnalysisTarget
    last_to_avg: float | None = None # lta
    shifted_trend: float | None = None # st

    # decision criteria
    LAST_TO_AVG_THRESHOLD: float = 2.0
    SHIFTED_TREND_THRESHOLD: float  = 1.3

    # decision indicators
    last_val_surge: bool = False
    shifted_up_trend: bool = False

    def __str__(self): 
        res = f"[{self.category}] lta: {self.last_to_avg}/{self.LAST_TO_AVG_THRESHOLD}, st: {self.shifted_trend}/{self.SHIFTED_TREND_THRESHOLD}"
        if self.last_val_surge: 
            res += f" | Surge detected"
        if self.shifted_up_trend: 
            res += f" | Shifted Up-Trend detected"
        return res

    def is_event(self):
        if self.last_to_avg and self.last_to_avg >= self.LAST_TO_AVG_THRESHOLD:
            self.last_val_surge = True
        if self.shifted_trend and self.shifted_trend >= self.SHIFTED_TREND_THRESHOLD:
            self.shifted_up_trend = True

        return self.last_val_surge or self.shifted_up_trend
    
    def get_event_str(self):
        if self.last_val_surge: 
            if self.shifted_up_trend: 
                res = EventCategory.SURGE_UPTREND
            else: 
                res = EventCategory.SURGE
        else:
            if self.shifted_up_trend: 
                res = EventCategory.UPTREND
            else: 
                res = EventCategory.NONE
        return res
    