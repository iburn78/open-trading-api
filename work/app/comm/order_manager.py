from dataclasses import dataclass, field
from typing import Callable

from core.common.optlog import optlog
from core.model.agent import AgentCard
from core.model.order import Order
from core.kis.ws_data import TransactionNotice

@dataclass
class OrderManager:
    """
    organize orders from each agent in a structured way
    - to find the agent from a TransactionNotice (trn) using oderno and code

    map = {
        code: {
            pending_trns: [trn, trn, ...],
            agents: {
                agent_id: [orderno, orderno, ...]
                agent_id: [orderno, orderno, ...]
                ...
            }
        },
        code: {
            pending_trns: [trn, trn, ...],
            agents: {
                agent_id: [orderno, orderno, ...]
                agent_id: [orderno, orderno, ...]
                ...
            }
        },
        ...
    }
    """
    map: dict = field(default_factory=dict)

    def add_agent_orders(self, agent: AgentCard, orders: list[Order]):
        code_map = self.map.setdefault(agent.code, {'pending_trns': [], 'agents': {}})
        agent_map = code_map['agents'].setdefault(agent.id, [])

        for order in orders:
            if order.order_no not in agent_map:
                agent_map.append(order.order_no)
            else: 
                optlog.warning(f"Order {order.order_no} from agent {agent.id} already registered in OrderManager ---")

    def add_pending_trn(self, trn: TransactionNotice):
        code_map = self.map.setdefault(trn.code, {'pending_trns': [], 'agents': {}})
        pending_trns = code_map['pending_trns']
        pending_trns.append(trn)


    def get_agent_from_trn(self, trn: TransactionNotice):

        pass