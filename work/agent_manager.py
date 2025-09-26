from gen_tools import *
get_logger("agent_manager", "log/agent_manager.log")

from kis_tools import *
from local_comm import *

@dataclass
# --------------------------
# DEVELOP FURTHER 
# --------------------------
class TradeTarget:
    # may read this from an Excel file
    target_codes: list = field(default_factory=list)
    max_exposure: dict = field(default_factory=dict) # {code: max_inv, }

    def __post_init__(self):
        self.target_codes = ['005930', '000660', '001440', '000240', '003230']

    def get_target_codes(self):
        return self.target_codes

    def get_max_exposure(self, code, the_account: Account = None):
        # _safety_margin = 0.1 # how much to leave cach in the account 
        # _cash_t_2 = int(the_account.cash.t_2*(1-_safety_margin)/_max) # round down for cash
        # some code
        max_exp = 30_000_000
        return max_exp

@dataclass
class Agent:
    id: str
    code: str
    cash_t_2: int # available cash for trading

    def report(self): # to AgentManager
        pass

    def report_performance(self): # to update overall performance
        pass

@dataclass
class AgentManager:
    book: pd.DataFrame = None
    agents: list = field(default_factory=list)

    # agent:code = 1:1
    columns = [
        'agent_id', 'code', 'max_exposure', 'cash_t_2', 'quantity', 'avg_price', 'bep_price', 'active'
    ]
    file = 'data/agent_book.pkl'

    def __post_init__(self):
        self.book = pd.DataFrame(columns = self.columns)

    def save(self): 
        self.book.to_pickle(self.file)

    def load(self):
        try: 
            self.book = pd.read_pickle(self.file)
        except FileNotFoundError: 
            optlog.error('agent_book file not found...')

    def _get_agent_id_from_code(self, code):
        return 'agent_'+code

    def load_target_into_book(self, target: TradeTarget):
        for code in target.get_target_codes():
            new_row = {
                'agent_id': self._get_agent_id_from_code(code),
                'code': code,
                'max_exposure': target.get_max_exposure(code),
                'cash_t_2': target.get_max_exposure(code),
                'quantity': 0, 
                'avg_price': 0, 
                'bep_price': 0, 
                'active': False, 
            } 
            self.book.loc[len(self.book)] = new_row

    def sync_with_account(self, the_account: Account):
        # create a lookup dict for holdings: code -> holding
        holdings_map = {h.code: h for h in the_account.holdings}

        # function to get values for each row
        def _get_values(code):
            h = holdings_map.get(code)
            if h:
                return h.quantity, h.avg_price, h.bep_price
            return 0, 0, 0

        # apply to all rows
        self.book[['quantity', 'avg_price', 'bep_price']] = self.book['code'].apply(
            lambda code: pd.Series(_get_values(code))
        )
        self.book['cash_t_2'] = adj_int(self.book['cash_t_2'] - self.book['quantity']*self.book['bep_price'])
    
    def check_cash_t_2_total(self, the_account: Account):
        MAX_USAGE_CASH_T_2 = 0.9 # safety margin on cash_t_2
        max_exposure_exceeded = []
        mask = self.book['cash_t_2'] < 0
        max_exposure_exceeded = self.book.loc[mask, 'code'].tolist() 
        if max_exposure_exceeded:
            optlog.warning(f"Codes exceed the max exposure: {max_exposure_exceeded}") # these agents can only sell...

        cash_t_2_total_allocated = self.book.loc[~mask, 'cash_t_2'].sum() 
        if the_account.cash.t_2*MAX_USAGE_CASH_T_2 <= cash_t_2_total_allocated:
            # this case needs attention in allocating cash
            log_raise("Total allocated exposure exceeds the available cash")
        
        return max_exposure_exceeded

    def get_activated_agent(self, code): # or if there is no agent for a code, create one and activate 
        if code in self.book['code'].values:
            agent_id = self._get_agent_id_from_code(code)
            if self.book.loc[self.book['agent_id'] == agent_id, 'active'].iat[0]: 
                agent = next((agent for agent in self.agents if agent.id == agent_id), None)
                if agent is None: 
                    log_raise(f"Active agent is missing for code {code}")
                return agent
            else: 
                self.book.loc[self.book['agent_id'] == agent_id, 'active'] = True
                agent = Agent(
                    id=agent_id, 
                    code=code,
                    cash_t_2=self.book.loc[self.book['agent_id']==agent_id, 'cash_t_2'].iat[0],
                )
                self.agents.append(agent)
                return agent
        else:
            optlog.error(f"Attempted to get an agent for non requested code {code}")
            pass 
    
    def remove_agent_and_deactivate(self, code):
        if code in self.book['code'].values:
            agent_id = self._get_agent_id_from_code(code)
            if self.book.loc[self.book['agent_id'] == agent_id, 'active'].iat[0]: 
                self.book.loc[self.book['agent_id'] == agent_id, 'active'] = False
                agent = next((a for a in self.agents if a.id == agent_id), None)
                if agent:
                    self.agents.remove(agent)
                return agent
            else: 
                print("No such active agent for code: ", code)
        else:
            print("No such code: ", code)
            pass 


async def main(): 
    # ----------------------------------------------
    # Cancel all outstanding orders in OPT system
    # - There might be other orders in the 한투 system
    # ----------------------------------------------
    await send_command('cancel_orders', None)

    resp = await send_command('get_account', None)
    try:
        the_account = resp['data'] if resp['valid'] else log_raise("the_account retrieval failed")
    except KeyError:
        log_raise("Invalid response format from send_command")

    print(the_account)
    trade_target = TradeTarget()
    agent_manager = AgentManager()
    agent_manager.load_target_into_book(trade_target)
    print(agent_manager.book)
    agent_manager.sync_with_account(the_account)
    print(agent_manager.book)
    agent_manager.check_cash_t_2_total(the_account)
    print(agent_manager.book)
    for code in agent_manager.book['code']:
        a = agent_manager.get_activated_agent(code)
        print(a)
        await asyncio.sleep(1)
    for code in agent_manager.book['code']:
        a = agent_manager.remove_agent_and_deactivate(code)
        print(a)
        await asyncio.sleep(1)
    

if __name__ == "__main__":
    asyncio.run(main())