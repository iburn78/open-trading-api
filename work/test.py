import sys
import logging

import pandas as pd

sys.path.extend(['..', '.'])
import kis_auth as ka
from domestic_stock_functions_ws import *
from domestic_stock_functions import *

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 인증
ka.auth()
ka.auth_ws()
trenv = ka.getTREnv()

# 웹소켓 선언
# kws = ka.KISWebSocket(api_url="/tryitout")

# kws.subscribe(request=asking_price_krx, data=["005930", "000660"])


# 시작
# def on_result(ws, tr_id, result, data_info):
#     print(result)

# kws.start(on_result=on_result)

##############################################################################################
# [국내주식] 주문/계좌 > 주식잔고조회[v1_국내주식-006]
##############################################################################################

result1, result2 = inquire_balance(
    cano=trenv.my_acct,
    env_dv="real",
    acnt_prdt_cd=trenv.my_prod,
    afhr_flpr_yn="N",
    inqr_dvsn="01",
    unpr_dvsn="01",
    fund_sttl_icld_yn="N",
    fncg_amt_auto_rdpt_yn="N",
    prcs_dvsn="00"
)
print(result1)
print(result1.to_string())
print(result2)
print(result2.to_string())

##############################################################################################
# [국내주식] 주문/계좌 > 주식잔고조회_실현손익[v1_국내주식-041]
##############################################################################################

result1, result2 = inquire_balance_rlz_pl(
    cano=trenv.my_acct,
    acnt_prdt_cd=trenv.my_prod,
    afhr_flpr_yn="N",
    inqr_dvsn="02",
    unpr_dvsn="01",
    fund_sttl_icld_yn="N",
    fncg_amt_auto_rdpt_yn="N",
    prcs_dvsn="01",
    cost_icld_yn="N"
)
print(result1)
print(result1.to_string())
print(result2)
print(result2.to_string())

# ##############################################################################################
# # [국내주식] 종목정보 > 상품기본조회[v1_국내주식-029]
# ##############################################################################################

# df = search_info(pdno="000660", prdt_type_cd="300")
# print(df.columns)
# print(df)
# print(df.to_string())

# ##############################################################################################
# # [국내주식] 종목정보 > 주식기본조회[v1_국내주식-067]
# ##############################################################################################

# df = search_stock_info(prdt_type_cd="300", pdno="005930")
# print(df.columns)
# print(df)
# print(df.to_string())

# ##############################################################################################
# # [국내주식] 종목정보 > 국내주식 대차대조표 [v1_국내주식-078]
# ##############################################################################################

# df = finance_balance_sheet(fid_div_cls_code="1", fid_cond_mrkt_div_code="J", fid_input_iscd="000660")
# print(df)
# time.sleep(1)

# ##############################################################################################
# # [국내주식] 종목정보 > 국내주식 재무비율 [v1_국내주식-080]
# ##############################################################################################

# df = finance_financial_ratio(fid_div_cls_code="1", fid_cond_mrkt_div_code="J", fid_input_iscd="000660")
# print(df)
# time.sleep(1)

# ##############################################################################################
# # [국내주식] 종목정보 > 국내주식 성장성비율 [v1_국내주식-085]
# ##############################################################################################

# df = finance_growth_ratio(fid_input_iscd="000660", fid_div_cls_code="1", fid_cond_mrkt_div_code="J")
# print(df)
# time.sleep(1)

# ##############################################################################################
# # [국내주식] 종목정보 > 국내주식 손익계산서 [v1_국내주식-079]
# ##############################################################################################

# df = finance_income_statement(fid_div_cls_code="1", fid_cond_mrkt_div_code="J", fid_input_iscd="000660")
# print(df)
# time.sleep(1)

# ##############################################################################################
# # [국내주식] 종목정보 > 국내주식 기타주요비율[v1_국내주식-082]
# ##############################################################################################

# df = finance_other_major_ratios(fid_input_iscd="000660", fid_div_cls_code="1", fid_cond_mrkt_div_code="J")
# print(df)
# time.sleep(1)

# ##############################################################################################
# # [국내주식] 종목정보 > 국내주식 수익성비율[v1_국내주식-081]
# ##############################################################################################

# df = finance_profit_ratio(fid_input_iscd="000660", fid_div_cls_code="1", fid_cond_mrkt_div_code="J")
# print(df)
# time.sleep(1)


