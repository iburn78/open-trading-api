from ..model.strategy_base import StrategyBase
from ..model.strategy_util import UpdateEvent

class NullStr(StrategyBase):
    """
    - doing nothing str 
    """
    def __init__(self):
        super().__init__() 
    
    async def on_update(self, update_event: UpdateEvent):
        if update_event == UpdateEvent.INITIATE:
            self.logger.info(f"Null Strategy initiated: {self.code}: {self.pm.market_prices.current_price:,d} / {self.pm.bep_return_rate:.6f}", extra={"owner":self.agent_id})
