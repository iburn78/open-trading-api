from collections import defaultdict
from datetime import date, timedelta
import asyncio
import pickle
import os
import time

from .comm_interface import AgentSession
from .comm_interface import Sync, OM_Dispatch, Dispatch_ACK
from ..base.settings import DATA_DIR, OM_save_filename, disk_save_period, order_manager_keep_days
from ..base.tools import merge_with_suffix_on_A, list_str, dict_key_number
from ..kis.kis_tools import KIS_Functions
from ..kis.ws_data import TransactionNotice
from ..model.order import Order, CancelOrder
from ..comm.conn_agents import ConnectedAgents

# this is a server side application
# orders placed by agents are managed here in a comphrehensive way
# all order records are kept

PENDING_TRNS = 'pending_trns'
INCOMPLETED_ORDERS = 'incompleted_orders'
COMPLETED_ORDERS = 'completed_orders'
PENDING_DISPATCHES = 'pending_dispatches'

class OrderManager:
    """
    # To be used in the server side application 
    # Organize orders from each agent in a structured way
    - keeps the last `keep_days` worth of data
    - within a day, it keeps increaing and records everything about orders
    - pending trns are due to race condition between order submission and getting the trn (order_no not yet assigned from the server)
    - when new orders are added, need to check if there are any pending trn for the order
    - handles Order and CancelOrder the same way (order means cancel_order included)
    
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
            pending_dispatches: {  # indexed
                agent_id: {id: data, id: data, ...}
                agent_id: {id: data, id: data, ...}
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
            pending_dispatches: {  # indexed
                agent_id: {id: data, id: data, ...}
                agent_id: {id: data, id: data, ...}
                ...
            }
        },
        ...
    }
    """
    # defaultdict(list) is useful when there is 1 to N relationship, e.g., multiple notices to one order
    # access to defaultdict would generate key inside with empty list
    def __init__(self, logger, connected_agents: ConnectedAgents, kf: KIS_Functions, service):
        self.logger = logger
        self.connected_agents = connected_agents
        self.kf = kf
        self.service = service

        self.map = defaultdict(
            lambda: defaultdict(
                lambda: {
                            PENDING_TRNS: defaultdict(list), 
                            INCOMPLETED_ORDERS: defaultdict(dict), 
                            COMPLETED_ORDERS: defaultdict(dict),
                            PENDING_DISPATCHES: defaultdict(dict),
                        }
            )
        )
        self.load_days: int = order_manager_keep_days

        # each key in dict (key=code) gets its own asyncio.Lock automatically
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.sec = lambda t: int(t[:2])*3600 + int(t[2:4])*60 + int(t[4:6])
        self.load_history()

    def __str__(self):
        if not self.map:
            return "[OrderManager] no map initialized"
        date_ = max(self.map.keys())
        res = f'[OrderManager] for {date_}, codes: ' + list_str(self.map[date_].keys()) +'\n'
        for code, code_map in self.map[date_].items():
            res += f'- {code}\n'
            res += f'  {PENDING_TRNS}: ' + dict_key_number(code_map[PENDING_TRNS])+'\n' 
            res += f'  {INCOMPLETED_ORDERS}: \n'
            for agent_id, orders_dict in code_map[INCOMPLETED_ORDERS].items():
                res += f'  - {agent_id}: total {len(orders_dict)} orders\n'
                for _, o in orders_dict.items():
                    res += f'    - {o}\n'
            res += f'  {COMPLETED_ORDERS}: \n'
            for agent_id, orders_dict in code_map[COMPLETED_ORDERS].items():
                res += f'  - {agent_id}: total {len(orders_dict)} orders\n'
                for _, o in orders_dict.items():
                    res += f'    - {o}\n'
            res += f'  {PENDING_DISPATCHES}: \n'
            for agent_id, data_dict in code_map[PENDING_DISPATCHES].items():
                res += f'  - {agent_id}: total {len(data_dict)} items\n'
                for _, o in data_dict.items():
                    res += f'    - {o}\n'
        return res.strip()

    # sync is based first by code, and then by checking if agent.id exists
    # sync_start_date should be an isoformat ("YYYY-MM-DD")
    async def get_agent_sync(self, agent: AgentSession, sync_start_date: str | None = None):
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
        # pending_trns: should exist only for today, and only today data will be sent
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
                    self.logger.error(f"[OrderManager] pending trns not empty: {code_map[PENDING_TRNS]} for date {d_} - check the validity of incompleted orders required", extra={"owner":agent.id})
            else: # d_ == today_
                ios = code_map[INCOMPLETED_ORDERS].get(agent.id, {})
                cos = merge_with_suffix_on_A(cos, code_map[COMPLETED_ORDERS].get(agent.id, {}))
                ptrns = code_map[PENDING_TRNS]

        self.logger.info(f"[OrderManager] agent sync data sent", extra={"owner":agent.id})
        return Sync(agent.id, pios, ios, cos, ptrns)

    async def agent_sync_completed_lock_release(self, agent: AgentSession):
        lock = self._locks[agent.code]
        if lock and lock.locked():
            # to avoid deadlock with ack_received(), release first
            lock.release()

            # handling of pending dispatches
            code_map = self._get_code_map(agent.code)
            pds = code_map[PENDING_DISPATCHES].pop(agent.id, {})
            if pds:
                agent.sync_completed_event.clear()
                for d in pds.values():
                    await self.dispatch_handler(agent, d)
                await agent.sync_completed_event.wait()
            agent.sync_completed = True
            self.logger.info(f"[OrderManager] agent sync completed", extra={"owner":agent.id})
            return True
        else:
            self.logger.error(f"[OrderManager] agent sync lock released FAILED: code {agent.code}", extra={"owner":agent.id})
            return False

    def _get_code_map(self, code, date_=None):
        if date_ is None:
            date_ = date.today().isoformat()
        date_map = self.map.setdefault(date_, {})
        code_map = date_map.setdefault(code, {
            PENDING_TRNS: {}, INCOMPLETED_ORDERS: {}, COMPLETED_ORDERS: {}, PENDING_DISPATCHES: {}
        })
        return code_map

    def _update_map(self, code_map, order: Order | CancelOrder):
        # move to completed if finished 
        if order.completed:
            code_map[INCOMPLETED_ORDERS].get(order.agent_id, {}).pop(order.order_no, None)
            code_map[COMPLETED_ORDERS].setdefault(order.agent_id, {})[order.order_no] = order

            if not order.is_regular_order: 
                # in case of CancelOrder, also handle the original_order
                original_order = code_map[INCOMPLETED_ORDERS].get(order.agent_id, {}).get(order.original_order_no)
                if original_order is None: 
                    self.logger.error(f"[OrderManager] cancel order update error {order}", extra={"owner":order.agent_id})
                    return

                original_order.quantity = original_order.quantity - order.processed
                if original_order.quantity < original_order.processed:
                    self.logger.error(f"[OrderManager] cancel quantity error {order}, {original_order}", extra={"owner":order.agent_id})
                    return 

                if original_order.quantity == original_order.processed:
                    original_order.completed = True
                    code_map[INCOMPLETED_ORDERS].get(order.agent_id).pop(order.original_order_no)
                    code_map[COMPLETED_ORDERS].setdefault(order.agent_id, {})[original_order.order_no] = original_order

    async def submit_orders_and_register(self, agent, orders: list[Order | CancelOrder]):
        if any(o.submitted for o in orders):
            self.logger.error(f"[OrderManager] orders already submitted: no actions taken", extra={"owner": agent.id})
            return False
        
        for order in orders:
            if order.is_regular_order:
                res = await self.kf.order_cash(
                    ord_dv=order.side, 
                    pdno=order.code, 
                    mtype=order.mtype, 
                    ord_qty=order.quantity,
                    ord_unpr=order.price, 
                    excg_id_dvsn_cd=order.exchange
                    )
            else: # CancelOrder
                res = await self.kf.order_rvsecncl(
                    krx_fwdg_ord_orgno=order.original_order_org_no,
                    orgn_odno=order.original_order_no,
                    mtype=order.mtype, 
                    rvse_cncl_dvsn_cd='02', # cancel
                    ord_qty=order.quantity, # to cancel quantity
                    ord_unpr=0, # send it with 0 (cancel)
                    qty_all_ord_yn=order.qty_all_yn, 
                    excg_id_dvsn_cd=order.exchange
                )

            if res is None:
                self.logger.error(f"[OrderManager] order submit failed, uid {order.unique_id}", extra={"owner":agent.id})
            else:
                order_no = res.get('ODNO') or res.get('odno')
                submitted_time = res.get('ORD_TMD') or res.get('ord_tmd')
                org_no = res.get('KRX_FWDG_ORD_ORGNO') or res.get('krx_fwdg_ord_orgno')
                order.update_submit_response(order_no, submitted_time, org_no)

            # send back the submission result (order with status updated) 
            await self.dispatch_handler(agent, order)
            if not order.submitted:
                continue
            
            ###_ _______________________________________________

            async with self._locks[order.code]:
                # register incompleted order
                code_map = self._get_code_map(agent.code)
                code_map[INCOMPLETED_ORDERS].setdefault(agent.id, {})[order.order_no] = order

                # process pending notices
                # - catch notices that are delivered before order submission is completed
                for notice in code_map[PENDING_TRNS].pop(order.order_no, []):
                    order.update(notice)
                    # send back notice to the agent right away
                    await self.dispatch_handler(agent, notice) 
                self._update_map(code_map, order)
        return True

    async def process_tr_notice(self, notice: TransactionNotice):
        # reroute notice to the corresponding order
        # notice content handling logic resides in Order | CancelOrder class
        # notice could arrive faster than order submit result - should not use order_no (race condition)
        # trn: order = N : 1 relationship
        async with self._locks[notice.code]:
            code_map = self._get_code_map(notice.code)
            order = None
            # find order by notice.order_no (which doesn't have agent id)
            for _, order_dict in code_map[INCOMPLETED_ORDERS].items(): 
                order = order_dict.get(notice.order_no)
                if order: 
                    break # stop finding
            if order:  
                order.update(notice)
                self._update_map(code_map, order)
                agent = self.connected_agents.get_agent_by_id(order.agent_id)
                if agent: # if agent is still connected
                    await self.dispatch_handler(agent, notice)
            else:
                # otherwise save it to pending_trns
                code_map[PENDING_TRNS].setdefault(notice.order_no, []).append(notice)

    # checks if pending trns persist for a specific code
    # runs as an independent coroutine on the server
    async def pending_trns_timeout(self, max_age=300, interval=120):
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
                                self.logger.error(f'[OrderManager] pending TRNs EXPIRED - timeout {max_age} sec: order_no {order_no}')

    async def persist_to_disk(self, immediate=False):
        if immediate:
            return await self._save_once()

        while True:
            # save only today's record
            await asyncio.sleep(disk_save_period)
            await self._save_once() 

    async def _save_once(self):
            os.makedirs(DATA_DIR, exist_ok=True)
            date_ = date.today().isoformat()
            date_map = self.map.get(date_, {})

            # Acquire all code locks in parallel
            locks = [self._locks[code] for code in date_map.keys()]
            await asyncio.gather(*(lock.acquire() for lock in locks))
            try:
                filename = os.path.join(DATA_DIR, f"{OM_save_filename}{self.service}_{date_}.pkl")
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
        for fname in sorted(os.listdir(DATA_DIR)):
            if not (fname.startswith(f"{OM_save_filename}{self.service}") and fname.endswith(".pkl")):
                continue
            date_ = fname.split('.')[0].split('_')[-1] # 'YYYY-MM-DD'
            if date_ < cutoff_date:
                continue  # skip old files
            path = os.path.join(DATA_DIR, fname)
            with open(path, "rb") as f:
                self.map[date_] = pickle.load(f)
            self.logger.info(f"[OrderManager] loaded history for {date_} ({fname})")

    async def dispatch_handler(self, agent: AgentSession, data):
        d = OM_Dispatch(data)
        code_map = self._get_code_map(agent.code)
        code_map[PENDING_DISPATCHES].setdefault(agent.id, {})[d.id] = data
        await agent.dispatch(d)
        
    async def ack_received(self, dispatch_ack: Dispatch_ACK):
        agent = self.connected_agents.get_agent_by_id(dispatch_ack.agent_id)

        async with self._locks[agent.code]:
            code_map = self._get_code_map(agent.code)
            agent_map = code_map[PENDING_DISPATCHES].get(agent.id)
            if not agent_map:
                self.logger.error(f"[OrderManager] stale ACK: {dispatch_ack}", extra={"owner": agent.id})
                return
            del agent_map[dispatch_ack.id]


            if not agent.sync_completed and not agent_map:
                agent.sync_completed_event.set()


###_
"""
defaultdict(<function OrderManager.__init__.<locals>.<lambda> at 0x00000161857DFE20>, 
            {'2026-01-10': {'000660': {'pending_trns': {}, 'incompleted_orders': {}, 'completed_orders': {}, 'pending_dispatches': {}}}, 
             '2026-01-11': {'000660': {'pending_trns': {}, 'incompleted_orders': {}, 'completed_orders': {}, 'pending_dispatches': {}}}, 
             '2026-01-12': {'000660': {'pending_trns': {}, 'incompleted_orders': {'A5': {}, 'A7': {}}, 
            'completed_orders': {'A5': {'0000007379': Order(agent_id='A5', logger=<Logger agent_runner_demo (WARNING)>, code='000660', side=<SIDE.BUY: 'buy'>, mtype=<MTYPE.MARKET: '01'>, quantity=1, price=0, exchange=<EXG.SOR: 'SOR'>, unique_id='7f4f3f7758a64119aaba635cb3f2143e', gen_time='0112122353.878389', org_no='00950', order_no='0000007379', submitted_time='122359', is_regular_order=True, submitted=True, accepted=True, completed=True, amount=754000, avg_price=754000.0, processed=1, fee_=107, tax_=0), 
                                        '0000007404': Order(agent_id='A5', logger=<Logger agent_runner_demo (WARNING)>, code='000660', side=<SIDE.BUY: 'buy'>, mtype=<MTYPE.MARKET: '01'>, quantity=2, price=0, exchange=<EXG.SOR: 'SOR'>, unique_id='7e383d16e37f4704842894650aad4bfd', gen_time='0112122532.277560', org_no='00950', order_no='0000007404', submitted_time='122533', is_regular_order=True, submitted=True, accepted=True, completed=True, amount=1506000, avg_price=753000.0, processed=2, fee_=214, tax_=0)}, 
                                'A7': {'0000007474': Order(agent_id='A7', logger=<Logger agent_runner_demo (WARNING)>, code='000660', side=<SIDE.BUY: 'buy'>, mtype=<MTYPE.MARKET: '01'>, quantity=10, price=0, exchange=<EXG.SOR: 'SOR'>, unique_id='394d2a178ca2433da4f51cf993a5b2c6', gen_time='0112123013.113691', org_no='00950', order_no='0000007474', submitted_time='123014', is_regular_order=True, submitted=True, accepted=True, completed=True, amount=7528000, avg_price=752800.0, processed=10, fee_=1070, tax_=0), 
                                       '0000007475': Order(agent_id='A7', logger=<Logger agent_runner_demo (WARNING)>, code='000660', side=<SIDE.BUY: 'buy'>, mtype=<MTYPE.MARKET: '01'>, quantity=10, price=0, exchange=<EXG.SOR: 'SOR'>, unique_id='61ebb681e0814e5d863c458292c6c78e', gen_time='0112123013.113691', org_no='00950', order_no='0000007475', submitted_time='123014', is_regular_order=True, submitted=True, accepted=True, completed=True, amount=7530000, avg_price=753000.0, processed=10, fee_=1069, tax_=0)}}, 
            'pending_dispatches': {'A5': {}, 'A7': {'1e69a4de87ac4d46b15531b2241e1a31': Order(agent_id='A7', logger=<Logger agent_runner_demo (WARNING)>, code='000660', side=<SIDE.BUY: 'buy'>, mtype=<MTYPE.MARKET: '01'>, quantity=10, price=0, exchange=<EXG.SOR: 'SOR'>, unique_id='394d2a178ca2433da4f51cf993a5b2c6', gen_time='0112123013.113691', org_no='00950', order_no='0000007474', submitted_time='123014', is_regular_order=True, submitted=True, accepted=True, completed=True, amount=7528000, avg_price=752800.0, processed=10, fee_=1070, tax_=0), 
                                  '4950bf8e4f1f44258f44494c2faeb484': <core.kis.ws_data.TransactionNotice object at 0x00000161997DC190>, 
                                  'd646984f28fb4a9aaec9d36563c7679b': <core.kis.ws_data.TransactionNotice object at 0x00000161997DC910>, 
                                  'c25d954a6d0246559689e92f36b2ce5d': Order(agent_id='A7', logger=<Logger agent_runner_demo (WARNING)>, code='000660', side=<SIDE.BUY: 'buy'>, mtype=<MTYPE.MARKET: '01'>, quantity=10, price=0, exchange=<EXG.SOR: 'SOR'>, unique_id='61ebb681e0814e5d863c458292c6c78e', gen_time='0112123013.113691', org_no='00950', order_no='0000007475', submitted_time='123014', is_regular_order=True, submitted=True, accepted=True, completed=True, amount=7530000, avg_price=753000.0, processed=10, fee_=1069, tax_=0), 
                                  'c3568a92a4fd4a428a36fcd168aa0a37': <core.kis.ws_data.TransactionNotice object at 0x00000161997DCC10>, 
                                  '226f8bf1ac324a60a710addcb0b2ada1': <core.kis.ws_data.TransactionNotice object at 0x00000161997DCED0>}}}}})
                                  

###_ gravious errors
1) pending dispatch... order manager has check it as completed, but notices not gone yet. mismatch could arise
    - should perfectly match order manager vs order book 
    - when ack received should only be updated at the same time for both (revise total logic)
    - asyncio doesn't stop at CPU, it is raised at next await, so ensure both be the same 
    - it includes order and notices

2) default dict -> care, once you put key, it will be generated 

3) order has logger could be wrong... 

4) 0112_123014.206 [ERROR] > [CommHandler] handler error at client port 11676: cannot unpack non-iterable NoneType object

5) dashboard port collison issue

6) discunnect later trns are not quued to the pending trns
"""