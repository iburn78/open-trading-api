import pandas as pd
import asyncio
from dataclasses import dataclass, field

from .order import Order, OrderList
from .client import PersistentClient
from ..common.optlog import optlog, log_raise
from ..kis.ws_data import ORD_DVSN, TransactionNotice, TransactionPrices

@dataclass
class AgentCard: # an agent's business card (e.g., agents submit their business cards in registration)
    id: str
    code: str

    # server managed info / may change per connection
    # e.g., server memos additional info to the agent's business card
    client_port: str | None = None # assigned by the server/OS 
    writer: object | None = None 
    orderlist: OrderList = field(default_factory=OrderList)

@dataclass
class Agent:
    # id and code do not change for the lifetime
    id: str
    code: str
    orderlist: OrderList = field(default_factory=OrderList)

    # temporary vars for trading stretegy - need review 
    target_return_rate: float = 0.0
    strategy: str | None = None # to be implemented
    assigned_cash_t_2: int = 0 # available cash for trading
    holding_quantity: int = 0
    total_cost_incurred: int = 0

    # temporary var for performance measure testing - need review 
    stats: dict = field(default_factory=dict)

    # for server communication
    card: AgentCard = field(default_factory=lambda: AgentCard(id="", code=""))
    client: PersistentClient = field(default_factory=PersistentClient)
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    _ready_event: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self):
        # keep AgentCard consistent with Agent's id/code
        self.card.id = self.id
        self.card.code = self.code

        self.client.on_dispatch = self.on_dispatch

        self.stats = {
            'key_data': 0, 
            'count': 0,
        }

    async def run(self, **kwargs):
        """Keeps the agent alive until stopped. """
        await self.client.connect()

        resp = await self.client.send_command("register_agent_card", request_data=self.card)
        optlog.info(resp.get('response_status'))
        if not resp.get('response_success'):
            await self.client.close()
            return 

        resp = await self.client.send_command("subscribe_trp_by_agent_card", request_data=self.card)
        optlog.info(resp.get('response_status'))

        self._ready_event.set()

        try:
            await self._stop_event.wait()  # wait until .close() is called
        except asyncio.CancelledError:
            optlog.info(f"Agent {self.id} cancelled")
        finally:
            await self.client.close()

    def report_performance(self): 
        pass

    def update_stats(self, trp: TransactionPrices):
        self.stats['key_data'] += int(trp.trprices['CNTG_VOL'].iat[0])
        self.stats['count'] += 1
    
    def make_order(self):
        side = 'buy'
        quantity = 10
        ord_dvsn = ORD_DVSN.MARKET
        price = 0
        order = Order(self.id, self.code, side, quantity, ord_dvsn, price)
        return order
        ######### IMPLEMENT AND TEST THIS ##############
        ######### IMPLEMENT AND TEST THIS ##############
        ######### IMPLEMENT AND TEST THIS ##############
        ######### IMPLEMENT AND TEST THIS ##############
        ######### IMPLEMENT AND TEST THIS ##############

    def on_dispatch(self, msg):
        # first classify what is receieved
        pass
        # print(f'in call async back {self.code}---------')
        # print(msg)


# used in server on AgentCard
@dataclass
class ConnectedAgents:
    code_agent_card_dict: dict[str, list[AgentCard]]= field(default_factory=dict) 
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def add(self, agent_card: AgentCard):
        async with self._lock:
            if not agent_card.client_port:
                log_raise(f'Client port is not assigned for agent {agent_card.id} --- ')

            if self.get_agent_card_by_id(agent_card.id):
                return f'[Warning] agent_card {agent_card.id} already registered --- ', False

            if self.get_agent_card_by_port(agent_card.client_port):
                log_raise(f'Client port is {agent_card.client_port} is alreay in use --- ')

            self.code_agent_card_dict.setdefault(agent_card.code, []).append(agent_card)
            return f'agent_card {agent_card.id} registered in the server', True

    async def remove(self, agent_card: AgentCard):
        if not agent_card: 
            return 

        async with self._lock:
            agent_card_list = self.code_agent_card_dict.get(agent_card.code)
            if not agent_card_list:
                return f"[Warning] agent_card {agent_card.id} not found"

            target = next((x for x in agent_card_list if x.id == agent_card.id), None)
            if target:
                agent_card_list.remove(target)
                # clean up emtpy code
                if not agent_card_list:
                    del self.code_agent_card_dict[agent_card.code]
                return f"agent_card {agent_card.id} removed from the server"
            return f"[Warning] agent_card {agent_card.id} not found"

    def get_agent_card_by_port(self, port):
        for code, list in self.code_agent_card_dict.items():
            for agent_card in list:
                if agent_card.client_port == port:
                    return agent_card
        return None   # This case could be an agent connected and port is assigned but registration failed (e.g., duplication) so not in connected_agent.

    def get_agent_card_by_id(self, id):
        for code, list in self.code_agent_card_dict.items():
            for agent_card in list:
                if agent_card.id == id:
                    return agent_card
        return None

    def get_all_agents(self):
        res = []
        for code, list in self.code_agent_card_dict.items():
            for i in list: 
                res.append(i) 
        return res

    def get_target_agents(self, trp: TransactionPrices):
        code = trp.trprices['MKSC_SHRN_ISCD'].iat[0]
        return self.code_agent_card_dict.get(code, [])



# Refine why this is needed and what to do
# Refine why this is needed and what to do
# Refine why this is needed and what to do
# Refine why this is needed and what to do
@dataclass
class AgentManager:
    # trade_target: TradeTarget
    target_df: pd.DataFrame = None
    agent_list: list = field(default_factory=list)

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
