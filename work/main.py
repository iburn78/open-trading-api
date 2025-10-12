from gen_tools import *
get_logger("main", "log/main.log", level=logging.DEBUG)

from kis_tools import *
from local_comm import send_command
from strategy import *
from agent import *

# main.py -----------------------------------------------------------
# Account 정보 관리
# - the_account
# - Server에서 정보 읽어옴
# - Update (not yet implemented)
# AgentManager 
# - TradeTarget으로 trade_target 수신
# - trade_target 및 the_account 감안해서 book 생성
# - agents의 보관: agents 
# - agents의 active 여부, 행동 관리 
# - agents의 성과관리 (not yet implemented)


# ---------------------------------
# Account
# ---------------------------------

port = '5001'
trenv = asyncio.run(send_command('get_trenv')) 

the_account = Account().acc_load(trenv)
optlog.info(the_account)

# ---------------------------------
# Target setting and agent creation
# ---------------------------------
trade_target = TradeTarget(the_account=the_account) # trade_target never changes while running
agent_manager = AgentManager(trade_target=trade_target)