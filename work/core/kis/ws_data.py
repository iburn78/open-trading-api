import json 
from collections import namedtuple
import pandas as pd
from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime

tr_id_dict = {
    'TransactionNotice': {'demo': 'H0STCNI9', 'real': 'H0STCNI0',},
    'TransactionPrices_KRX': {'demo': 'H0STCNT0', 'real': 'H0STCNT0',}, # 실시간 체결가 (KRX) 
    'TransactionPrices_Total': {'demo': None, 'real': 'H0UNCNT0',}, # 실시간 체결가 (종합) - 종합은 모의투자 미지원
    # to add more...
}

def get_tr(trenv, tr_id):
    rev_tr_id_dict = { 
        (env, tr): name 
        for name, env_dict in tr_id_dict.items()
        for env, tr in env_dict.items()
        }
    return rev_tr_id_dict.get((trenv.env_dv, tr_id))

# ----------------------------------------
# trenv conversion to/from json
# ----------------------------------------
# trenv cannnot be pickled, so conversion needed
# add more fields if needed ...

def trenv_to_json(trenv):
    return json.dumps({
        'my_svr': trenv.my_svr,
    })

def trenv_from_json(trenv_json):
    nt1 = namedtuple('TrEnv', ['my_svr',])
    return nt1(*json.loads(trenv_json))

# ----------------------------------------
# Common Enum definitions
# ----------------------------------------
class ORD_DVSN(str, Enum):
    LIMIT = '00'
    MARKET = '01'

class RCtype(str, Enum):
    REVISE = '01'
    CANCEL = '02'

class AllYN(str, Enum):
    ALL = 'Y'
    PARTIAL = 'N'

class SIDE(str, Enum):
    BUY = 'buy'
    SELL = 'sell'

@dataclass
class TransactionNotice: # 국내주식 실시간체결통보
    acnt_no: str | None = None # account number
    oder_no: str | None = None # order number
    ooder_no: str | None = None # original order number 
    seln_byov_cls: str | None = None # 01: sell, 02: buy
    rctf_cls: str | None = None # 0:정상, 1:정정, 2:취소
    oder_kind: ORD_DVSN | None = None # 00: limit, 01: market
    oder_cond: str | None = None # 0: None, 1: IOC (Immediate or Cancel), 2: FOK (Fill or Kill)
    code: str | None = None     
    cntg_qty: int | None = None # traded quantity
    cntg_unpr: int | None = None # traded price
    stck_cntg_hour: str | None = None # traded time (HHMMSS)
    rfus_yn: str | None = None # 0: 승인, 1: 거부 
    cntg_yn: str | None = None # 1: 주문, 정정, 취소, 거부, 2: 체결 
    acpt_yn: str | None = None # 1: 주문접수, 2: 확인, 3: 취소(IOC/FOK)
    brnc_no: str | None = None # 지점번호
    oder_qty: int | None = None # total order quantity  
    exg_yn: str | None = None # 1:KRX, 2:NXT, 3:SOR-KRX, 4:SOR-NXT + 실시간체결창 표시여부(Y/N)
    crdt_cls: str | None = None # 신용구분 
    oder_prc: int | None = None # order price    

    def __str__(self):
        return "TransactionNotice:" + json.dumps(asdict(self), indent=4, default=str)

    def _set_data(self, res):
        if res.empty:
            raise("Empty response in TransactionNotice.from_response ---")
        row = res.iloc[0] 
        self.acnt_no        = self.pd_nan_chker_("str", row["ACNT_NO"])
        self.oder_no        = self.pd_nan_chker_("str", row["ODER_NO"])
        self.ooder_no       = self.pd_nan_chker_("str", row["OODER_NO"])
        bs                  = self.pd_nan_chker_("str", row["SELN_BYOV_CLS"])
        self.seln_byov_cls  = None if bs is None else 'sell' if bs == '01' else 'buy' if bs == '02' else bs
        self.rctf_cls       = self.pd_nan_chker_("str", row["RCTF_CLS"])
        ok                  = self.pd_nan_chker_("str", row["ODER_KIND"])
        self.oder_kind      = None if ok is None else ORD_DVSN(ok).name
        self.oder_cond      = self.pd_nan_chker_("str", row["ODER_COND"])
        self.code           = self.pd_nan_chker_("str", row["STCK_SHRN_ISCD"])
        self.cntg_qty       = self.pd_nan_chker_("int", row["CNTG_QTY"])
        self.cntg_unpr      = self.pd_nan_chker_("int", row["CNTG_UNPR"])
        self.stck_cntg_hour = self.pd_nan_chker_("str", row["STCK_CNTG_HOUR"])
        self.rfus_yn        = self.pd_nan_chker_("str", row["RFUS_YN"])
        self.cntg_yn        = self.pd_nan_chker_("str", row["CNTG_YN"])
        self.acpt_yn        = self.pd_nan_chker_("str", row["ACPT_YN"])
        self.brnc_no        = self.pd_nan_chker_("str", row["BRNC_NO"])
        self.oder_qty       = self.pd_nan_chker_("int", row["ODER_QTY"])
        self.exg_yn         = self.pd_nan_chker_("str", row["EXG_YN"])
        self.exchange       = None if self.exg_yn is None else 'KRX' if self.exg_yn[0] in ['1', '3'] else 'NXT' if self.exg_yn[0] in ['2', '4'] else None
        self.crdt_cls       = self.pd_nan_chker_("str", row["CRDT_CLS"])
        self.oder_prc       = self.pd_nan_chker_("int", row["ODER_PRC"]) 

    @classmethod
    def create_object_from_response(cls, res):
        obj = cls()
        obj._set_data(res)
        return obj

    @staticmethod
    def pd_nan_chker_(casttype, val):
        # values are always str
        return None if pd.isna(val) or val=="" else {"str": str, "int": int, "float": float}[casttype](val)


@dataclass
class TransactionPrices: # 국내주식 실시간체결가 (KRX, but should be the same for NXT, total)
    trprices: pd.DataFrame
    trenv: object = None

    def __post_init__(self):
        if set(self.trprices.columns) != set(self._get_columns(self.trenv)):
            raise Exception("TransactionPrices column names need attention")

    def _get_columns(self, trenv):
        if trenv.env_dv == 'demo': # KRX
            CNTG_CLS_CODE = 'CCLD_DVSN'
        else: 
            CNTG_CLS_CODE = 'CNTG_CLS_CODE' # "CNTG_CLS_CODE" for 'NXT' and 'TOTAL' 
        _columns = [
            "MKSC_SHRN_ISCD", # code
            "STCK_CNTG_HOUR", # hour
            "STCK_PRPR", # 체결가
            "PRDY_VRSS_SIGN", 
            "PRDY_VRSS", 
            "PRDY_CTRT",
            "WGHN_AVRG_STCK_PRC",
            "STCK_OPRC", # opening
            "STCK_HGPR", # high
            "STCK_LWPR", # low
            "ASKP1", # 매도호가1
            "BIDP1", # 매수호가1
            "CNTG_VOL",  # 체결 거래량 
            "ACML_VOL",  # 누적 거래량
            "ACML_TR_PBMN", # 누적 거래 대금 
            "SELN_CNTG_CSNU", # 매도 체결 건수 (1건 = multiple stocks)
            "SHNU_CNTG_CSNU", # 매수 체결 건수
            "NTBY_CNTG_CSNU", # 순매수 체결 건수
            "CTTR",  # 체결강도
            "SELN_CNTG_SMTN",  # 총매도수량 (number of stocks)
            "SHNU_CNTG_SMTN",  # 총매수수량
            CNTG_CLS_CODE,  # 1: 매수(+), 3: 장전, 5: 매도(-)
            "SHNU_RATE", # 매수비율
            "PRDY_VOL_VRSS_ACML_VOL_RATE", # 전일 거래량 대비 등락률
            "OPRC_HOUR", 
            "OPRC_VRSS_PRPR_SIGN",
            "OPRC_VRSS_PRPR",
            "HGPR_HOUR",
            "HGPR_VRSS_PRPR_SIGN",
            "HGPR_VRSS_PRPR",
            "LWPR_HOUR",
            "LWPR_VRSS_PRPR_SIGN",
            "LWPR_VRSS_PRPR",
            "BSOP_DATE", # 영업일자
            "NEW_MKOP_CLS_CODE", # 20: 장중/보통, 32: 장종료후/종가
            "TRHT_YN", # 거래정지 Y/N
            "ASKP_RSQN1", # 매도호가 잔량1
            "BIDP_RSQN1", # 매수호가 잔량1
            "TOTAL_ASKP_RSQN", # 총 매도호가 잔량
            "TOTAL_BIDP_RSQN", # 총 매수호가 잔량
            "VOL_TNRT", # 거래량 회전률
            "PRDY_SMNS_HOUR_ACML_VOL", # 전일 동시간 누적 거래량
            "PRDY_SMNS_HOUR_ACML_VOL_RATE", # 전일 동시간 누적 거래량 비율
            "HOUR_CLS_CODE", # 시간구분코드 0: 장중, A: 장후예상, B: 장전예상, C: 9시 이후의 예상가, VI발동, D: 시간외 단일가 예상
            "MRKT_TRTM_CLS_CODE", # 임의종료구분코드
            "VI_STND_PRC", # 정적VI발동기준가
        ]
        return _columns

    def get_price_quantity_time(self):
        """
        Returns price and quantity and time if there is only one record
        Returns avg(price), sum(quantity), latest(time) if there are more than one record
        """
        if self.trprices.empty:
            return None, None, None

        ################ CHECK NEEDED DATA FORMAT #################
        ################ CHECK NEEDED #################
        ################ CHECK NEEDED #################
        ################ CHECK NEEDED #################
        ################ CHECK NEEDED #################

        if len(self.trprices) == 1:
            record = self.trprices.iloc[0]
            lt = datetime.strptime(record["BSOP_DATE"] +' '+ record['STCK_CNTG_HOUR'], '%Y%m%d %H%M%S')
            return record["STCK_PRPR"], record["CNTG_VOL"], lt

        else:
            qty_sum = self.trprices["CNTG_VOL"].sum()
            pr_avg = (self.trprices["STCK_PRPR"]*self.trprices["CNTG_VOL"]).sum()/qty_sum # qty_sum should not be a zero value
            lt_series = pd.to_datetime(self.trprices["BSOP_DATE"]+' '+self.trprices['STCK_CNTG_HOUR'], format='%Y%m%d %H%M%S')
            return pr_avg, qty_sum, lt_series.max()
