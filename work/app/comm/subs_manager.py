from dataclasses import dataclass, field
from typing import Callable
import asyncio

from core.model.agent import AgentCard

@dataclass
class SubscriptionManager:
    """
    map = {
        func: {
            code: [agent_id, agent_id, ...],
            ...
        },
        ...
    }
    """
    map: dict = field(default_factory=dict)
    kws: object = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def add(self, func: Callable, agent_card: AgentCard):
        async with self._lock:
            func_map = self.map.setdefault(func, {})
            agent_list = func_map.get(agent_card.code)
            if not agent_list:
                func_map[agent_card.code] = [agent_card.id]
                # new entry of (func, code), so subscribe 
                self._subscribe(func, agent_card.code)
            else:
                if agent_card.id not in agent_list:
                    agent_list.append(agent_card.id)

    async def remove(self, func: Callable, agent_card: AgentCard):
        if not agent_card:
            return

        async with self._lock:
            # if this func or code not in map, nothing to do
            if func not in self.map:
                return f"[Warning] {func.__name__} not found in subscription map"

            func_map = self.map[func]
            if agent_card.code not in func_map:
                return f"[Warning] {agent_card.code} not found under {func.__name__}"

            agent_list = func_map[agent_card.code]
            if agent_card.id not in agent_list:
                return f"[Warning] {agent_card.id} not subscribed to {agent_card.code}"

            # remove id
            agent_list.remove(agent_card.id)

            # cleanup empty code list
            if not agent_list:
                # (func, code) does not exist, so unsubscribe
                self._unsubscribe(func, agent_card.code)
                del func_map[agent_card.code]

            # cleanup empty func entry
            if not func_map:
                del self.map[func]

            return f"Removed {agent_card.id} from {func.__name__} ({agent_card.code})"
    
    async def remove_agent(self, agent_card: AgentCard):
        for key in list(self.map.keys()): # list is necessary as self.remove modifies the map while iterating
            await self.remove(key, agent_card)

    def _subscribe(self, func: Callable, code):
        self.kws.subscribe(request=func, data=code)

    def _unsubscribe(self, func: Callable, code):
        self.kws.unsubscribe(request=func, data=code)