from ..model.strategy_base import StrategyBase
from ..model.strategy_util import UpdateEvent
from ..model.bar_analysis import SeriesAnalysis, TrendEvent, AnalysisTarget

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
    def __init__(self):
        super().__init__() 
        # bar setting
        self.bar_aggr.reset(aggr_delta_sec=1)
        self.bar_analyzer.reset(num_bar=100) ###_ num_bar has too many meanings... 

    def on_bar_update(self):
        p_lta = SeriesAnalysis.get_last_to_avg(self.bar_analyzer.bars, AnalysisTarget.PRICE)
        p_st = SeriesAnalysis.get_shifted_trend(self.bar_analyzer.bars, AnalysisTarget.PRICE)

        v_lta = SeriesAnalysis.get_last_to_avg(self.bar_analyzer.bars, AnalysisTarget.VOLUME)
        v_st = SeriesAnalysis.get_shifted_trend(self.bar_analyzer.bars, AnalysisTarget.VOLUME)

        p_trend_event = TrendEvent(AnalysisTarget.PRICE, p_lta, p_st, LAST_TO_AVG_THRESHOLD=1.002, SHIFTED_TREND_THRESHOLD=1.0)
        v_trend_event = TrendEvent(AnalysisTarget.VOLUME, v_lta, v_st, LAST_TO_AVG_THRESHOLD=1.1, SHIFTED_TREND_THRESHOLD=1.1)
        self.bar_analyzer.handle_mkt_event(p_trend_event, v_trend_event)

        super().on_bar_update()

    async def on_update(self, update_event: UpdateEvent):
        if update_event != UpdateEvent.PRICE_UPDATE:
            self.logger.info(f"{self.code}-{update_event.name}", extra={"owner": self.agent_id})
        
        if update_event == UpdateEvent.MARKET_EVENT:
            self.logger.info(self.last_market_signal)



