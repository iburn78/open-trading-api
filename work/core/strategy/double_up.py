import asyncio

from .strategy import StrategyBase
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

    async def on_update(self, update_event: UpdateEvent):
        ###_ e.g., referring to the price(marekt) data and pm(performance) data
        if update_event == UpdateEvent.PRICE_UPDATE:
            optlog.debug(f"{self.code}: {self.pm.cur_price} / {self.pm.return_rate}", name=self.agent_id)
        else:
            # does not mean all updates are logged
            optlog.debug(f"on_update: {update_event}", name=self.agent_id)
        if self.pm.holding_qty + self.pm.pending_buy_qty == 0:
            # buy once
            q = 1  # quantity to buy
            optlog.info(f"INITIAL BUY {q}", name=self.agent_id)
            sc = StrategyCommand(side=SIDE.BUY, ord_dvsn=ORD_DVSN.MARKET, quantity=q)
            sent = await self.order_submit(sc)
            optlog.info(self.pm.order_book, name=self.agent_id)
            return
        if self.pm.return_rate is not None and self.pm.return_rate >= 0.002:
            # sell all
            q = self.pm.holding_qty  # quantity to sell
            optlog.info(f"SELL ALLL {q}", name=self.agent_id) 
            sc = StrategyCommand(side=SIDE.SELL, ord_dvsn=ORD_DVSN.MARKET, quantity=q)
            sent = await self.order_submit(sc)
            optlog.info(self.pm.order_book, name=self.agent_id)
            return
        if self.pm.return_rate is not None and self.pm.return_rate <= -0.002:
            # buy double up to max buy amount
            max_purchse = 12
            q = max(self.pm.holding_qty*2, self.pm.max_market_buy_amt) 
            optlog.info(f"DOUBLE-UP BUY {q}", name=self.agent_id)
            sc = StrategyCommand(side=SIDE.BUY, ord_dvsn=ORD_DVSN.MARKET, quantity=q)
            sent = await self.order_submit(sc)
            optlog.info(self.pm.order_book, name=self.agent_id)
            return

