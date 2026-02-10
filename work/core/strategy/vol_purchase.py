from ..model.strategy_base import StrategyBase
from ..model.strategy_util import UpdateEvent
from ..model.barlist_analysis import BarListAnalysis, AnalysisTarget, BarListEvent

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
    SELL_BEP_RETURN_RATE = 0.005 
    def __init__(self, bar_delta=None, **kwargs):
        super().__init__() 
        # bar setting
        self.pl = kwargs.get('pl', 0.5)
        self.ps = kwargs.get('ps', 0.3)
        self.vl = kwargs.get('vl', 1.3)
        self.vs = kwargs.get('vs', 1.1)

        self.bar_builer.reset(bar_delta=bar_delta)
        self.barlist.reset(num_bar=100) 

    def on_barlist_update(self):
        p_lta = BarListAnalysis.get_last_to_avg(self.barlist.barlist, AnalysisTarget.PRICE)
        p_st = BarListAnalysis.get_shifted_trend(self.barlist.barlist, AnalysisTarget.PRICE)

        v_lta = BarListAnalysis.get_last_to_avg(self.barlist.barlist, AnalysisTarget.VOLUME)
        v_st = BarListAnalysis.get_shifted_trend(self.barlist.barlist, AnalysisTarget.VOLUME)

        self.check_barlist_event(p_lta=p_lta, p_st=p_st, v_lta=v_lta, v_st=v_st, P_LTA_abs_pct=self.pl, P_ST_abs_pct=self.ps, V_LTA_th=self.vl, V_ST_th=self.vs)
        super().on_barlist_update()

    async def on_update(self, update_event: UpdateEvent):
        if update_event != UpdateEvent.PRICE_UPDATE:
            self.logger.info(f"{self.code}-{update_event.name}", extra={"owner": self.agent_id})
        
        if update_event == UpdateEvent.BARLIST_EVENT:
            self.logger.info(self.barlist_status, extra={"owner": self.agent_id})

        if self.pm.pending_buy_qty > 0 or self.pm.pending_sell_qty > 0: return 

        if update_event == UpdateEvent.BARLIST_EVENT:
            if self.barlist_status.barlist_event == BarListEvent.BARLIST_BULL: 
                self.logger.info(f"BUY 1", extra={"owner": self.agent_id})
                sc = self.market_buy(quantity=1)
                await self.execute_rebind(sc)
                return
            elif self.barlist_status.barlist_event == BarListEvent.BARLIST_BEAAR: 
                if self.pm.holding_qty > 0:
                    self.logger.info(f"SELL 1", extra={"owner": self.agent_id})
                    sc = self.market_sell(quantity=1)
                    await self.execute_rebind(sc)
                    return
        
        if self.pm.bep_return_rate is not None and self.pm.bep_return_rate >= self.SELL_BEP_RETURN_RATE:
            # sell all
            q = self.pm.holding_qty  # quantity to sell
            if q > 0:
                self.logger.info(f"SELL ALL {q}", extra={"owner": self.agent_id})
                sc = self.market_sell(quantity=q)
                await self.execute_rebind(sc)
                return

        



