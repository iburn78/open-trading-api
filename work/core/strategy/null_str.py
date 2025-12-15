from ..model.strategy_base import StrategyBase
from ..model.strategy_util import UpdateEvent
from ..common.optlog import optlog

class NullStr(StrategyBase):
    """
    - doing nothing str 
    """
    def __init__(self):
        super().__init__() 
    
    async def on_update(self, update_event: UpdateEvent):
        if update_event == UpdateEvent.INITIATE:
            optlog.debug(f"Null Strategy Initiated: {self.code}: {self.pm.market_prices.current_price:,d} / {self.pm.bep_return_rate:.6f}", name=self.agent_id)
