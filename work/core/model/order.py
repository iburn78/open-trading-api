import json
import pandas as pd
import asyncio
from collections import defaultdict
from dataclasses import dataclass, field, asdict

from .cost import CostCalculator
from ..common.optlog import optlog, log_raise
from ..common.tools import get_market, excel_round_int 
from ..kis.domestic_stock_functions import order_cash, order_rvsecncl
from ..kis.ws_data import ORD_DVSN, RCtype, AllYN, TransactionNotice

@dataclass
class Order:
    agent_id: str 
    code: str
    side: str # 'buy' or 'sell'
    quantity: int
    ord_dvsn: ORD_DVSN # market or limit
    price: int
    amount: int = 0 # total purchased cumulative amount (sum of quantity x price)
    avg_price: float = 0.0
    bep_cost: int = 0
    bep_price: float = 0.0
    market: str = None # KOSPI, KOSDAQ, etc
    exchange: str = "SOR" # Smart Order Routing - KRX, NXT, etc.

    org_no: str | None = None
    order_no: str | None = None
    submitted_time: str | None = None

    submitted: bool = False
    accepted: bool = False
    completed: bool = False
    cancelled: bool = False 

    # as the order is fullfilled, cost_occured should refect exact cost up to that moment
    # round only done when the order is fully fullfilled
    processed: int = 0
    fee_occured: float = 0.0
    tax_occured: float = 0.0
    fee_rounded: int = 0   # if completed or cancelled, this is final 
    tax_rounded: int = 0   # if completed or cancelled, this is final 

    # NEED TO CLARIFY CALCELLED LOGIC
    # IOC, FOK, End of day cancellation etc
    # even not completed, remainder of order not to be processed

    def __post_init__(self):
        if type(self.quantity) != int or type(self.price) != int:
            log_raise("submit with quantity and/or price as int ---")
        if self.side not in ("buy", "sell"):
            log_raise("side must be 'buy' or 'sell' ---")

        if self.ord_dvsn == ORD_DVSN.LIMIT and self.price == 0:
            log_raise("Limit orders require a price")
        if self.ord_dvsn == ORD_DVSN.MARKET and self.price != 0:
            log_raise("Market orders should not have a price ---")

        self.market = get_market(self.code)

        if self.market not in ['KOSPI', 'KOSDAQ']:
            log_raise("Check the market of the stock: KOSPI or KOSDAQ ---")
        
    
    def __str__(self):
        return "Order:" + json.dumps(asdict(self), indent=4, default=str)

    def submit(self, trenv):
        if self.completed or self.cancelled:
            log_raise('A completed or cancelled order submitted ---')

        ord_qty = str(self.quantity)
        ord_unpr = str(self.price)
        res = order_cash(env_dv=trenv.env_dv, ord_dv=self.side, cano=trenv.my_acct, acnt_prdt_cd=trenv.my_prod, pdno=self.code, ord_dvsn=self.ord_dvsn, ord_qty=ord_qty, ord_unpr=ord_unpr, excg_id_dvsn_cd=self.exchange)

        if res.empty:
            log_raise('Order submission failed ---')
        else: 
            if pd.isna(res.loc[0, ["ODNO", "ORD_TMD", "KRX_FWDG_ORD_ORGNO"]]).any():
                log_raise("Check submission response ---")
            self.order_no = res.ODNO.iloc[0]
            self.submitted_time = res.ORD_TMD.iloc[0]
            self.org_no = res.KRX_FWDG_ORD_ORGNO.iloc[0]
            self.submitted = True
            optlog.info(f"Order {self.order_no} submitted")
    
    def update(self, notice: TransactionNotice, trenv):
        if self.order_no != notice.oder_no: # checking order_no (or double-checking)
            log_raise(f"Notice does not match with order {self.order_no} ---")
        if self.completed or self.cancelled: 
            log_raise(f"Notice for completed or cancelled order {self.order_no} arrived ---")
        if notice.rfus_yn != "0": # "0": 승인
            log_raise(f"Order {self.order_no} refused ---")

        if notice.cntg_yn == "1": # 주문, 정정, 취소, 거부
            if notice.acpt_yn == "1": # 주문접수 (최초 주문)
                self.accepted = True
            elif notice.acpt_yn == "2": # 확인
                if notice.ooder_no is None:
                    log_raise("Check logic (original order no of notice) ---")
                self.accepted = True
                self.update_rc_specific()
            else: # notice.acpt_yn == "3": # 취소(FOK/IOC)
                log_raise("Not implemented yet ---")

        else: # notice.cntg_yn == "2": # 체결
            if notice.acpt_yn == "2": # 확인
                self.processed += notice.cntg_qty
                self.amount += notice.cntg_qty*notice.cntg_unpr
                self.avg_price = self.amount/self.processed

                fee_float, tax_float, fee_rd, tax_rd = CostCalculator.calculate(
                    side = notice.seln_byov_cls,
                    quantity = notice.cntg_qty, 
                    price = notice.cntg_unpr,
                    market = self.market, 
                    svr = trenv.my_svr,
                    exchange = notice.exchange
                )
                self.fee_occured += fee_float
                self.tax_occured += tax_float
                self.fee_rounded = excel_round_int(self.fee_occured, fee_rd)
                self.tax_rounded = excel_round_int(self.tax_occured, tax_rd)

                self.bep_cost, self.bep_price = CostCalculator.bep_cost_calculate(self.processed, self.avg_price, self.market, trenv.my_svr)

                if self.processed > self.quantity:
                    log_raise('Check order processed quantity ---')
                if self.processed == self.quantity:
                    self.completed = True
                    optlog.info(f"Order {self.order_no} completed")
            else: 
                log_raise("Check logic ---")

    def update_rc_specific(self):
        # to be overrided by ReviseCancelOrder
        # no need to define any here
        pass

    def make_revise_cancel_order(self, rc, qty, ord_dvsn, pr, all_yn):   # ord_dvsn could changed, e.g., from limit to market
        if not self.submitted:
            log_raise(f"Order {self.order_no} not submitted yet but revise-cancel tried / instead modify order itself ---")
        return ReviseCancelOrder(self.code, self.side, qty, ord_dvsn, pr, rc=rc, all_yn=all_yn, original_order=self)

@dataclass
class ReviseCancelOrder(Order):
    rc: RCtype = None # '01': revise, '02': cancel
    all_yn: AllYN = None # 잔량 전부 주문 - Y:전부, N: 일부 
    original_order: Order = None

    def __post_init__(self):
        super().__post_init__()  # need to call explicitly 
        if self.original_order is None: 
            log_raise("Check revise-cancel original order ---")

    # revise is cancel + re-order
    # new order_no is assigned both for revise and cancel
    # command rule/sequence: ----------------------
    # - check order_no 
    # - check revise or cancel
    # - check all or partial 
    # - if all and revise:
    # -     check ord_dvsn (market or limit etc)
    # -     check price (quantity can be any, at least "0" required)
    # - if all and cancel:
    # -     nothing matters (can be any, at least "0" required)
    # - if partial and revise:
    # -     check ord_dvsn (market or limit etc)
    # -     check price and quantity
    # - if partial and cancel:
    # -     check quantity (price can be any, at least "0" required)
    def submit(self, trenv):
        ord_qty = str(self.quantity)
        ord_unpr = str(self.price)
        res = order_rvsecncl(
            env_dv=trenv.env_dv,
            cano=trenv.my_acct,
            acnt_prdt_cd=trenv.my_prod,
            krx_fwdg_ord_orgno=self.original_order.org_no,
            orgn_odno=self.original_order.order_no,
            ord_dvsn=self.ord_dvsn, 
            rvse_cncl_dvsn_cd=self.rc, 
            ord_qty=ord_qty,
            ord_unpr=ord_unpr, 
            qty_all_ord_yn=self.all_yn, 
            excg_id_dvsn_cd=self.exchange
        )
        if res.empty:
            log_raise(f'Order {self.order_no} revise-cancel failed ---')
        else: 
            if pd.isna(res.loc[0, ["ODNO", "ORD_TMD", "KRX_FWDG_ORD_ORGNO"]]).any():
                log_raise("Check revise-cancel response ---")
            self.order_no = res.ODNO.iloc[0]
            self.submitted_time = res.ORD_TMD.iloc[0]
            self.org_no = res.KRX_FWDG_ORD_ORGNO.iloc[0]
            self.submitted = True

            if self.rc == RCtype.REVISE:
                optlog.info(f"Order {self.original_order.order_no}'s revise order {self.order_no} submitted")
            else: # cancel
                optlog.info(f"Order {self.original_order.order_no}'s {'full' if self.all_yn == AllYN.ALL else 'partial'} cancellation order {self.order_no} submitted")

    def update_rc_specific(self):
        if self.original_order.completed or self.original_order.cancelled: 
            log_raise("Check update_original, as original order is completed or cancelled ---")

        if self.all_yn == AllYN.ALL: 
            self.quantity = self.original_order.quantity - self.original_order.processed
            self.original_order.quantity = self.original_order.processed
            self.original_order.completed = True
        else: 
            self.original_order.quantity = self.original_order.quantity - self.quantity
            if self.original_order.quantity == self.original_order.processed:
                self.original_order.completed = True
            elif self.original_order.quantity < self.original_order.processed:
                log_raise('Check partial order revise-cancel logic ---')
        
        if self.rc == RCtype.CANCEL: 
            self.cancelled = True
                
@dataclass
class OrderList: # submitted order list
    # If order size grows, consider making all as a dict for faster lookup O(1)
    # @dataclass need to define default values with care (e.g., field(...))
    all: list[Order] = field(default_factory=list) 

    # defaultdict(list) is useful when there is 1 to N relationship, e.g., multiple notices to one order
    # simple access to defaultdict would generate key inside with empty list - handle with care
    _pending_tr_notices: dict[str, list[TransactionNotice]] = field(
        default_factory=lambda: defaultdict(list)
    )
    # the _lock is an instance variable used to protect the 'all' variable and '_pending_tr_notices' variable in each OrderList instance
    # if and only if the two variables are indenpendent, you may split it to two _locks for performance
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __str__(self):
        if not self.all:
            return "<no orders>"
        return "\n".join(str(order) for order in self.all)

    async def process_tr_notice(self, notice: TransactionNotice, trenv):
        # reroute notice to corresponding order
        # notice content handling logic should reside in Order class
        # tr notice could arrive faster than order submit result - should not use order_no
        # i.e., race condition could occur
        async with self._lock:
            order = next((o for o in self.all if o.order_no is not None and o.order_no == notice.oder_no), None)
            if order is not None:
                order.update(notice, trenv)
            else:
                self._pending_tr_notices[notice.oder_no].append(notice)

    async def try_process_pending_tr_notices(self, order:Order, trenv):
        # Retry unmatched notices when new orders get order_no
        async with self._lock:
            to_process = self._pending_tr_notices.get(order.order_no, [])
            for notice in to_process:
                order.update(notice, trenv)
            self._pending_tr_notices.pop(order.order_no, None)

    async def submit_orders_and_register(self, orders:list, trenv): # only accepts new orders not submitted.
        if len([o for o in orders if o.submitted]) > 0: log_raise('Orders should not have been submitted ---')
        for order in orders:
            await asyncio.to_thread(order.submit, trenv)
            async with self._lock:
                self.all.append(order)
            await self.try_process_pending_tr_notices(order, trenv) # catch notices that are delivered before registration into order list
            await asyncio.sleep(trenv.sleep)

    ############################## NEED REVIEW ################################ 
    ############################## MAY CHANGE TO BY AGENT OR BY CODE ################################ 
    ############################## ALL CANCEL REQUIRED TOO ################################ 
    async def cancel_all_outstanding(self, trenv):
        # submitted but not accepted oreders: cannot cancel... should try later again... 
        not_accepted_orders = [o for o in self.all if not o.accepted]
        if not_accepted_orders: 
            log_raise('Submitted but not accepted orders exist; should try later again ---')
        to_cancel = [o for o in self.all if not o.completed and not o.cancelled]
        to_cancel_list = []
        for o in to_cancel:
            cancel_order = ReviseCancelOrder(o.code, o.side, o.quantity, o.ord_dvsn, o.price, rc=RCtype.CANCEL, all_yn=AllYN.ALL, original_order=o)
            to_cancel_list.append(cancel_order)
        
        optlog.info(f'Cancelling all outstanding {len(to_cancel_list)} orders:')
        await self.submit_orders_and_register(to_cancel_list, trenv)

    async def closing_checker(self, delay=5): 
        await asyncio.sleep(delay)
        # 1. check if any order not yet submitted or accepted
        not_submitted = [o for o in self.all if not o.submitted]
        not_accepted = [o for o in self.all if not o.accepted]
        if not_submitted:
            log_raise(f"Cannot close: {len(not_submitted)} orders not yet submitted ---")
        if not_accepted:
            log_raise(f"Cannot close: {len(not_submitted)} orders not yet accepted ---")

        # 2. check if any pending notices remain
        if self._pending_tr_notices:
            l = len(self._pending_tr_notices)
            count = sum(len(v) for v in self._pending_tr_notices.values())
            log_raise(f"Cannot close: pending notices dict has {l} items, with total {count} pending notices ---")

        optlog.info("[v] closing check successful")
        # ##################################################################################
        # MAY SAVE STATUS or .... follow-up
        # Generate Report
        # Is this truely the end of main.py? Or, could be a chance to save some state
        # ################################################################################## 
