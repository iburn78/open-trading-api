from ..common.optlog import log_raise 
from ..common.tools import excel_round
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

    DEMO_FEE = {
        'KRX': 0.0142, 
        'NXT': 0.0142,
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
            'TransactionTax': 0, # to increase to 0.05 (2026.1.1)
            'RuralDevTax': 0.15,
        },
        'KOSDAQ': {
            'TransactionTax': 0.15, # to increase to 0.20 (2026.1.1)
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
        'FEE': 0, # maybe -1; need check (seems better tracking with 0)
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
            return cls.DEMO_FEE, cls.RD_rule['FEE'], cls.RD_rule['TAX']
        else:
            log_raise("Check in cost calculation: possibly trenv issue ---")

    # 각각의 Order가 중간 체결 될때는 각 Fee 및 Tax를 float로 합산하고, 매 순간 Excel Rounding (int) 진행함
    # 완료되거나 중단될 경우, rounded 값 사용
    # 보수적 접근으로 실제 증권사 Logic을 정확히 알 수 없으므로 근사치임 (체결간 시간 간격등 추가 Rule이 있을 수 있음)
    @classmethod
    def calculate(cls, side: SIDE, quantity, price, listed_market, svr, traded_exchange=None, maker_taker="taker"): # default to be conservative
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
            tax = cls.TAX[listed_market]['TransactionTax'] + cls.TAX[listed_market]['RuralDevTax']
        
        fee_ = excel_round(quantity*price*fee/100, fee_rd_rule)
        tax_ = excel_round(quantity*price*tax/100, tax_rd_rule)

        return fee_, tax_

    # 매각시 수익이 0 이 되는 total cost의 계산
    @classmethod
    def bep_cost_calculate(cls, quantity, avg_price, listed_market, svr): 
        exchange = "KRX"  # default to be conservative
        fee_table, fee_rd_rule, tax_rd_rule = cls.get_fee_table(svr)
        fee_percent = fee_table[exchange]
        tax_percent = cls.TAX[listed_market]['TransactionTax'] + cls.TAX[listed_market]['RuralDevTax']

        bep_rate = (1+fee_percent/100)/(1-(fee_percent/100+tax_percent/100))
        bep_cost = quantity*avg_price*(bep_rate-1) 
        bep_price = avg_price*bep_rate 

        # return as floats
        return bep_cost, bep_price
