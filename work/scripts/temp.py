import core.kis.kis_auth as ka
from core.model.account import Account, CashBalance, Holding


svr = 'vps' # prod, auto, vps
ka.auth(svr)
ka.auth_ws(svr)
trenv = ka.getTREnv()

a = Account()
a.acc_load(trenv)
print(a)


# - feedback required for strategy command by strategy.
# - agent initial status has to be defined (holding, and initial cash)
# - boundary condition to be set : holding >= 0, t2 cash to be positive (with margin)
# - safety margin to be XX% of remaining t2 cash
# - implement checking max order possible (to check possible order amount)
# - market: -25%, limit: -1.2% etc (may set -30%, -5%)
