from ..model.strategy_base import StrategyBase
from ..model.strategy_util import UpdateEvent

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
    
    async def on_update(self, update_event: UpdateEvent):
        if update_event != UpdateEvent.PRICE_UPDATE:
            self.logger.info(f"{self.code}-{update_event.name}", extra={"owner": self.agent_id})
        
        if update_event == UpdateEvent.VOLUME_TREND_EVENT:
            self.logger.info(self.last_mp_signal)
        
        ###_ may store price trend too




