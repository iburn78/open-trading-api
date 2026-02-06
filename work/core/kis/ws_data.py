from datetime import datetime
from collections import namedtuple

from .kis_tools import SIDE, MTYPE, EXG
from ..base.tools import excel_round_vector, cast_or_none
from ..model.cost import CostCalculator
from ..model.aux_info import AuxInfo

# ------------------------------------------------------
# 국내주식 실시간체결통보
# ------------------------------------------------------
TRNoticeColumns = [
    "CUST_ID", 
    "ACNT_NO", 
    "ODER_NO", 
    # "ODER_QTY",
    "OODER_NO", 
    "SELN_BYOV_CLS", 
    "RCTF_CLS",
    "ODER_KIND", "ODER_COND", "STCK_SHRN_ISCD", "CNTG_QTY", "CNTG_UNPR",
    "STCK_CNTG_HOUR", "RFUS_YN", "CNTG_YN", "ACPT_YN", "BRNC_NO", 
    # "ACNT_NO2",
    "ODER_QTY",
    "ACNT_NAME", 
    # "ORD_COND_PRC", 
    # "ORD_EXG_GB", "POPUP_YN", 
    "EXG_YN", # combination of "ORD_EXG_GB", "POPUP_YN", 
    # "FILLER", 
    "CRDT_CLS",
    "CRDT_LOAN_DATE", 
    "CNTG_ISNM40", 
    "ODER_PRC"
]
TRNoticeData = namedtuple('TRNoticeData', TRNoticeColumns)

class TransactionNotice: 
    """
    note: oder_kind set to '00'(LIMIT) in 체결확인(022) reponses even when the order is MARKET 
    {self.rfus_yn}{self.cntg_yn}{self.acpt_yn} 
    - 011: order accepted
    - 012: cancel or revise completed
    - 022: order processed
    """
    def __init__(self, n_rows, d, aux_info): # d is a list of data
        assert n_rows == 1, f"expected n_rows=1, got {n_rows}"
        trn_data = TRNoticeData(*d)

        self.acnt_no        = cast_or_none("str", trn_data.ACNT_NO) # account number
        self.order_no       = cast_or_none("str", trn_data.ODER_NO) # order number
        self.orignal_order_no       = cast_or_none("str", trn_data.OODER_NO) # original order number 
        bs                  = cast_or_none("str", trn_data.SELN_BYOV_CLS) # 01: sell, 02: buy
        self.seln_byov_cls  = None if bs is None else SIDE.SELL if bs == '01' else SIDE.BUY if bs == '02' else bs
        self.rctf_cls       = cast_or_none("str", trn_data.RCTF_CLS) # 0:정상, 1:정정, 2:취소
        ok                  = cast_or_none("str", trn_data.ODER_KIND) # 00: limit, 01: market
        self.oder_kind      = None if ok is None else MTYPE(ok)
        self.oder_cond      = cast_or_none("str", trn_data.ODER_COND) # 0: None, 1: IOC (Immediate or Cancel), 2: FOK (Fill or Kill)
        self.code           = cast_or_none("str", trn_data.STCK_SHRN_ISCD)
        self.cntg_qty       = cast_or_none("int", trn_data.CNTG_QTY) # traded quantity
        self.cntg_unpr      = cast_or_none("int", trn_data.CNTG_UNPR) # traded price
        self.stck_cntg_hour = cast_or_none("str", trn_data.STCK_CNTG_HOUR) # traded time (HHMMSS)
        self.rfus_yn        = cast_or_none("str", trn_data.RFUS_YN) # 0: 승인, 1: 거부 
        self.cntg_yn        = cast_or_none("str", trn_data.CNTG_YN) # 1: 주문, 정정, 취소, 거부, 2: 체결 
        self.acpt_yn        = cast_or_none("str", trn_data.ACPT_YN) # 1: 주문접수, 2: 확인, 3: 취소(IOC/FOK)
        self.brnc_no        = cast_or_none("str", trn_data.BRNC_NO) # 지점번호
        self.oder_qty       = cast_or_none("int", trn_data.ODER_QTY) # total order quantity  
        self.exg_yn         = cast_or_none("str", trn_data.EXG_YN) # 1:KRX, 2:NXT, 3:SOR-KRX, 4:SOR-NXT + 실시간체결창 표시여부(Y/N)
        self.traded_exchange= None if self.exg_yn is None else EXG.KRX if self.exg_yn[0] in ['1', '3'] else EXG.NXT if self.exg_yn[0] in ['2', '4'] else None
        self.crdt_cls       = cast_or_none("str", trn_data.CRDT_CLS) # 신용구분 
        self.oder_prc       = cast_or_none("int", trn_data.ODER_PRC) # order price    
        self.checker_code   = self.rfus_yn + self.cntg_yn + self.acpt_yn
        self.fee_, self.tax_= self._fee_tax(aux_info)

    def __str__(self):
        return (
            f"[TR notice] {self.code}, "
            f"no {self.order_no} / {self.orignal_order_no} {self.checker_code} cnd {self.oder_cond} {self.traded_exchange.name} "
            f"{self.seln_byov_cls.name} {self.oder_kind.name} P:{self.cntg_unpr} Q:{self.oder_qty} pr:{self.cntg_qty}"
        )

    def _fee_tax(self, aux_info: AuxInfo):
        if self.checker_code == "022":
            fee_, tax_ = CostCalculator.calculate(
                side = self.seln_byov_cls,
                quantity = self.cntg_qty, 
                price = self.cntg_unpr,
                service = aux_info.service,
                listed_market = aux_info.code_market_map.get(self.code),
                traded_exchange = self.traded_exchange
            )
        else: 
            fee_, tax_ = 0, 0
        return fee_, tax_

# ------------------------------------------------------
# MarketPrices 국내주식 실시간체결가 (KRX)
# ------------------------------------------------------
TRPriceColumns = [
    "MKSC_SHRN_ISCD", # code
    "STCK_CNTG_HOUR", # hour (%H%M%S) | note: it shows sometimes future time in Demo server (at least in the Demo server)
    "STCK_PRPR", # 체결가
    "PRDY_VRSS_SIGN", 
    "PRDY_VRSS", 
    "PRDY_CTRT",
    "WGHN_AVRG_STCK_PRC", # Definition is not known (may be from the start of the market)
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
    "CCLD_DVSN",  # 1: 매수(+), 3: 장전, 5: 매도(-) # "CNTG_CLS_CODE" for 'NXT' and 'TOTAL' 
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
    "BSOP_DATE", # 영업일자 (%Y%m%d)
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
TRPriceData = namedtuple('TRPriceData', TRPriceColumns)

class TransactionPrices:
    n_cols = len(TRPriceColumns)

    def __init__(self, n_rows, d):
        assert len(d) == n_rows * self.n_cols, (
            f"TRP data {len(d)} cols {self.n_cols} x rows {n_rows} mismatch"
        )
        self.records = [
            TRPriceData(*d[i:i + self.n_cols])
            for i in range(0, n_rows * self.n_cols, self.n_cols)
        ]
        self.time = datetime.now()
        if not self.records:
            self.code = ""
            self.price = None
            self.quantity = 0
            return

        self.code = self.records[0].MKSC_SHRN_ISCD
        self.price = int(self.records[-1].STCK_PRPR)
        self.quantity = sum(int(r.CNTG_VOL) for r in self.records)

    def __str__(self):
        parts = [f"[TR prices] {self.code}:"]
        for r in self.records:
            parts.append(f"    {r.STCK_CNTG_HOUR} {r.STCK_PRPR} {r.CNTG_VOL}")
        return '\n'.join(parts)
