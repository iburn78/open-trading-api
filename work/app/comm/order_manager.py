from dataclasses import dataclass, field
from collections import defaultdict
from datetime import date
import asyncio

from core.common.optlog import optlog
from core.model.agent import AgentCard
from core.model.order import Order
from core.kis.ws_data import TransactionNotice



# orderlist should reside within OrderManager, not in AgentCard
@dataclass
class OrderManager:
    """
    organize orders from each agent in a structured way
    - to find the agent from a TransactionNotice (trn) using oder_no and code
    - Keeps only the last `keep_days` worth of data
    
    map = {date: {}, }
    map[date] = {
        code: {
            pending_trns: [trn, trn, ...],
            agents: {
                agent_id: [order_no, order_no, ...] or OrderList 
                agent_id: [order_no, order_no, ...]
                ...
            }
        },
        code: {
            pending_trns: [trn, trn, ...],
            agents: {
                agent_id: [order_no, order_no, ...]
                agent_id: [order_no, order_no, ...]
                ...
            }
        },
        ...
    }

    """
    keep_days: int = 7 # may save in the disc (to be implemented later)
    map: defaultdict = field(default_factory=lambda: defaultdict(
        lambda: defaultdict(
            lambda: {"pending_trns": [], "agents": defaultdict(list)}
        )
    ))
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def add_agent_orders(self, agent: AgentCard, orders: list[Order], date=date.today().isoformat()):
        async with self._lock:
            date_map = self.map.setdefault(date, {})
            code_map = date_map.setdefault(agent.code, {'pending_trns': [], 'agents': {}})
            agent_map = code_map['agents'].setdefault(agent.id, [])

            for order in orders:
                if order.order_no not in agent_map:
                    agent_map.append(order.order_no)
                else: 
                    optlog.error(f"Order {order.order_no} from agent {agent.id} already registered in OrderManager ---")

    # pending TransactionNotice (trn) are due to race condition between order submission and getting the trn
    # when new orders are added, check if there are any pending trn for the same code, and assign the agent
    async def add_pending_trn(self, trn: TransactionNotice, date=date.today().isoformat()):
        async with self._lock:
            date_map = self.map.setdefault(date, {})
            code_map = date_map.setdefault(trn.code, {'pending_trns': [], 'agents': {}})
            pending_trns = code_map['pending_trns']
            pending_trns.append(trn)

    async def get_agent_id_from_trn(self, trn: TransactionNotice, date=date.today().isoformat()) -> AgentCard | None:
        async with self._lock:
            order_no = trn.oder_no
            date_map = self.map.setdefault(date, {})
            code_map = date_map.setdefault(trn.code, {'pending_trns': [], 'agents': {}})
            for agent_id, order_nos in code_map['agents'].items():
                if order_no in order_nos:
                    return agent_id
            return None
