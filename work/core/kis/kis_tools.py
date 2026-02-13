import pandas as pd
from typing import Optional, Tuple
from enum import StrEnum

from .kis_connect import KIS_Connector

class _TR_ID:
    # this class should only be accessed through KIS_Functions class
    def __init__(self, service): # Service 
        if service.is_real():
            self.ORDER_CASH_BUY = "TTTC0012U"
            self.ORDER_CASH_SELL = "TTTC0011U"
            self.RC_ORDER = "TTTC0013U"
            self.GET_PSBL_ORDER = "TTTC8908R"
            self.INQUIRE_BALANCE = "TTTC8434R"
            self.CCNL_NOTICE = "H0STCNI0"
            self.CCNL_KRX = "H0STCNT0"

        else: # demo
            self.ORDER_CASH_BUY = "VTTC0012U"
            self.ORDER_CASH_SELL = "VTTC0011U"
            self.RC_ORDER = "VTTC0013U"
            self.GET_PSBL_ORDER = "VTTC8908R"
            self.INQUIRE_BALANCE = "VTTC8434R"
            self.CCNL_NOTICE = "H0STCNI9"
            self.CCNL_KRX = "H0STCNT0" 
    
    def get_target(self, tr_id):
        if tr_id == self.CCNL_NOTICE:
            return "TransactionNotice"
        elif tr_id in (self.CCNL_KRX, ): # may expand later 
            return "TransactionPrices"

class EXG(StrEnum): # Exchange
    SOR = 'SOR'
    KRX = 'KRX'
    NXT = 'NXT'

class MTYPE(StrEnum): # Match Type
    LIMIT = '00' # SOR, KRX, NXT
    MARKET = '01' # SOR, KRX
    MIDDLE = '21' # KRX, NXT (중간가): works like MARKET 

    def is_allowed_in(self, exchange: EXG) -> bool:
        allowed = {
            MTYPE.LIMIT:  {EXG.SOR, EXG.KRX, EXG.NXT},
            MTYPE.MARKET: {EXG.SOR, EXG.KRX},
            MTYPE.MIDDLE: {EXG.KRX, EXG.NXT},
        }
        return exchange in allowed[self]

class SIDE(StrEnum):
    BUY = 'buy'
    SELL = 'sell'

class KIS_Functions:
    def __init__(self, kc: KIS_Connector): 
        self.kc = kc
        self.tr_id = _TR_ID(kc.service)

    async def order_cash(
        self,
        ord_dv: SIDE,  # 매도매수구분 (buy:매수, sell:매도)
        pdno: str,  # 상품번호 (종목코드)
        mtype: MTYPE,  # 주문구분
        ord_qty: int,  # 주문수량
        ord_unpr: int,  # 주문단가
        excg_id_dvsn_cd: EXG,  # 거래소ID구분코드
        sll_type: str = "",  # 매도유형 (매도주문 시)
        cndt_pric: str = ""  # 조건가격
    ): 
        api_url = "/uapi/domestic-stock/v1/trading/order-cash"
        tr_id = self.tr_id.ORDER_CASH_BUY if ord_dv == SIDE.BUY else self.tr_id.ORDER_CASH_SELL
        params = {
            "CANO": self.kc.account_no,
            "ACNT_PRDT_CD": self.kc.product_no,
            "PDNO": pdno,
            "ORD_DVSN": mtype,
            "ORD_QTY": str(ord_qty), 
            "ORD_UNPR": str(ord_unpr),
            "EXCG_ID_DVSN_CD": excg_id_dvsn_cd,
            "SLL_TYPE": sll_type,
            "CNDT_PRIC": cndt_pric
        }

        res, _ = await self.kc.url_fetch(api_url, tr_id, "", params, post=True)
        if res:
            return res.get('output', None)
        else: 
            return None

    async def order_rvsecncl(
        self, 
        krx_fwdg_ord_orgno: str,  # [필수] 한국거래소전송주문조직번호
        orgn_odno: str,  # [필수] 원주문번호
        mtype: MTYPE,  # [필수] 주문구분
        rvse_cncl_dvsn_cd: str,  # [필수] 정정취소구분코드 (ex. 01:정정,02:취소)
        ord_qty: int,  # [필수] 주문수량
        ord_unpr: int,  # [필수] 주문단가
        qty_all_ord_yn: str,  # [필수] 잔량전부주문여부 (ex. Y:전량, N:일부)
        excg_id_dvsn_cd: EXG,  # [필수] 거래소ID구분코드
        cndt_pric: Optional[str] = ""  # 조건가격
    ):
        api_url = "/uapi/domestic-stock/v1/trading/order-rvsecncl"
        tr_id = self.tr_id.RC_ORDER
        params = {
            "CANO": self.kc.account_no,
            "ACNT_PRDT_CD": self.kc.product_no,
            "KRX_FWDG_ORD_ORGNO": krx_fwdg_ord_orgno,
            "ORGN_ODNO": orgn_odno,
            "ORD_DVSN": mtype,
            "RVSE_CNCL_DVSN_CD": rvse_cncl_dvsn_cd,
            "ORD_QTY": str(ord_qty),
            "ORD_UNPR": str(ord_unpr),
            "QTY_ALL_ORD_YN": qty_all_ord_yn,
            "EXCG_ID_DVSN_CD": excg_id_dvsn_cd, 
        }
        if cndt_pric:
            params["CNDT_PRIC"] = cndt_pric

        res, _ = await self.kc.url_fetch(api_url, tr_id, "", params, post=True)
        if res:
            return res.get('output', None)
        else: 
            return None

    async def get_psbl_order(self, code: str, mtype: MTYPE, price: int):
        if mtype != MTYPE.LIMIT: # MARKET or MIDDLE
            price = 0
        if code is None or code == '':
            code = ' ' # empty space is requried

        api_url = "/uapi/domestic-stock/v1/trading/inquire-psbl-order"
        tr_id = self.tr_id.GET_PSBL_ORDER
        params = {
            "CANO": self.kc.account_no,
            "ACNT_PRDT_CD": self.kc.product_no,
            "PDNO": code,
            "ORD_UNPR": str(price), 
            "ORD_DVSN": mtype,
            "CMA_EVLU_AMT_ICLD_YN": "N", # CMA평가금액포함여부
            "OVRS_ICLD_YN": "N" # 해외포함여부
        }

        res, h = await self.kc.url_fetch(api_url, tr_id, "", params)  
        if res:
            a_ = res.get('output')['nrcvb_buy_amt'] # 미수없는 매수금액
            q_ = res.get('output')['nrcvb_buy_qty'] # 미수없는 매수수량
            p_ = res.get('output')['psbl_qty_calc_unpr'] # 가능수량계산단가(시장가)
            return int(a_), int(q_), int(p_) # returned as int
        else: 
            return None, None, None

    async def inquire_balance(
        self,
        afhr_flpr_yn: str = "N",  # 시간외단일가·거래소여부
        inqr_dvsn: str = "01",  # 조회구분
        unpr_dvsn: str = "01",  # 단가구분
        fund_sttl_icld_yn: str = "N",  # 펀드결제분포함여부
        fncg_amt_auto_rdpt_yn: str = "N",  # 융자금액자동상환여부
        prcs_dvsn: str = "00",  # 처리구분
        FK100: str = "",  # 연속조회검색조건100
        NK100: str = "",  # 연속조회키100
        tr_cont: str = "",  # 연속거래여부
        dataframe1: Optional[pd.DataFrame] = None,  # 누적 데이터프레임1
        dataframe2: Optional[pd.DataFrame] = None,  # 누적 데이터프레임2
        depth: int = 0,  # 내부 재귀깊이 (자동관리)
        max_depth: int = 20  # 최대 재귀 횟수 제한
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        주식 잔고조회 API입니다. 
        실전계좌의 경우, 한 번의 호출에 최대 50건까지 확인 가능하며, 이후의 값은 연속조회를 통해 확인하실 수 있습니다. 
        모의계좌의 경우, 한 번의 호출에 최대 20건까지 확인 가능하며, 이후의 값은 연속조회를 통해 확인하실 수 있습니다. 
        * 당일 전량매도한 잔고도 보유수량 0으로 보여질 수 있으나, 해당 보유수량 0인 잔고는 최종 D-2일 이후에는 잔고에서 사라집니다.
        Args:
            afhr_flpr_yn (str): [필수] 시간외단일가·거래소여부 (ex. N:기본값, Y:시간외단일가, X:NXT)
            inqr_dvsn (str): [필수] 조회구분 (ex. 01 – 대출일별 | 02 – 종목별)
            unpr_dvsn (str): [필수] 단가구분 (ex. 01)
            fund_sttl_icld_yn (str): [필수] 펀드결제분포함여부 (ex. N, Y)
            fncg_amt_auto_rdpt_yn (str): [필수] 융자금액자동상환여부 (ex. N)
            prcs_dvsn (str): [필수] 처리구분 (ex. 00: 전일매매포함, 01:전일매매미포함)
            FK100 (str): 연속조회검색조건100
            NK100 (str): 연속조회키100
            tr_cont (str): 연속거래여부
            dataframe1 (Optional[pd.DataFrame]): 누적 데이터프레임1
            dataframe2 (Optional[pd.DataFrame]): 누적 데이터프레임2
            depth (int): 내부 재귀깊이 (자동관리)
            max_depth (int): 최대 재귀 횟수 제한
        Returns:
            Tuple[pd.DataFrame, pd.DataFrame]: 주식잔고조회 데이터 (output1, output2)
        """

        if depth > max_depth:
            if dataframe1 is None:
                dataframe1 = pd.DataFrame()
            if dataframe2 is None:
                dataframe2 = pd.DataFrame()
            return dataframe1, dataframe2

        api_url = "/uapi/domestic-stock/v1/trading/inquire-balance"
        tr_id = self.tr_id.INQUIRE_BALANCE
        params = {
            "CANO": self.kc.account_no,
            "ACNT_PRDT_CD": self.kc.product_no,
            "AFHR_FLPR_YN": afhr_flpr_yn,
            "OFL_YN": "",
            "INQR_DVSN": inqr_dvsn,
            "UNPR_DVSN": unpr_dvsn,
            "FUND_STTL_ICLD_YN": fund_sttl_icld_yn,
            "FNCG_AMT_AUTO_RDPT_YN": fncg_amt_auto_rdpt_yn,
            "PRCS_DVSN": prcs_dvsn,
            "CTX_AREA_FK100": FK100,
            "CTX_AREA_NK100": NK100
        }
        
        res, h = await self.kc.url_fetch(api_url, tr_id, tr_cont, params) 

        if res is None or h is None:
            return None, None

        current_data1 = pd.DataFrame(res.get('output1'))
        if dataframe1 is not None:
            dataframe1 = pd.concat([dataframe1, current_data1], ignore_index=True)
        else:
            dataframe1 = current_data1

        current_data2 = pd.DataFrame(res.get('output2'))
        if dataframe2 is not None:
            dataframe2 = pd.concat([dataframe2, current_data2], ignore_index=True)
        else:
            dataframe2 = current_data2

        tr_cont = h['tr_cont']
        FK100 = res['ctx_area_fk100']
        NK100 = res['ctx_area_nk100']

        if tr_cont in ["M", "F"]:  # 다음 페이지 존재
            print("calling next page...") # no need to log...
            return await self.inquire_balance(
                afhr_flpr_yn, inqr_dvsn, unpr_dvsn,
                fund_sttl_icld_yn, fncg_amt_auto_rdpt_yn, prcs_dvsn, FK100, NK100,
                "N", dataframe1, dataframe2, depth + 1, max_depth
            )
        else:
            return dataframe1, dataframe2

    # ------------------------------------------------------------------------------
    # websocket subscription functions
    # ------------------------------------------------------------------------------
    # tr_type: [필수] 구독 등록("1") 또는 해제("2")

    async def ccnl_notice(self, subs=True): # default subscription
        if subs:
            tr_type = "1" # subscription
        else: 
            tr_type = "2" # unsubscription
        tr_id = self.tr_id.CCNL_NOTICE
        tr_key = self.kc.htsid # tr_key: htsid
        await self.kc.ws_send(tr_type, tr_id, tr_key)

    # tr_key: code
    async def ccnl_krx(self, tr_key: str, subs=True):
        if subs:
            tr_type = "1" # subscription
        else: 
            tr_type = "2" # unsubscription
        tr_id = self.tr_id.CCNL_KRX
        await self.kc.ws_send(tr_type, tr_id, tr_key)

    # expand to include other functions if needed
