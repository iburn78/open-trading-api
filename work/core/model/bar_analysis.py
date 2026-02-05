import asyncio
from dataclasses import dataclass
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
    
    def mark_on_bars(self, mkt_event): 
        bar_ = self.bars[-1]
        bar_.price_event_ = mkt_event.p_event 
        bar_.volume_event_ = mkt_event.v_event 
        bar_.mkt_event_ = mkt_event.mkt_event 

# -------------------------------------------------------------------------
# Analysis classes
# -------------------------------------------------------------------------

class AnalysisTarget(StrEnum):
    PRICE = 'close' 
    VOLUME = 'volume'

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
class EventCategory(StrEnum):
    # price_event_
    PR_SURGE = "price_surge" # more than threshold
    PR_PLUMMET = "price_plummet" # more than threshold

    PR_UPTREND = "price_uptrend"
    PR_DOWNTREND = "price_downtrend"

    PR_SURGE_UPTREND = "price_surge_uptrend"
    PR_PLUMMET_DOWNTREND = "price_plummet_downtrend"

    # volume_event_
    VOL_SURGE = "volume_surge"
    VOL_UPTREND = "volume_uptrend"
    VOL_SURGE_UPTREND = "volume_surge_uptrend"

    # mkt_event_
    PSU_VSU = "market_bull" # Price Surge Uptrend & Volume Surge Uptrend
    PPD_VSU = "market_bear" # Price Plummet Downtrend & Volume Surge Uptrend


@dataclass
class MarketEvent:
    # price
    p_lta: float # last_to_avg
    p_st: float # shifted_trend

    # volume
    v_lta: float # last_to_avg
    v_st: float # shifted_trend

    # decision criteria
    P_LTA_abs_pct: float = 1.0 # absolute difference in percent (e.g., 1% over/under average)
    P_ST_abs_pct: float  = 1.0 # absolute difference in percent (e.g., 1% over/under early)

    V_LTA_th: float = 2.0 # ratio
    V_ST_th: float  = 1.3

    # control vars
    p_event: EventCategory | None = None
    v_event: EventCategory | None = None
    mkt_event: EventCategory | None = None

    def __str__(self): 
        res = f"[MarketEvent] p_lta/st, v:{self.p_lta:.2f}/{self.p_st:.2f} {self.v_lta:.2f}/{self.v_st:.2f}" 
        res += f" | th: {self.P_LTA_abs_pct:.1f}/{self.P_ST_abs_pct:.1f} {self.V_LTA_th:.2f}/{self.V_ST_th:.2f} | " 
        res += f"{self.p_event}/{self.v_event}/{self.mkt_event}"
        return res

    def __post_init__(self):
        # price 
        p1 = None
        p2 = None
        if self.p_lta is not None: 
            if self.p_lta >= 1 + self.P_LTA_abs_pct/100: 
                p1 = EventCategory.PR_SURGE
            elif self.p_lta <= 1 - self.P_LTA_abs_pct/100:
                p1 = EventCategory.PR_PLUMMET
        
        if self.p_st is not None:
            if self.p_st >= 1 + self.P_ST_abs_pct/100: 
                p2 = EventCategory.PR_UPTREND
            elif self.p_st <= 1 - self.P_ST_abs_pct/100:
                p2 = EventCategory.PR_DOWNTREND
            
        if p1 is EventCategory.PR_SURGE and p2 is EventCategory.PR_UPTREND:
            self.p_event = EventCategory.PR_SURGE_UPTREND
        elif p1 is EventCategory.PR_PLUMMET and p2 is EventCategory.PR_DOWNTREND:
            self.p_event = EventCategory.PR_PLUMMET_DOWNTREND
        else: 
            self.p_event = p1 # choose surge/plummet over up/down trend

        # volume
        v1 = None
        v2 = None

        if self.v_lta is not None and self.v_lta >= self.V_LTA_th:
            v1 = EventCategory.VOL_SURGE
        
        if self.v_st is not None and self.v_st >= self.V_ST_th:
            v2 = EventCategory.VOL_UPTREND
            
        if v1 is EventCategory.VOL_SURGE and v2 is EventCategory.VOL_UPTREND:
            self.v_event = EventCategory.VOL_SURGE
        else: 
            self.v_event = v1 # choose surge over uptrend

        # combined
        if self.p_event is EventCategory.PR_SURGE_UPTREND and self.v_event is EventCategory.VOL_SURGE:
            self.mkt_event = EventCategory.PSU_VSU
        elif self.p_event is EventCategory.PR_PLUMMET_DOWNTREND and self.v_event is EventCategory.VOL_SURGE:
            self.mkt_event = EventCategory.PPD_VSU