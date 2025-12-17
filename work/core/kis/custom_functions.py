import pandas as pd
import httpx
from typing import Optional

from . import kis_auth as ka

##############################################################################################
# [국내주식] 주문/계좌 > 주식주문(현금)[v1_국내주식-001]
##############################################################################################
# modified to use _url_fetch_async

async def order_cash_async(
        _http: httpx.AsyncClient,
        env_dv: str,  # 실전모의구분 (real:실전, demo:모의)
        ord_dv: str,  # 매도매수구분 (buy:매수, sell:매도)
        cano: str,  # 종합계좌번호
        acnt_prdt_cd: str,  # 계좌상품코드
        pdno: str,  # 상품번호 (종목코드)
        ord_dvsn: str,  # 주문구분
        ord_qty: str,  # 주문수량
        ord_unpr: str,  # 주문단가
        excg_id_dvsn_cd: str,  # 거래소ID구분코드
        sll_type: str = "",  # 매도유형 (매도주문 시)
        cndt_pric: str = ""  # 조건가격
) -> pd.DataFrame:

    # 필수 파라미터 검증
    if env_dv == "" or env_dv is None:
        raise ValueError("env_dv is required (e.g. 'real:실전, demo:모의')")

    if ord_dv == "" or ord_dv is None:
        raise ValueError("ord_dv is required (e.g. 'buy:매수, sell:매도')")

    if cano == "" or cano is None:
        raise ValueError("cano is required (e.g. '종합계좌번호')")

    if acnt_prdt_cd == "" or acnt_prdt_cd is None:
        raise ValueError("acnt_prdt_cd is required (e.g. '상품유형코드')")

    if pdno == "" or pdno is None:
        raise ValueError("pdno is required (e.g. '종목코드(6자리) , ETN의 경우 7자리 입력')")

    if ord_dvsn == "" or ord_dvsn is None:
        raise ValueError("ord_dvsn is required (e.g. '')")

    if ord_qty == "" or ord_qty is None:
        raise ValueError("ord_qty is required (e.g. '')")

    if ord_unpr == "" or ord_unpr is None:
        raise ValueError("ord_unpr is required (e.g. '')")

    if excg_id_dvsn_cd == "" or excg_id_dvsn_cd is None:
        raise ValueError("excg_id_dvsn_cd is required (e.g. 'KRX')")

    # tr_id 설정
    if env_dv == "real":
        if ord_dv == "sell":
            tr_id = "TTTC0011U"
        elif ord_dv == "buy":
            tr_id = "TTTC0012U"
        else:
            raise ValueError("ord_dv can only be sell or buy")
    elif env_dv == "demo":
        if ord_dv == "sell":
            tr_id = "VTTC0011U"
        elif ord_dv == "buy":
            tr_id = "VTTC0012U"
        else:
            raise ValueError("ord_dv can only be sell or buy")
    else:
        raise ValueError("env_dv is required (e.g. 'real' or 'demo')")

    api_url = "/uapi/domestic-stock/v1/trading/order-cash"

    params = {
        "CANO": cano,  # 종합계좌번호
        "ACNT_PRDT_CD": acnt_prdt_cd,  # 계좌상품코드
        "PDNO": pdno,  # 상품번호
        "ORD_DVSN": ord_dvsn,  # 주문구분
        "ORD_QTY": ord_qty,  # 주문수량
        "ORD_UNPR": ord_unpr,  # 주문단가
        "EXCG_ID_DVSN_CD": excg_id_dvsn_cd,  # 거래소ID구분코드
        "SLL_TYPE": sll_type,  # 매도유형
        "CNDT_PRIC": cndt_pric  # 조건가격
    }

    res = await ka._url_fetch_async(_http, api_url, tr_id, "", params, postFlag=True)

    if res.isOK():
        current_data = pd.DataFrame([res.getBody().output])
        return current_data
    else:
        res.printError(url=api_url)
        return pd.DataFrame()


##############################################################################################
# [국내주식] 주문/계좌 > 주식주문(정정취소)[v1_국내주식-003]
##############################################################################################
# modified to use _url_fetch_async

async def order_rvsecncl_async(
        _http: httpx.AsyncClient,
        env_dv: str,  # [필수] 실전모의구분 (ex. real:실전, demo:모의)
        cano: str,  # [필수] 종합계좌번호
        acnt_prdt_cd: str,  # [필수] 계좌상품코드
        krx_fwdg_ord_orgno: str,  # [필수] 한국거래소전송주문조직번호
        orgn_odno: str,  # [필수] 원주문번호
        ord_dvsn: str,  # [필수] 주문구분
        rvse_cncl_dvsn_cd: str,  # [필수] 정정취소구분코드 (ex. 01:정정,02:취소)
        ord_qty: str,  # [필수] 주문수량
        ord_unpr: str,  # [필수] 주문단가
        qty_all_ord_yn: str,  # [필수] 잔량전부주문여부 (ex. Y:전량, N:일부)
        excg_id_dvsn_cd: str,  # [필수] 거래소ID구분코드 (ex. KRX: 한국거래소, NXT:대체거래소,SOR:SOR)
        cndt_pric: Optional[str] = ""  # 조건가격
) -> pd.DataFrame:

    # 필수 파라미터 검증
    if env_dv == "" or env_dv is None:
        raise ValueError("env_dv is required (e.g. 'real', 'demo')")

    if cano == "" or cano is None:
        raise ValueError("cano is required")

    if acnt_prdt_cd == "" or acnt_prdt_cd is None:
        raise ValueError("acnt_prdt_cd is required")

    if krx_fwdg_ord_orgno == "" or krx_fwdg_ord_orgno is None:
        raise ValueError("krx_fwdg_ord_orgno is required")

    if orgn_odno == "" or orgn_odno is None:
        raise ValueError("orgn_odno is required")

    if ord_dvsn == "" or ord_dvsn is None:
        raise ValueError("ord_dvsn is required")

    if rvse_cncl_dvsn_cd == "" or rvse_cncl_dvsn_cd is None:
        raise ValueError("rvse_cncl_dvsn_cd is required (e.g. '01', '02')")

    if ord_qty == "" or ord_qty is None:
        raise ValueError("ord_qty is required")

    if ord_unpr == "" or ord_unpr is None:
        raise ValueError("ord_unpr is required")

    if qty_all_ord_yn == "" or qty_all_ord_yn is None:
        raise ValueError("qty_all_ord_yn is required (e.g. 'Y', 'N')")

    if excg_id_dvsn_cd == "" or excg_id_dvsn_cd is None:
        raise ValueError("excg_id_dvsn_cd is required (e.g. 'KRX', 'NXT', 'SOR')")

    # tr_id 설정
    if env_dv == "real":
        tr_id = "TTTC0013U"
    elif env_dv == "demo":
        tr_id = "VTTC0013U"
    else:
        raise ValueError("env_dv is required (e.g. 'real' or 'demo')")

    api_url = "/uapi/domestic-stock/v1/trading/order-rvsecncl"

    params = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt_prdt_cd,
        "KRX_FWDG_ORD_ORGNO": krx_fwdg_ord_orgno,
        "ORGN_ODNO": orgn_odno,
        "ORD_DVSN": ord_dvsn,
        "RVSE_CNCL_DVSN_CD": rvse_cncl_dvsn_cd,
        "ORD_QTY": ord_qty,
        "ORD_UNPR": ord_unpr,
        "QTY_ALL_ORD_YN": qty_all_ord_yn,
        "EXCG_ID_DVSN_CD": excg_id_dvsn_cd
    }

    # 옵션 파라미터 추가
    if cndt_pric:
        params["CNDT_PRIC"] = cndt_pric

    res = await ka._url_fetch_async(_http, api_url, tr_id, "", params, postFlag=True)

    if res.isOK():
        return pd.DataFrame([res.getBody().output])
    else:
        res.printError(url=api_url)
        return pd.DataFrame()
