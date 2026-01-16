from ..kis.ws_data import SIDE, MTYPE 
from ..model.strategy_base import StrategyBase
from ..model.strategy_util import UpdateEvent

class DoubleUpStrategy(StrategyBase):
    """
    - buy shares at a random time
    - if return rate reached a threshold, sell all shares
    - if return rate reduced to another threshold, buy double (up to max buy amount)
    - repeat this
    
    """
    def __init__(self):
        super().__init__() 
    
    INITIAL_BUY_QTY = 1
    MAX_PURCHASE_QTY = 4
    DOUBLEUP_MULTIPLIER = 2

    SELL_BEP_RETURN_RATE = 0.002 
    BUY_BEP_RETURN_RATE = -0.004

    async def on_update(self, update_event: UpdateEvent):
        if update_event != UpdateEvent.PRICE_UPDATE:
            self.logger.info(f"{self.code}-{update_event.name}", extra={"owner": self.agent_id})

        if self.pm.pending_buy_qty > 0 or self.pm.pending_sell_qty > 0: return

        if self.pm.holding_qty == 0:
            # buy once
            q = self.INITIAL_BUY_QTY
            self.logger.info(f"INITIAL BUY {q}", extra={"owner": self.agent_id})
            sc = self.create_an_order(side=SIDE.BUY, mtype=MTYPE.MARKET, price=0, quantity=q)
            await self.execute_rebind(sc)
            return

        # pending sell quantity 
        if self.pm.bep_return_rate is not None and self.pm.bep_return_rate >= self.SELL_BEP_RETURN_RATE:
            # sell all
            q = self.pm.holding_qty  # quantity to sell
            self.logger.info(f"SELL ALL {q}", extra={"owner": self.agent_id})
            sc = self.create_an_order(side=SIDE.SELL, mtype=MTYPE.MARKET, price=0, quantity=q)
            await self.execute_rebind(sc)
            return

        if self.pm.bep_return_rate is not None and self.pm.bep_return_rate <= self.BUY_BEP_RETURN_RATE:
            # buy double up to max buy amount
            q = min(self.pm.holding_qty*self.DOUBLEUP_MULTIPLIER, self.MAX_PURCHASE_QTY)
            self.logger.info(f"DOUBLE-UP BUY {q}", extra={"owner": self.agent_id})
            sc = self.create_an_order(side=SIDE.BUY, mtype=MTYPE.MARKET, price=0, quantity=q)
            await self.execute_rebind(sc)
            return
