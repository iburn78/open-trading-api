import asyncio

from ..model.agent import AgentCard

class SubscriptionManager:
    """
    Server side application
    Manage subscriptions from agents 
    note: receiving TR notices (ccnl_notice) is subscripted separately
    note: this class assumes that all functions are from one KIS_Functions class instance (handed through the server)
    
    subs_map = {
        func: {
            code: [agent_id, agent_id, ...],
            ...
        },
        ...
    }
    """
    def __init__(self):
        self.subs_map = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    def __str__(self): 
        if self.subs_map:
            parts = [
                "[SubsManager]"
            ]
            for f, d in self.subs_map.items():
                parts.append(f'{f.__name__}: {d}')
            return '\n'.join(parts)
        else: 
            return '[SubsManager] no agent-specific subscriptions'

    # add and subscribe
    async def add(self, agent: AgentCard, func): # func: websocket subscription functions in KIS_Functions 
        async with self._lock:
            func_map = self.subs_map.setdefault(func, {})
            agent_list = func_map.get(agent.code)
            if not agent_list:
                func_map[agent.code] = [agent.id]
                await func(tr_key=agent.code) # execution of subscription 
            elif agent.id not in agent_list:
                agent_list.append(agent.id)
            else:
                return f"agent {agent.id} already subscribed"

            agent.subscriptions.add(func) # agent's own record
            return f"agent {agent.id} subscribed"

    # remove and unsubscribe
    # agent could have multiple subscriptions (i.e., multiple funcs)
    async def remove(self, agent: AgentCard, func=None): # if func = None, remove all
        async with self._lock:
            if func is None:
                res = []
                for f in agent.subscriptions.copy():
                    res.append(await self._remove(agent, f))
                return '\n'.join(res)
            else:
                return await self._remove(agent, func)

    async def _remove(self, agent: AgentCard, func): 
        if func not in self.subs_map:
            return f"[SubsManager] {func.__name__} not found in subscription map"

        func_map = self.subs_map.get(func)
        if agent.code not in func_map:
            return f"[SubsManager] {agent.code} not found under {func.__name__}"

        agent_list = func_map.get(agent.code)
        if agent.id not in agent_list:
            return f"[SubsManager] {agent.id} not subscribed to {agent.code}"

        agent_list.remove(agent.id)
        agent.subscriptions.discard(func)

        # cleanup empty code list
        if not agent_list:
            # (func, code) does not exist, so unsubscribe
            await func(tr_key=agent.code, subs=False) # execution of unsubcription
            del func_map[agent.code]

        # cleanup empty func entry
        if not func_map:
            del self.subs_map[func]

        return f"Removed {agent.id} from {func.__name__} ({agent.code})"