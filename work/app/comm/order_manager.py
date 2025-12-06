from dataclasses import dataclass, field
from collections import defaultdict
from datetime import date, timedelta
import asyncio
import pickle
import os
import time

from core.common.setup import data_dir, disk_save_period, order_manager_keep_days
from core.common.optlog import optlog, log_raise, LOG_INDENT
from core.common.tools import merge_with_suffix_on_A
from core.common.interface import Sync
from core.model.agent import AgentCard, dispatch
from core.model.order import Order
from core.kis.ws_data import TransactionNotice, RCtype, AllYN
from app.comm.conn_agents import ConnectedAgents


# server side application
# Orders placed by agents are managed here in a comphrehensive way
# all order records are kept

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
    
    # Communication with the API server 
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
            incompleted_orders: {  # indexed
                agent_id: {order_no: order, order_no: order}
                agent_id: {order_no: order, order_no: order}
                ...
            }
            completed_orders: {  # indexed
                agent_id: {order_no: order, order_no: order}
                agent_id: {order_no: order, order_no: order}
                ...
            }
        },
        code: {
            pending_trns: {
                order_no: [trn, trn, ...],
                order_no: [trn, trn, ...],
                ...
            }
            incompleted_orders: {  # indexed
                agent_id: {order_no: order, order_no: order}
                agent_id: {order_no: order, order_no: order}
                ...
            }
            completed_orders: {  # indexed
                agent_id: {order_no: order, order_no: order}
                agent_id: {order_no: order, order_no: order}
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
    load_days: int = order_manager_keep_days

    # Each key gets its own asyncio.Lock automatically
    # key = code
    _locks: dict[str, asyncio.Lock] = field(
        default_factory=lambda: defaultdict(lambda: asyncio.Lock())
    )

    def __post_init__(self): 
        self.sec = lambda t: int(t[:2])*3600 + int(t[2:4])*60 + int(t[4:6])
        self.load_history()

    def __str__(self):
        if not self.map:
            return "(no map initialized)"
        date_ = max(self.map.keys())
        res = '[OrderManager]\n'
        res = res + f'{LOG_INDENT}codes: {list(self.map[date_].keys())}\n'
        for code, code_map in self.map[date_].items():
            res = res + f'{LOG_INDENT}- {code}\n'
            res = res + f'{LOG_INDENT}  {PENDING_TRNS}: {list(code_map[PENDING_TRNS].keys())}\n'
            res = res + f'{LOG_INDENT}  {INCOMPLETED_ORDERS}: { {agent_id: len(orders_dict) for agent_id, orders_dict in code_map[INCOMPLETED_ORDERS].items()} }\n'
            for agent_id, orders_dict in code_map[INCOMPLETED_ORDERS].items():
                for k, o in orders_dict.items():
                    res = res + f'{LOG_INDENT}  - {agent_id}: {o}\n'
            res = res + f'{LOG_INDENT}  {COMPLETED_ORDERS}: { {agent_id: len(orders_dict) for agent_id, orders_dict in code_map[COMPLETED_ORDERS].items()} }\n'
            for agent_id, orders_dict in code_map[COMPLETED_ORDERS].items():
                for k, o in orders_dict.items():
                    res = res + f'{LOG_INDENT}  - {agent_id}: {o}\n'
        return res.strip()

    # sync is based first by code, and then by checking if agent.id exists
    # code and agent.id has to be correct 
    # sync_start_date should be an isoformat ("YYYY-MM-DD")
    async def get_agent_sync(self, agent: AgentCard, sync_start_date: str | None = None):
        lock = self._locks[agent.code]
        await lock.acquire()

        today_ = date.today().isoformat()
        if sync_start_date is None: sync_start_date = today_

        pios = {} # prev incompleted order 
        ios = {} # for today
        cos = {} # all days
        ptrns = {} # for today

        # incompleted_orders: multi-day sync needed (as an order can be partially executed)
        # completed_orders: multi-day sync needed
        # pending_trns: should exist only for today, and today data will be sent
        for d_ in sorted(self.map.keys()): # dates are isoformat "yyyy-mm-dd"
            if d_ < sync_start_date: continue

            date_map = self.map.get(d_)
            if not date_map: continue

            code_map = date_map.get(agent.code)
            if not code_map: continue

            if d_ < today_:
                pios = merge_with_suffix_on_A(pios, code_map[INCOMPLETED_ORDERS].get(agent.id, {}))
                cos = merge_with_suffix_on_A(cos, code_map[COMPLETED_ORDERS].get(agent.id, {}))
                if code_map[PENDING_TRNS]: # if not empty for prev dates, log error
                    optlog.error(f"[OrderManager] pending trns not empty: {code_map[PENDING_TRNS]} for date {d_} - check the validity of incompleted orders required", name=agent.id)
            else: # d_ == today_
                ios = code_map[INCOMPLETED_ORDERS].get(agent.id, {})
                ptrns = code_map[PENDING_TRNS]

        optlog.debug(f"[OrderManager] agent sync data sent", name=agent.id)
        return Sync(agent.id, pios, ios, cos, ptrns)

    def agent_sync_completed_lock_release(self, agent: AgentCard):
        lock = self._locks[agent.code]
        if lock and lock.locked():
            lock.release()
            optlog.debug(f"[OrderManager] agent sync lock released for code {agent.code}", name=agent.id)
            return True
        else:
            log_raise(f"[OrderManager] agent sync lock released FAILED for code {agent.code}", name=agent.id)
            return False

    async def submit_orders_and_register(self, agent: AgentCard, orders: list[Order], trenv, date_=None):
        if len([o for o in orders if o.submitted]) > 0: log_raise('Orders should have not been submitted ---', name=agent.id)
        if date_ is None: date_=date.today().isoformat()

        # below is sequential submission 
        # may consider to concurrently submit: API might not allow this
        # tasks = []
        # for o in orders:
        #     task = asyncio.create_task(...)  
        #     tasks.append(task)
        # await asyncio.gather(*tasks, return_exceptions=True)
        for order in orders: 
            # submit part
            try:
                await asyncio.to_thread(order.submit, trenv)
            except Exception as e:
                optlog.error(f"[OrderManager] error in order submission {order.unique_id}: {e}", name=agent.id, exc_info=True) 
            finally: 
                # send back submission result (order status updated) to the agent right away
                # less likely that order object itself will be corrupt after .submit
                await dispatch(agent, order)  

            # registration
            if order.submitted: # when order_no is assigned successfully by API
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
            
            # no registration
            else:
                optlog.error(f"[OrderManager] order submission failed: {order.unique_id}", name=agent.id) 
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
                    code_map[COMPLETED_ORDERS].setdefault(order.agent_id, {})[order.order_no] = order

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
            incompleted_orders: dict[str, Order] = code_map[INCOMPLETED_ORDERS].get(agent.id, {})
            if not incompleted_orders:
                optlog.info(f"[OrderManager] no incompleted orders to cancel for agent {agent.id} ---", name=agent.id)
                return 

            rc_orders = [] 
            for o in incompleted_orders.values():
                cancel_order = o.make_revise_cancel_order(rc=RCtype.CANCEL, ord_dvsn=o.ord_dvsn, qty=o.quantity-o.processed, pr=o.price, all_yn=AllYN.ALL) 
                # quantity doesn't matter anyway when cancel all
                rc_orders.append(cancel_order)

            await self.submit_orders_and_register(agent, rc_orders, trenv, date_)
            optlog.info(f'[OrderManager] cancelling all outstanding {len(rc_orders)} orders for agent {agent.id}...', name=agent.id)

    async def closing_checker(self, agent, delay=5, date_=None):
        await asyncio.sleep(delay)
        if date_ is None: date_=date.today().isoformat()
        agent_incomplete_orders: dict = self.map.get(date_, {}).get(agent.code, {}).get(INCOMPLETED_ORDERS, {}).get(agent.id, {})

        if agent_incomplete_orders:
            optlog.error(f"[OrderManager-ClosingCheck] {len(agent_incomplete_orders)} orders not yet completed for agent {agent.id}:", name=agent.id)

            not_accepted = [o for k, o in agent_incomplete_orders.items() if not o.accepted]
            if not_accepted:
                optlog.error(f"[OrderManager-ClosingCheck] ---- {len(not_accepted)} orders not yet accepted", name=agent.id)

            # may add more checks here ...

        optlog.info("[OrderManager-ClosingCheck] closing check done", name=agent.id)

    # checks if pending trns persist for a specific code
    # runs as an independent coroutine on the server
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
                                optlog.error(f'[OrderManager] pending TRNs EXPIRED - timeout {max_age} sec: order_no {order_no}')


    async def persist_to_disk(self, immediate=False):
        if immediate:
            return await self._save_once()

        while True:
            # save only today's record
            await asyncio.sleep(disk_save_period)
            await self._save_once() 

    async def _save_once(self):
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

            # clean up old dates
            cutoff = (date.today() - timedelta(days=self.load_days)).isoformat()
            dates_to_remove = [d for d in self.map.keys() if d < cutoff]
            for d in dates_to_remove:
                del self.map[d]

            return date_
    
    def load_history(self):
        self.map.clear()
        cutoff_date = (date.today() - timedelta(days=self.load_days)).isoformat()
        for fname in sorted(os.listdir(data_dir)):
            if not (fname.startswith("order_manager_") and fname.endswith(".pkl")):
                continue

            date_ = fname[14:24]  # 'YYYY-MM-DD'
            if date_ < cutoff_date:
                continue  # skip old files
            path = os.path.join(data_dir, fname)
            try:
                with open(path, "rb") as f:
                    loaded = pickle.load(f)
            except Exception as e:
                optlog.error(f"[OrderManager] failed to load {fname}: {e}")
                continue
            self.map[date_] = loaded
            optlog.info(f"[OrderManager] loaded history for {date_} ({fname})")
