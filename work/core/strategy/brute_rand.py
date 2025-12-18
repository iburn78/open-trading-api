import asyncio
import random

from ..common.optlog import optlog
from ..model.strategy_base import StrategyBase
from ..model.strategy_util import UpdateEvent
from ..kis.ws_data import SIDE, ORD_DVSN 

class BruteForceRandStrategy(StrategyBase):
    """
    Buy / sell shares at a random time
    """
    def __init__(self):
        super().__init__() 
        self.run_once = False
    
    async def on_update(self, update_event: UpdateEvent):
        if update_event != UpdateEvent.PRICE_UPDATE:
            optlog.debug(f"{self.code}-{update_event.name}", name=self.agent_id)

        # q = random.randint(1, 5)
        if self.run_once:
            return
        self.run_once=True

        sc1 = self.create_an_order(side=SIDE.BUY, ord_dvsn=ORD_DVSN.LIMIT, price=520000, quantity=10)
        sc2 = self.create_an_order(side=SIDE.BUY, ord_dvsn=ORD_DVSN.LIMIT, price=515000, quantity=10)
        sc3 = self.create_an_order(side=SIDE.BUY, ord_dvsn=ORD_DVSN.LIMIT, price=505000, quantity=5)
        sc4 = self.create_an_order(side=SIDE.BUY, ord_dvsn=ORD_DVSN.LIMIT, price=505000, quantity=5)

        [sc1, sc2, sc3, sc4] = await self.execute_rebind([sc1, sc2, sc3, sc4])
        await asyncio.sleep(random.randint(1, 2))

        # cancel test
        optlog.info(f'cancel order')
        co = sc2.make_a_cancel_order(partial=True, to_cancel_qty=20)
        co = await self.execute(co)
        optlog.info(f'cancel {co.order_no} {co.original_order}: {co}')


        ###_ in case of partial cancel
        ###_ how trn is arrived
        ###_ how to reflect to the order manager and order book: both has to be updated
        ###_ add name to tasks
        return
        ###_ study how to handle below cases: 
        '''
        1218_130457.384 [ERROR] sv> kis_auth>
-------------------------------
Error in response: 200 url=/uapi/domestic-stock/v1/trading/order-rvsecncl
rt_cd: 1 / msg_cd: 40430000 / msg1: 모의투자 취소수량이 취소가능수량을 초과합니다.-------------------------------
1218_130457.787 [WARN] sv> B2_> [CancelOrder] order submit response empty, uid c37b0dc0-9ffc-4496-a5ad-911ad364c65f
1218_130458.002 [I] sv> ----------submitted-----------
1218_130458.004 [I] sv> [O] 000660   B2_   none 18130457.335 P       0 Q   20 pr    0 BUY LIM SOR ______ ftap:     0       0           0        0
1218_130516.500 [I] sv> [Server] dashboard
        


###_ handle below too: server restart etc
        1218_154623.105 [ERROR] sv> kis_auth> Connection exception >> no close frame received or sent

        '''