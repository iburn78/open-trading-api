import asyncio
from dataclasses import dataclass, field

from core.common.optlog import log_raise
from core.model.agent import AgentCard
from core.kis.ws_data import TransactionPrices

# used in server 
@dataclass
class ConnectedAgents:
    code_agent_card_dict: dict[str, list[AgentCard]]= field(default_factory=dict) 
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __str__(self): 
        if self.code_agent_card_dict:
            parts = [
                "[ConnectedAgents]"
            ]
            for c, l in self.code_agent_card_dict.items():
                parts.append(f'    {c}: {[(a.id, a.client_port) for a in l]}')
            return '\n'.join(parts)
        else: 
            return '[ConnectedAgents] no agents connected'

    async def add(self, agent_card: AgentCard):
        async with self._lock:
            if not agent_card.client_port:
                log_raise(f'Client port is not assigned for agent {agent_card.id} --- ')

            if self.get_agent_card_by_id(agent_card.id):
                return False, f'[ConnectedAgents-warning] agent_card {agent_card.id} already registered --- '

            if self.get_agent_card_by_port(agent_card.client_port):
                log_raise(f'Client port is {agent_card.client_port} is alreay in use --- ')

            self.code_agent_card_dict.setdefault(agent_card.code, []).append(agent_card)
            return True, f'agent_card {agent_card.id} registered in the server'

    async def remove(self, agent_card: AgentCard):
        if not agent_card: 
            return 

        async with self._lock:
            agent_card_list = self.code_agent_card_dict.get(agent_card.code)
            if not agent_card_list:
                return f"[ConnectedAgents-warning] agent_card {agent_card.id} not found"

            # for a code, there cannot be too many agents; so the following next() efficieny is fine
            target = next((x for x in agent_card_list if x.id == agent_card.id), None)
            if target:
                agent_card_list.remove(target)
                # clean up emtpy code
                if not agent_card_list:
                    del self.code_agent_card_dict[agent_card.code]
                return f"agent_card {agent_card.id} removed from the server"
            return f"[ConnectedAgents-warning] agent_card {agent_card.id} not found"

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

    def get_target_agents_by_trp(self, trp: TransactionPrices):
        code = trp.trprices['MKSC_SHRN_ISCD'].iat[0]
        return self.code_agent_card_dict.get(code, [])