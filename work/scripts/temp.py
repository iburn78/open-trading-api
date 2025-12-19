from core.common.optlog import set_logger
set_logger()

from core.model.account import *
import core.kis.kis_auth as ka
import asyncio

svr = 'vps' # prod, auto, vps
ka.auth(svr)
trenv = ka.getTREnv()

the_account = Account()
async def ta():
    task = asyncio.create_task(the_account.acc_load(trenv), name="load_acc_task")
    await asyncio.gather(task)
asyncio.run(ta())
print(the_account)

