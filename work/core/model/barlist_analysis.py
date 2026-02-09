from dataclasses import dataclass
from enum import StrEnum

from .bar import Bar

# -------------------------------------------------------------------------
# Analysis classes
# -------------------------------------------------------------------------
class AnalysisTarget(StrEnum):
    PRICE = 'close' # var name in Bar class
    VOLUME = 'volume'

class BarListAnalysis: # analysis tools; gets list[Bar]
    @staticmethod
    def get_last_to_avg(bars: list[Bar], attr: AnalysisTarget):
        avg_past = sum(getattr(b, attr) for b in bars) / len(bars)
        if avg_past == 0: return None
        return getattr(bars[-1], attr) / avg_past

    @staticmethod
    def get_shifted_trend(bars: list[Bar], attr: AnalysisTarget, shift=None):
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
# BarListEvent definitions and assignments
# -------------------------------------------------------------------------
class BarListEvent(StrEnum):
    # price_event
    PR_SURGE = "price_surge" # more than threshold
    PR_PLUMMET = "price_plummet" # more than threshold

    PR_UPTREND = "price_uptrend" # internal only 
    PR_DOWNTREND = "price_downtrend" # internal only

    PR_SURGE_UPTREND = "price_surge_uptrend"
    PR_PLUMMET_DOWNTREND = "price_plummet_downtrend"

    # volume_event
    VOL_SURGE = "volume_surge"
    VOL_UPTREND = "volume_uptrend" # internal only
    VOL_SURGE_UPTREND = "volume_surge_uptrend"

    # barlist_event (p and v combined)
    BARLIST_BULL = "barlist_bull" # Price Surge Uptrend & Volume Surge Uptrend
    BARLIST_BEAAR = "barlist_bear" # Price Plummet Downtrend & Volume Surge Uptrend

@dataclass
class BarListStatus:
    # price
    p_lta: float # last_to_avg
    p_st: float # shifted_trend

    # volume
    v_lta: float # last_to_avg
    v_st: float # shifted_trend

    # decision criteria
    P_LTA_abs_pct: float = 0.5 # absolute difference in percent (e.g., 1% over/under average)
    P_ST_abs_pct: float  = 0.3 # absolute difference in percent (e.g., 1% over/under early)

    V_LTA_th: float = 1.5 # ratio
    V_ST_th: float  = 1.3

    # events
    price_event: BarListEvent | None = None
    volume_event: BarListEvent | None = None
    barlist_event: BarListEvent | None = None

    def __str__(self): 
        res = f"[BarListStatus] p_lta/st, v:{self.p_lta:.2f}/{self.p_st:.2f} {self.v_lta:.2f}/{self.v_st:.2f}" 
        res += f" | th: {self.P_LTA_abs_pct:.2f}/{self.P_ST_abs_pct:.2f} {self.V_LTA_th:.2f}/{self.V_ST_th:.2f} | " 
        res += f"{self.price_event}/{self.volume_event}/{self.barlist_event}"
        return res

    def __post_init__(self):
        # price 
        p1 = None
        p2 = None
        if self.p_lta is not None: 
            if self.p_lta >= 1 + self.P_LTA_abs_pct/100: 
                p1 = BarListEvent.PR_SURGE
            elif self.p_lta <= 1 - self.P_LTA_abs_pct/100:
                p1 = BarListEvent.PR_PLUMMET
        
        if self.p_st is not None:
            if self.p_st >= 1 + self.P_ST_abs_pct/100: 
                p2 = BarListEvent.PR_UPTREND
            elif self.p_st <= 1 - self.P_ST_abs_pct/100:
                p2 = BarListEvent.PR_DOWNTREND
            
        if p1 is BarListEvent.PR_SURGE and p2 is BarListEvent.PR_UPTREND:
            self.price_event = BarListEvent.PR_SURGE_UPTREND
        elif p1 is BarListEvent.PR_PLUMMET and p2 is BarListEvent.PR_DOWNTREND:
            self.price_event = BarListEvent.PR_PLUMMET_DOWNTREND
        else: 
            self.price_event = p1 # choose surge/plummet over up/down trend

        # volume
        v1 = None
        v2 = None

        if self.v_lta is not None and self.v_lta >= self.V_LTA_th:
            v1 = BarListEvent.VOL_SURGE
        
        if self.v_st is not None and self.v_st >= self.V_ST_th:
            v2 = BarListEvent.VOL_UPTREND
            
        if v1 is BarListEvent.VOL_SURGE and v2 is BarListEvent.VOL_UPTREND:
            self.volume_event = BarListEvent.VOL_SURGE_UPTREND
        else: 
            self.volume_event = v1 # choose surge over uptrend

        # combined
        if self.price_event is BarListEvent.PR_SURGE_UPTREND and self.volume_event is BarListEvent.VOL_SURGE:
            self.barlist_event = BarListEvent.BARLIST_BULL
        elif self.price_event is BarListEvent.PR_PLUMMET_DOWNTREND and self.volume_event is BarListEvent.VOL_SURGE:
            self.barlist_event = BarListEvent.BARLIST_BEAAR
