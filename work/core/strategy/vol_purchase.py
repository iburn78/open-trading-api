from ..model.strategy_base import StrategyBase
from ..model.strategy_util import UpdateEvent
from ..model.bar_analysis import SeriesAnalysis, AnalysisTarget, MarketEvent

class VolumePurchase(StrategyBase):
    """
    - Hypothesis: 
        - real movement happens when there is volume increase 
    - Action: 
        - buy shares when there is movement with volume up
        - sell shares when return is achieved
    - Control
        - limit up to X shares, Y amount
    """
    def __init__(self, aggr_delta_sec=None):
        super().__init__() 
        # bar setting
        self.bar_aggr.reset(aggr_delta_sec=aggr_delta_sec)
        self.bar_analyzer.reset(num_bar=100) ###_ num_bar has too many meanings... 

    def on_bar_update(self):
        p_lta = SeriesAnalysis.get_last_to_avg(self.bar_analyzer.bars, AnalysisTarget.PRICE)
        p_st = SeriesAnalysis.get_shifted_trend(self.bar_analyzer.bars, AnalysisTarget.PRICE)

        v_lta = SeriesAnalysis.get_last_to_avg(self.bar_analyzer.bars, AnalysisTarget.VOLUME)
        v_st = SeriesAnalysis.get_shifted_trend(self.bar_analyzer.bars, AnalysisTarget.VOLUME)

        mkt_event = MarketEvent(p_lta, p_st, v_lta, v_st, 1.0, 1.0, 2.0, 1.3)
        self.bar_analyzer.mark_on_bars(mkt_event)

        super().on_bar_update(mkt_event)

    async def on_update(self, update_event: UpdateEvent):
        if update_event != UpdateEvent.PRICE_UPDATE:
            self.logger.info(f"{self.code}-{update_event.name}", extra={"owner": self.agent_id})
        
        if update_event == UpdateEvent.MARKET_EVENT:
            self.logger.info(self.last_market_signal)



