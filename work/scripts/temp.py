# import core.kis.kis_auth as ka
# from core.model.account import Account, CashBalance, Holding
# from core.model.order import get_psbl_order
from core.kis.ws_data import ORD_DVSN

print(ORD_DVSN('0'))

# svr = 'vps' # prod, auto, vps
# ka.auth(svr)
# ka.auth_ws(svr)
# trenv = ka.getTREnv()

# # a = Account()
# # a.acc_load(trenv)
# # print(a)

# code = '000660'
# price = 50000

# ord = ORD_DVSN.LIMIT

# get_psbl_order(trenv, code, ord, price)



# 초당 거래건수 초과시, Graceful handling
# Look for log... B1> received order without Order No. 
# this case -> let agent/strategy know (feedback) and handle rewind 2:35