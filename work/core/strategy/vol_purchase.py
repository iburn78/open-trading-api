from ..model.strategy_base import StrategyBase
from ..model.strategy_util import UpdateEvent
from ..model.bar_analysis import VolumeAnalysis, VolumeTrendEvent

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
        self.bar_aggr.reset(aggr_delta_sec=2)
        self.bar_analyzer.reset(num_bar=20) 

    def on_bar_update(self):
        super().on_bar_update()
        va = VolumeAnalysis.get_vol_to_avg(self.bar_analyzer.bars)
        svr = VolumeAnalysis.get_shifted_vol_ratio(self.bar_analyzer.bars)

        mkt_event = VolumeTrendEvent(va, svr, VOLUME_RATIO=1.5, SLOPE_RATIO=1.3)
        self.bar_analyzer.handle_mkt_event(mkt_event)

    async def on_update(self, update_event: UpdateEvent):
        if update_event != UpdateEvent.PRICE_UPDATE:
            self.logger.info(f"{self.code}-{update_event.name}", extra={"owner": self.agent_id})
        
        if update_event == UpdateEvent.MARKET_EVENT:
            self.logger.info(self.last_market_signal)



