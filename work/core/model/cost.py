from ..common.optlog import log_raise 
from ..common.tools import excel_round_int
from ..kis.ws_data import SIDE, EXCHANGE

# ----------------------------------------
# Transaction cost calculation
# ----------------------------------------
class CostCalculator:
    # all data: percent
    # 한투수수료 (유관기관수수료 포함)
    FEE = {
        'KRX': 0.0140527, 
        'NXT': {
            'maker': 0.0130527, 
            'taker': 0.0130527, 
            'settle': 0.0130527, 
        } 
    }

    # 유관기관수수료
    # from December 2025, KRX fee changes from 0.0023% to 0.00134% (maker) 0.00182% (taker): need to check
    MIN_FEE = {
        'KRX': 0.0036396, 
        'NXT': {
            'maker': 0.0031833, 
            'taker': 0.0031833, 
            'settle': 0.0031833, 
        } 
    }  

    # percent
    TAX = {  
        # On-exchange (장내)
        'KOSPI': {
            'TransactionTax': 0, 
            'RuralDevTax': 0.15,
        },
        'KOSDAQ': {
            'TransactionTax': 0.15, 
            'RuralDevTax': 0,
        },
        # OTC (장외) including 비상장
        # Below is not allowed in this code yet... 
        'OTC': {
            'TransactionTax': 0.35, 
            'RuralDevTax': 0,
        }
        # KONEX, K-OTC ... 
    }

    # rounding rule 
    RD_rule = { 
        # 0: # 1원 미만 rounding
        # -1: # 10원 미만 rounding 
        'FEE': -1, 
        'MIN_FEE': 0, 
        'TAX': 0, 
    }

    @classmethod
    def get_fee_table(cls, account):
        if account == "prod":  # 국내주식수수료 면제 (유관기관수수료만 부담)
            return cls.MIN_FEE, cls.RD_rule['MIN_FEE'], cls.RD_rule['TAX']
        elif account == "auto":
            return cls.FEE, cls.RD_rule['FEE'], cls.RD_rule['TAX']
        elif account == "vps":
            return cls.FEE, cls.RD_rule['FEE'], cls.RD_rule['TAX']
        else:
            log_raise("Check in cost calculation: possibly trenv issue ---")

    # 각각의 Order가 중간 체결 될때는 각 Fee 및 Tax를 float로 합산하고, 매 순간 Excel Rounding (int) 진행함
    # 완료되거나 중단될 경우, rounded 값 사용
    # 보수적 접근으로 실제 증권사 Logic을 정확히 알 수 없으므로 근사치임 (체결간 시간 간격등 추가 Rule이 있을 수 있음)
    @classmethod
    def calculate(cls, side: SIDE, quantity, price, market, svr, traded_exchange=None, maker_taker="taker"): # default to be conservative
        if traded_exchange is None: 
            traded_exchange = EXCHANGE.KRX # default to be conservative

        fee_table, fee_rd_rule, tax_rd_rule = cls.get_fee_table(svr)
        if traded_exchange == EXCHANGE.KRX:
            fee = fee_table[traded_exchange.value]
        else:
            fee = fee_table[traded_exchange.value][maker_taker]

        if side == SIDE.BUY:
            tax = 0
        else: 
            tax = cls.TAX[market]['TransactionTax'] + cls.TAX[market]['RuralDevTax']
        
        fee_float = quantity*price*fee/100
        tax_float = quantity*price*tax/100

        return fee_float, tax_float, fee_rd_rule, tax_rd_rule

    # 보수적으로 보았을때에 매각시 수익이 0가 되는 total cost의 계산
    # 일단 전체 보유 Amount로만 추정... 
    # 하나의 order quantity에 매수/매도가 여러번 있을수 있다보니, rounding 에러가 발생, 오차 발생 가능
    @classmethod
    def bep_cost_calculate(cls, quantity, avg_price, market, svr): 
        exchange = "KRX"  # default to be conservative
        fee_table, fee_rd_rule, tax_rd_rule = cls.get_fee_table(svr)
        fee_percent = fee_table[exchange]
        tax_percent = cls.TAX[market]['TransactionTax'] + cls.TAX[market]['RuralDevTax']

        bep_rate = (2*fee_percent/100+tax_percent/100)/(1-(fee_percent/100+tax_percent/100))
        bep_cost = excel_round_int(quantity*avg_price*bep_rate)
        bep_price = (quantity*avg_price + bep_cost)/quantity

        return bep_cost, bep_price