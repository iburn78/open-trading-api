from gen_tools import *
from kis_tools import TransactionPrices, Order, OrderList, ORD_DVSN
from dataclasses import dataclass, field
import asyncio
from strategy import *

@dataclass
class Agent:
    id: str
    code: str
    target_return_rate: float = 0.0
    strategy: str | None = 'strategy for this agent'  # to be implemented
    assigned_cash_t_2: int # available cash for trading
    holding_quantity: int = 0
    total_cost_incurred: int = 0
    active: bool = False

    # may introduce a class to measure performance
    stats: dict = field(default_factory=dict)
    agent_orderlist: OrderList = field(default_factory=OrderList)

    def __post_init__(self):
        self.stats = {
            'key_data': 0, 
            'count': 0,
        }

    def report(self): # to AgentManager
        pass

    def report_performance(self): # to update overall performance
        pass

    def update_stats(self, trp: TransactionPrices):
        self.stats['key_data'] += int(trp.trprices['CNTG_VOL'].iat[0])
        self.stats['count'] += 1
    
    def make_order(self):
        side = 'buy'
        quantity = 10
        ord_dvsn = ORD_DVSN.MARKET
        price = 0
        order = Order(self.code, side, quantity, ord_dvsn, price)




@dataclass
class AgentManager:
    trade_target: TradeTarget
    target_df: pd.DataFrame = None
    agent_list: list = field(default_factory=list)
    # the _lock is instnace variable, which means it protects the agent_list in each AgentManager instance
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self):
        self.target_df = self.trade_target.target_df
        self._populate_agents()

    # initially populating agents - have to be used only once
    def _populate_agents(self):
        for code in self.target_df['code']:
            agent = Agent(
                code=code,
                assigned_cash_t_2=self.target_df.loc[self.target_df['code']==code, 'cash_t_2'].iat[0],
            )
            self.agent_list.append(agent)

    def get_agent(self, code):
        return next((agent for agent in self.agent_list if agent.code == code), None)

    def activate_agent(self, code): 
        agent = self.get_agent(code)
        if agent: 
            if not agent.active:
                optlog.info(f'Agent for {code} activated')
                agent.active = True
                return True
            else: 
                optlog.warning(f'Agent for {code} is already active - check logic')
                return False
        else: 
            optlog.warning(f"No such agent for {code} - check the code is in trade target")
            return False

    def deactivate_agent(self, code):
        agent = self.get_agent(code)
        if agent: 
            if agent.active:
                optlog.info(f'Agent for {code} deactivated')
                agent.active = False
                return True
            else: 
                optlog.warning(f'Agent for {code} is already inactive - check logic')
                return False

        else: 
            optlog.warning(f"No such agent for {code} - check the code is in trade target")
            return False
    
    def agent_status(self):
        # ---------------------------------
        # active agents: 
        # inactive agents: 
        # performance summary (if handled here)
        # ---------------------------------
        pass

    async def process_tr_prices(self, trp: TransactionPrices):
        code = trp.trprices['MKSC_SHRN_ISCD'].iat[0]
        async with self._lock:
            agent = next((agent for agent in self.agent_list if agent.code == code), None)
            if agent is None:
                log_raise(f"No matching agent for code {code} ---")
            agent.update_stats(trp)