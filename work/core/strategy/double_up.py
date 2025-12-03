from ..model.strategy_base import StrategyBase
from ..model.strategy_util import StrategyCommand, UpdateEvent
from ..common.optlog import optlog
from ..kis.ws_data import SIDE, ORD_DVSN 

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
    MAX_PURCHASE_QTY = 12
    DOUBLEUP_MULTIPLIER = 2

    SELL_BEP_RETURN_RATE = 0.003 
    BUY_BEP_RETURN_RATE = -0.005

    ###_ cost gap seems exists / study logs
    ###_ bep_return_rate seems cumulative / not correct
    ###_ hard to see initial holding / dbl check if sync is baed on code (agent id)
    ###_ check if agent id is not changed, while code is changed
    ###_ when server is on, check pkl, and load // print when save (opt)

    async def on_update(self, update_event: UpdateEvent):
        optlog.debug(f"{self.code}-{update_event.name}: {self.pm.cur_price:,d} / {self.pm.bep_return_rate:.6f}", name=self.agent_id)

        # ensure no action while pending
        if self.pm.pending_buy_qty > 0 or self.pm.pending_sell_qty > 0: return

        if self.pm.holding_qty == 0:
            # buy once
            q = self.INITIAL_BUY_QTY

            optlog.info(f"INITIAL BUY {q}", name=self.agent_id)
            sc = StrategyCommand(side=SIDE.BUY, ord_dvsn=ORD_DVSN.MARKET, quantity=q)
            sent = await self.order_submit(sc)
            optlog.info(self.pm.order_book, name=self.agent_id)
            return

        # pending sell quantity 
        if self.pm.bep_return_rate is not None and self.pm.bep_return_rate >= self.SELL_BEP_RETURN_RATE:
            # sell all
            q = self.pm.holding_qty  # quantity to sell
            optlog.info(f"SELL ALLL {q}", name=self.agent_id) 
            sc = StrategyCommand(side=SIDE.SELL, ord_dvsn=ORD_DVSN.MARKET, quantity=q)
            sent = await self.order_submit(sc)
            optlog.info(self.pm.order_book, name=self.agent_id)
            return

        if self.pm.bep_return_rate is not None and self.pm.bep_return_rate <= self.BUY_BEP_RETURN_RATE:
            # buy double up to max buy amount

            q = min(self.pm.holding_qty*self.DOUBLEUP_MULTIPLIER, self.MAX_PURCHASE_QTY)
            optlog.info(f"DOUBLE-UP BUY {q}", name=self.agent_id)
            sc = StrategyCommand(side=SIDE.BUY, ord_dvsn=ORD_DVSN.MARKET, quantity=q)
            sent = await self.order_submit(sc)
            optlog.info(self.pm.order_book, name=self.agent_id)
            return

