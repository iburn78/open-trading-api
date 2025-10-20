from dataclasses import dataclass, field
import pandas as pd

from core.common.optlog import optlog
from core.model.agent import Agent

# ##############################################################
# Refine why this is needed and what to do
# ##############################################################

@dataclass
class AgentManager:
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