from .ws_data import ORD_DVSN
from .domestic_stock_functions import inquire_psbl_order

# Note: KIS API related func runs should be done in server side

# this takes API usage frequency limit, so use with care
def get_psbl_order(trenv, code: str, ord_dvsn: ORD_DVSN, price: int):
    if ord_dvsn == ORD_DVSN.MARKET:
        price = 0
    if code is None or code == '':
        code = ' ' # empty space is requried

    res = inquire_psbl_order(
        env_dv = trenv.env_dv,  
        cano = trenv.my_acct,  # 종합계좌번호
        acnt_prdt_cd = trenv.my_prod,  # 계좌상품코드
        pdno = code,  # 상품번호
        ord_unpr = str(price),  # 주문단가
        ord_dvsn = ord_dvsn.value,  # 주문구분
        cma_evlu_amt_icld_yn = 'N',  # CMA평가금액포함여부
        ovrs_icld_yn = 'N'  # 해외포함여부
    )

    a_ = res['nrcvb_buy_amt'].iloc[0] # 미수없는 매수금액
    q_ = res['nrcvb_buy_qty'].iloc[0] # 미수없는 매수수량
    p_ = res['psbl_qty_calc_unpr'].iloc[0] # 가능수량계산단가(시장가)

    return int(a_), int(q_), int(p_)