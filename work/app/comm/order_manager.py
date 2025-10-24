from dataclasses import dataclass, field
from collections import defaultdict
from datetime import date
import asyncio

from core.common.optlog import optlog, log_raise
from core.model.agent import AgentCard
from core.model.order import Order, ReviseCancelOrder
from core.kis.ws_data import TransactionNotice, RCtype, AllYN
from app.comm.conn_agents import ConnectedAgents
from app.comm.comm_handler import dispatch

# server side application
# Orders placed by agents are managed here in a comphrehensive way
# all order records are kept
# to be saved in disc everyday (to be implemented later)
OM_KEEP_DAYS: int = 7 
PENDING_TRNS = 'pending_trns'
INCOMPLETED_ORDERS = 'incompleted_orders'
COMPLETED_ORDERS = 'completed_orders'

@dataclass
class OrderManager:
    """
    # To be used in the server side application 
    # Organize orders from each agent in a structured way
    - keeps only the last `keep_days` worth of data
    - within a day, it keeps increaing and records everything about orders
    - pending trns are due to race condition between order submission and getting the trn (order_no not yet assigned from the server)
    - when new orders are added, need to check if there are any pending trn for the order
    
    # Communication with KIS API server 
    - order submitted: order itself send back (with order_no etc filled) 
    - upon order submission, pending trns are checked and send back 
    - trn received: trn is sent back to the corresponding agent right away

    map = {date: {}, }
    map[date] = {
        code: {
            pending_trns: {
                order_no: [trn, trn, ...],
                order_no: [trn, trn, ...],
                ...
            }
            incompleted_orders: {
                agent_id: [order, order, ...], 
                agent_id: [order, order, ...],
                ...
            }
            completed_orders: {
                agent_id: [order, order, ...], 
                agent_id: [order, order, ...],
                ...
            }
        },
        code: {
            pending_trns: {
                order_no: [trn, trn, ...],
                order_no: [trn, trn, ...],
                ...
            }
            incompleted_orders: {
                agent_id: [order, order, ...], 
                agent_id: [order, order, ...],
                ...
            }
            completed_orders: {
                agent_id: [order, order, ...], 
                agent_id: [order, order, ...],
                ...
            }
        },
        ...
    }

    """
    # defaultdict(list) is useful when there is 1 to N relationship, e.g., multiple notices to one order
    # access to defaultdict would generate key inside with empty list - handle with care
    # lambda is needed as a callable is required (while, list is already a callable)
    # below it does not need to use defaultdict, if setdefault is used everywhere: used here just for revealing the structure

    map: defaultdict = field(default_factory=lambda: defaultdict(
        lambda: defaultdict(
            lambda: {PENDING_TRNS: defaultdict(list), INCOMPLETED_ORDERS: defaultdict(list), COMPLETED_ORDERS: defaultdict(list)}
        )
    ))
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __str__(self):
        if not self.map:
            return "<no map initialized>"
        date = max(self.map.keys())
        res = 'OrderManager - as of date: ' + date + '\n'
        res = res + f'  codes: {list(self.map[date].keys())}\n'
        for code, code_map in self.map[date].items():
            res = res + f'    code: {code}\n'
            res = res + f'      pending_trns: {list(code_map[PENDING_TRNS].keys())}\n'
            res = res + f'      incompleted_orders: { {agent_id: len(orders) for agent_id, orders in code_map[INCOMPLETED_ORDERS].items()} }\n'
            res = res + f'      completed_orders: { {agent_id: len(orders) for agent_id, orders in code_map[COMPLETED_ORDERS].items()} }\n'
        return res

    async def submit_orders_and_register(self, agent: AgentCard, orders: list[Order], trenv, date=date.today().isoformat()):
        if len([o for o in orders if o.submitted]) > 0: log_raise('Orders should have not been submitted ---')

        # below is sequential submission 
        for order in orders: 
            await asyncio.to_thread(order.submit, trenv)
            # send back submission result to the agent right away
            await dispatch(agent, order)  

            async with self._lock:
                date_map = self.map.setdefault(date, {})
                code_map = date_map.setdefault(agent.code, {PENDING_TRNS: {}, INCOMPLETED_ORDERS: {}, COMPLETED_ORDERS: {}})
                code_map[INCOMPLETED_ORDERS].setdefault(agent.id, []).append(order)

                # catch notices that are delivered before order submission is completed
                to_process = code_map[PENDING_TRNS].get(order.order_no, None)
                if to_process:
                    for notice in to_process:
                        order.update(notice, trenv)
                        # send back notice to the agent right away
                        await dispatch(agent, notice)  

                    code_map[PENDING_TRNS].pop(order.order_no) 

            await asyncio.sleep(trenv.sleep)

    async def process_tr_notice(self, notice: TransactionNotice, connected_agents: ConnectedAgents, trenv, date=date.today().isoformat()):
        # reroute notice to the corresponding order
        # notice content handling logic resides in Order class
        # notice could arrive faster than order submit result - should not use order_no (race condition)
        # trn: order = N : 1 relationship
        async with self._lock:
            date_map = self.map.setdefault(date, {})
            code_map = date_map.setdefault(notice.code, {PENDING_TRNS: {}, INCOMPLETED_ORDERS: {}, COMPLETED_ORDERS: {}})

            all_incompleted_orders = []
            for order_lists in code_map[INCOMPLETED_ORDERS].values():
                for order in order_lists:
                    all_incompleted_orders.append(order)

            order = next((o for o in all_incompleted_orders if o.order_no == notice.oder_no), None)
            if order: 
                order.update(notice, trenv)
                # if order is completed or canceled, move to completed_orders
                if order.completed or order.cancelled:
                    # remove from incompleted_orders 
                    try:
                        code_map[INCOMPLETED_ORDERS].get(order.agent_id).remove(order) 
                    except:
                        # let it raise
                        log_raise(f'order.agent_id {order.agent_id} and notice.order_no {notice.order_no} mismatches ---') 
                    # add to completed_orders
                    code_map[COMPLETED_ORDERS].setdefault(order.agent_id, []).append(order)

                agent = connected_agents.get_agent_card_by_id(order.agent_id)
                if agent: # if agent is still connected
                    await dispatch(agent, notice)

            else:
                # otherwise save it to pending_trns
                code_map[PENDING_TRNS].setdefault(notice.order_no, []).append(notice) 

    async def cancel_all_outstanding(self, agent: AgentCard, trenv, date=date.today().isoformat()):
        async with self._lock:
            date_map = self.map.setdefault(date, {})
            code_map = date_map.setdefault(agent.code, {PENDING_TRNS: {}, INCOMPLETED_ORDERS: {}, COMPLETED_ORDERS: {}})
            incompleted_orders = code_map[INCOMPLETED_ORDERS].get(agent.id, [])
            if not incompleted_orders:
                optlog.info(f"No incompleted orders to cancel for agent {agent.id} ---")
                return 

        rc_orders = [] 
        for o in incompleted_orders:
            cancel_order = ReviseCancelOrder(agent_id=agent.id, code=o.code, side=o.side, ord_dvsn=o.ord_dvsn, quantity=o.quantity, order_no=o.price, rc=RCtype.CANCEL, all_yn=AllYN.ALL, original_order=o)
            rc_orders.append(cancel_order)

        await self.submit_orders_and_register(agent, rc_orders, trenv, date)
        optlog.info(f'Cancelling all outstanding {len(rc_orders)} orders for agent {agent.id}...')

    async def closing_checker(self, agent, delay=5, date=date.today().isoformat()): 
        await asyncio.sleep(delay)
        agent_incomplete_orders = self.map.get(date, {}).get(agent.code, {}).get(INCOMPLETED_ORDERS, {}).get(agent.id, [])

        if agent_incomplete_orders:
            optlog.error(f"[Closing Check]: {len(agent_incomplete_orders)} orders not yet completed for agent {agent.id}:")

            not_accepted = [o for o in agent_incomplete_orders if not o.accepted]
            if not_accepted:
                optlog.error(f" --- {len(not_accepted)} orders not yet accepted")
            # may add more checks here ...

        optlog.info("[v] closing check successful")