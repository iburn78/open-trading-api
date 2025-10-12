import pandas as pd
from gen_tools import optlog
from kis_tools import TransactionPrices, Order, OrderList, ORD_DVSN
from local_comm import PersistentClient
from dataclasses import dataclass, field
import asyncio
from strategy import TradeTarget

@dataclass
class AgentCard: # an agent's business card (e.g., agents submit their business cards in registration)
    id: str
    code: str

    # server managed info
    client_port: str | None = None # assigned by the server/OS 

@dataclass
class Agent:
    id: str
    code: str

    # temporary vars for trading stretegy - need review 
    target_return_rate: float = 0.0
    strategy: str | None = None # to be implemented
    assigned_cash_t_2: int = 0 # available cash for trading
    holding_quantity: int = 0
    total_cost_incurred: int = 0
    agent_orderlist: OrderList = field(default_factory=OrderList)

    # temporary var for performance measure testing - need review 
    stats: dict = field(default_factory=dict)

    # for server communication
    card: AgentCard = field(default_factory=lambda: AgentCard(id="", code=""))
    _registered: bool = False
    client: PersistentClient = field(default_factory=PersistentClient)
    _connected: bool = False
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self):
        # keep AgentCard consistent with Agent's id/code
        self.card.id = self.id
        self.card.code = self.code

        self.stats = {
            'key_data': 0, 
            'count': 0,
        }
    async def connect(self):
        await self.client.connect()
        self._connected = True
        if not self._registered:
            resp = await self.client.send_command("register_agent_card", request_data=self.card)
            self._registered = True
            optlog.info(resp.get('response_status'))

    # for graceful close 
    async def close(self): 
        if self._registered:
            resp = await self.client.send_command("remove_agent_card", request_data=self.card)
            self._registered = False
            optlog.info(resp.get('response_status'))
        await self.client.close()
        self._connected = False

    async def run(self):
        """Keeps the agent alive until stopped externally or via close()."""
        try:
            await self.connect()
            await self._stop_event.wait()  # wait until .close() is called
        except asyncio.CancelledError:
            optlog.info(f"{self.id} cancelled")
        finally:
            await self.close()

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
        order = Order(self.code, side, quantity, ord_dvsn, price)
        ######### IMPLEMENT AND TEST THIS ##############
        ######### IMPLEMENT AND TEST THIS ##############
        ######### IMPLEMENT AND TEST THIS ##############
        ######### IMPLEMENT AND TEST THIS ##############
        ######### IMPLEMENT AND TEST THIS ##############

    def on_broadcast(self, msg):
        print('in call back ---------')
        print(msg)


# used in server on AgentCard
@dataclass
class ConnectedAgents:
    code_agent_card_dict: dict[str, list[AgentCard]]= field(default_factory=dict) 
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def add(self, agent_card):
        async with self._lock:
            agent_card_list = self.code_agent_card_dict.setdefault(agent_card.code, [])
            # compares based on data between dataclass instances
            if agent_card not in agent_card_list: 
                agent_card_list.append(agent_card)
                msg = f'agent_card {agent_card} registered in the server'
            else:
                msg = f'[Warning] agent_card {agent_card} already registered --- '
            return msg

    async def remove(self, agent_card):
        async with self._lock:
            agent_card_list = self.code_agent_card_dict.get(agent_card.code)
            if agent_card_list:
                try:
                    agent_card_list.remove(agent_card) 
                    msg = f'agent_card {agent_card} removed from the server'
                except ValueError:
                    msg = f'[Warning] agent_card {agent_card} does not exist but removal attempted ---- '
                # Clean up empty list
                if not agent_card_list:
                    del self.code_agent_card_dict[agent_card.code]
            else:
                msg = f'[Warning] agent_card {agent_card} does not exist but removal attepmted ---- '
            return msg
    
    def get_agent_cards_by_code(self, code):
        return self.code_agent_card_dict.get(code)

    def get_agent_card_by_id(self, id):
        for code, list in self.code_agent_card_dict.items():
            for agent_card in list:
                if agent_card.id == id:
                    return agent_card
        return None

    ###### SHOULD Implement this #############------------------------
    ###### SHOULD Implement this #############------------------------
    ###### SHOULD Implement this #############------------------------
    async def process_tr_prices(self, trp: TransactionPrices):
        async with self._lock:
            code = trp.trprices['MKSC_SHRN_ISCD'].iat[0]
            for agent in self.code_agent_card_dict.get(code, []):
                print(agent.id)
                print(agent.code)
                print(trp)


# Refine why this is needed and what to do
@dataclass
class AgentManager:
    trade_target: TradeTarget
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
