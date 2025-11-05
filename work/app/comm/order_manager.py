from dataclasses import dataclass, field
from collections import defaultdict
from datetime import date
import asyncio
import pickle
import os
import time

from core.common.setup import data_dir, disk_save_period
from core.common.optlog import optlog, log_raise
from core.model.agent import AgentCard, dispatch
from core.model.order import Order, ReviseCancelOrder
from core.kis.ws_data import TransactionNotice, RCtype, AllYN
from app.comm.conn_agents import ConnectedAgents

# server side application
# Orders placed by agents are managed here in a comphrehensive way
# all order records are kept
# to be saved in disc everyday (to be implemented later)
OM_KEEP_DAYS: int = 7 

# naming constants
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

    map = {date_: {}, }
    map[date_] = {
        code: {
            pending_trns: {
                order_no: [trn, trn, ...],
                order_no: [trn, trn, ...],
                ...
            }
            incompleted_orders: {
                agent_id: {order_no: order, order_no: order}
                agent_id: {order_no: order, order_no: order}
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
                agent_id: {order_no: order, order_no: order}
                agent_id: {order_no: order, order_no: order}
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
            lambda: {PENDING_TRNS: defaultdict(list), INCOMPLETED_ORDERS: defaultdict(dict), COMPLETED_ORDERS: defaultdict(list)}
        )
    ))

    # Each key gets its own asyncio.Lock automatically
    # key = code
    _locks: dict[str, asyncio.Lock] = field(
        default_factory=lambda: defaultdict(lambda: asyncio.Lock())
    )

    def __post_init__(self): 
        self.sec = lambda t: int(t[:2])*3600 + int(t[2:4])*60 + int(t[4:6])
        self._pending_trns_task = None

    def __str__(self):
        if not self.map:
            return "(no map initialized)"
        date_ = max(self.map.keys())
        res = 'OrderManager:\n'
        res = res + f'codes: {list(self.map[date_].keys())}\n'
        for code, code_map in self.map[date_].items():
            res = res + f'- {code}\n'
            res = res + f'  {PENDING_TRNS}: {list(code_map[PENDING_TRNS].keys())}\n'
            res = res + f'  {INCOMPLETED_ORDERS}: { {agent_id: len(orders_dict) for agent_id, orders_dict in code_map[INCOMPLETED_ORDERS].items()} }\n'
            for agent_id, orders_dict in code_map[INCOMPLETED_ORDERS].items():
                for k, o in orders_dict.items():
                    res = res + f'  - {agent_id}: {o}\n'
            res = res + f'  {COMPLETED_ORDERS}: { {agent_id: len(orders) for agent_id, orders in code_map[COMPLETED_ORDERS].items()} }\n'
        return res

    async def submit_orders_and_register(self, agent: AgentCard, orders: list[Order], trenv, date_=None):
        if len([o for o in orders if o.submitted]) > 0: log_raise('Orders should have not been submitted ---', name=agent.id)
        if date_ is None: date_=date.today().isoformat()

        # below is sequential submission 
        # may consider to concurrently submit: KIS might not allow this
        # tasks = []
        # for o in orders:
        #     task = asyncio.create_task(...)  
        #     tasks.append(task)
        # await asyncio.gather(*tasks, return_exceptions=True)
        for order in orders: 
            try:
                await asyncio.to_thread(order.submit, trenv)
                if order.order_no:
                    async with self._locks[order.code]:
                        date_map = self.map.setdefault(date_, {})
                        code_map = date_map.setdefault(agent.code, {PENDING_TRNS: {}, INCOMPLETED_ORDERS: {}, COMPLETED_ORDERS: {}})
                        code_map[INCOMPLETED_ORDERS].setdefault(agent.id, {})[order.order_no] = order

                        # catch notices that are delivered before order submission is completed
                        to_process = code_map[PENDING_TRNS].get(order.order_no, None)
                        if to_process:
                            for notice in to_process:
                                order.update(notice, trenv)
                                # send back notice to the agent right away
                                await dispatch(agent, notice)  

                            code_map[PENDING_TRNS].pop(order.order_no) 
                else:
                    optlog.error(f"OrderManager: order submission failed: {order.unique_id}", name=agent.id) 
            except Exception as e:
                    optlog.error(f"Error in order submission {order.unique_id}: {e}", name=agent.id, exc_info=True) 
            finally: 
                # send back submission result (order status updated) to the agent right away
                await dispatch(agent, order)  
                await asyncio.sleep(trenv.sleep)

    async def process_tr_notice(self, notice: TransactionNotice, connected_agents: ConnectedAgents, trenv, date_=None):
        # reroute notice to the corresponding order
        # notice content handling logic resides in Order class
        # notice could arrive faster than order submit result - should not use order_no (race condition)
        # trn: order = N : 1 relationship
        if date_ is None: date_=date.today().isoformat()
        async with self._locks[notice.code]:
            date_map = self.map.setdefault(date_, {})
            code_map = date_map.setdefault(notice.code, {PENDING_TRNS: {}, INCOMPLETED_ORDERS: {}, COMPLETED_ORDERS: {}})

            order = None
            for order_dict in code_map[INCOMPLETED_ORDERS].values(): 
                order: Order | None = order_dict.get(notice.oder_no)
                if order is not None: break

            if order: 
                order.update(notice, trenv)
                # if order is completed or canceled, move to completed_orders
                if order.completed or order.cancelled:
                    # remove from incompleted_orders 
                    try:
                        code_map[INCOMPLETED_ORDERS].get(order.agent_id).pop(order.order_no) 
                    except:
                        # let it raise
                        log_raise(f'order.agent_id {order.agent_id} and notice.oder_no {notice.oder_no} mismatches ---', name=order.agent_id) 
                    # add to completed_orders
                    code_map[COMPLETED_ORDERS].setdefault(order.agent_id, []).append(order)

                agent = connected_agents.get_agent_card_by_id(order.agent_id)
                if agent: # if agent is still connected
                    await dispatch(agent, notice)

            else:
                # otherwise save it to pending_trns
                code_map[PENDING_TRNS].setdefault(notice.oder_no, []).append(notice)

    # agent specific cancel orders
    async def cancel_all_outstanding_for_agent(self, agent: AgentCard, trenv, date_=None):
        if date_ is None: date_=date.today().isoformat()

        async with self._locks[agent.code]:
            date_map = self.map.setdefault(date_, {})
            code_map = date_map.setdefault(agent.code, {PENDING_TRNS: {}, INCOMPLETED_ORDERS: {}, COMPLETED_ORDERS: {}})
            incompleted_orders: dict = code_map[INCOMPLETED_ORDERS].get(agent.id, {})
            if not incompleted_orders:
                optlog.info(f"No incompleted orders to cancel for agent {agent.id} ---", name=agent.id)
                return 

            rc_orders = [] 
            for k, o in incompleted_orders.items():
                cancel_order = ReviseCancelOrder(agent_id=agent.id, code=o.code, side=o.side, ord_dvsn=o.ord_dvsn, quantity=o.quantity, price=o.price, rc=RCtype.CANCEL, all_yn=AllYN.ALL, original_order=o)
                rc_orders.append(cancel_order)

            await self.submit_orders_and_register(agent, rc_orders, trenv, date_)
            optlog.info(f'Cancelling all outstanding {len(rc_orders)} orders for agent {agent.id}...', name=agent.id)

    async def closing_checker(self, agent, delay=5, date_=None):
        await asyncio.sleep(delay)
        if date_ is None: date_=date.today().isoformat()
        agent_incomplete_orders: dict = self.map.get(date_, {}).get(agent.code, {}).get(INCOMPLETED_ORDERS, {}).get(agent.id, {})

        if agent_incomplete_orders:
            optlog.error(f"[Closing Check]: {len(agent_incomplete_orders)} orders not yet completed for agent {agent.id}:", name=agent.id)

            not_accepted = [o for k, o in agent_incomplete_orders.items() if not o.accepted]
            if not_accepted:
                optlog.error(f" --- {len(not_accepted)} orders not yet accepted", name=agent.id)

            # may add more checks here ...

        optlog.info("[v] closing check done", name=agent.id)

    async def check_pending_trns_timeout(self, max_age=300, interval=120):
        while True:
            await asyncio.sleep(interval)
            # checking only for today's trns
            date_=date.today().isoformat()
            date_map = self.map.setdefault(date_, {})

            for code, code_map in date_map.items():
                async with self._locks[code]:
                    trns_map = code_map.get(PENDING_TRNS, {})

                    for order_no, items in trns_map.items():
                        # just check the first trn time: 
                        if items:
                            # first notice time as list is filled in order 
                            now_sec = int(time.time()) % 86400 # the same as self.sec(time.strftime("%H%M%S")), i.e., seconds since midnight
                            first_trn_time = getattr(items[0], "stck_cntg_ts", None) or "000000"
                            if (now_sec - self.sec(first_trn_time)) % 86400 >= max_age:  # wrapping around the midnight
                                # don't break, but the error msg will repeat
                                optlog.error(f'Pending TRNs EXPIRED - timeout {max_age} sec: order_no {order_no}')

    async def persist_to_disk(self):
        while True:
            await asyncio.sleep(disk_save_period)
            os.makedirs(data_dir, exist_ok=True)
            date_ = date.today().isoformat()
            date_map = self.map.get(date_, {})

            # Acquire all code locks in parallel
            locks = [self._locks[code] for code in date_map.keys()]
            await asyncio.gather(*(lock.acquire() for lock in locks))
            try:
                filename = os.path.join(data_dir, f"order_manager_{date_}.pkl")
                with open(filename, "wb") as f:
                    pickle.dump(dict(date_map), f)
            finally:
                # Release all locks
                for lock in locks:
                    lock.release()