import asyncio

from .comm_interface import AgentSession
from ..base.tools import list_str, get_listed_market
from ..model.aux_info import AuxInfo
from ..model.dashboard import DashboardManager
from ..kis.ws_data import TransactionPrices

# used in server, and handles AgentSession instances for which agent specific info is received
class ConnectedAgents:
    """
    code_agent_map: {
        code: [agent, agent, ...], 
        code: [agent, agent, ...],
        ...
    }
    agent_id_map: {
        agent_id: agent, 
        ...
    }
    """
    def __init__(self, logger, dashboard_manager:DashboardManager, aux_info:AuxInfo):
        self.logger = logger
        self.code_agent_map: dict[str, list[AgentSession]] = {}
        self.code_market_map = aux_info.code_market_map
        self.agent_id_map: dict[str, AgentSession] = {}
        self.dashboard_manager = dashboard_manager
        self._lock = asyncio.Lock()

    def __str__(self): 
        if self.code_agent_map:
            parts = [
                "[ConnectedAgents]"
            ]
            for c, l in self.code_agent_map.items():
                tl = [f'{a.id} ({a.dp}' for a in l]
                parts.append(f'- {c}: ' + list_str(tl))
            return '\n'.join(parts)
        else: 
            return '[ConnectedAgents] no agents connected'

    async def add(self, agent: AgentSession):
        async with self._lock:
            if self.get_agent_by_id(agent.id):
                return False, f'[ConnectedAgents] agent {agent.id} already registered'

            if not self.dashboard_manager.register_dp(agent.id, agent.dp):
                return False, f'[ConnectedAgents] agent {agent.id} client dashboard port {agent.dp} is already in use'

            self.code_agent_map.setdefault(agent.code, []).append(agent)
            if agent.code not in self.code_market_map:
                self.code_market_map[agent.code] = get_listed_market(agent.code) 
            self.agent_id_map[agent.id] = agent
            return True, f'agent {agent.id} registered in the server'

    async def remove(self, agent: AgentSession):
        async with self._lock:
            agent_list = self.code_agent_map.get(agent.code)
            if agent_list:
                target = next((x for x in agent_list if x.id == agent.id), None)
                if target:
                    agent_list.remove(target)
                    del self.agent_id_map[agent.id]
                    self.dashboard_manager.unregister_dp(target.dp)

                    # clean up emtpy code
                    if not agent_list:
                        del self.code_agent_map[agent.code]
                        del self.code_market_map[agent.code]
                    return f"[ConnectedAgents] agent {agent.id} removed from the server"
            return f"[ConnectedAgents] agent {agent.id} not found"

    def get_agent_by_id(self, id):
        return self.agent_id_map.get(id, None)

    def get_all_agents(self):
        return list(self.agent_id_map.values())

    def get_target_agents_by_trp(self, trp: TransactionPrices):
        code = trp.get_code()
        return self.code_agent_map.get(code, []).copy()
