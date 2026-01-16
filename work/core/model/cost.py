from ..base.settings import Service
from ..base.tools import excel_round
from ..kis.ws_data import SIDE, EXG

# ----------------------------------------
# Transaction cost calculation
# ----------------------------------------
class CostCalculator:
    # all data: percent

    # 유관기관수수료
    # KRX fee to changes from 0.0023% to the same as NXT 0.00134% (maker) 0.00182% (taker): temporary two months until Feb
    # below from KIS 
    MIN_FEE = {
        'KRX': 0.0036396, 
        'NXT': {
            'maker': 0.0031833, 
            'taker': 0.0031833, 
            'settle': 0.0031833, 
        } 
    }  

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

    # percent
    TAX = {  
        # On-exchange (장내)
        'KOSPI': {
            'TransactionTax': 0.05, # increased to 0.05 (2026.1.1)
            'RuralDevTax': 0.15,
        },
        'KOSDAQ': {
            'TransactionTax': 0.20, # increased to 0.20 (2026.1.1)
            'RuralDevTax': 0,
        },

        # OTC (장외) including 비상장
        # - below is not implemented yet... 
        'OTC': {
            'TransactionTax': 0.35, 
            'RuralDevTax': 0,
        }
        # KONEX, K-OTC ... 
    }

    # rounding rule 
    # 0: # 1원 미만 rounding
    # -1: # 10원 미만 rounding 
    # 체결 단위로 계산하고, 주문/일 단위로 합산한 뒤 1회 절사, 국내 증권사 수수료 라운딩의 사실상 표준
    RD_rule = { 
        'MIN_FEE': 0, 
        'FEE': 0, 
        'TAX': 0, 
    }

    @classmethod
    def get_fee_table(cls, service: Service):
        if service == Service.PROD:  # 국내주식수수료 면제 (유관기관수수료만 부담)
            return cls.MIN_FEE, cls.RD_rule['MIN_FEE'], cls.RD_rule['TAX']
        elif service == Service.AUTO:
            return cls.FEE, cls.RD_rule['FEE'], cls.RD_rule['TAX']
        elif service == Service.DEMO:
            return cls.DEMO_FEE, cls.RD_rule['FEE'], cls.RD_rule['TAX']

    # 각각의 Order가 중간 체결 될때는 각 Fee 및 Tax를 float로 합산하고, 매 순간 Excel Rounding (int) 진행함
    # 완료되거나 중단될 경우, rounded 값 사용
    @classmethod
    def calculate(cls, side: SIDE, quantity, price, service, listed_market=None, traded_exchange=None, maker_taker="taker"): 
        # default to be conservative
        if listed_market is None:
            listed_market = 'KOSPI'
        if traded_exchange is None: 
            traded_exchange = EXG.KRX

        fee_table, fee_rd_rule, tax_rd_rule = cls.get_fee_table(service)
        if traded_exchange == EXG.KRX:
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
    def bep_cost_calculate(cls, quantity, avg_price, service: Service): 
        # default to be conservative
        traded_exchange = EXG.KRX 
        listed_market = 'KOSPI'

        fee_table, fee_rd_rule, tax_rd_rule = cls.get_fee_table(service)
        fee_percent = fee_table[traded_exchange.value]
        tax_percent = cls.TAX[listed_market]['TransactionTax'] + cls.TAX[listed_market]['RuralDevTax']

        bep_rate = (1+fee_percent/100)/(1-(fee_percent/100+tax_percent/100))
        bep_cost = quantity*avg_price*(bep_rate-1) 
        bep_price = avg_price*bep_rate 

        # return as floats
        return bep_cost, bep_price
