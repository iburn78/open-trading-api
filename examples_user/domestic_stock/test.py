import sys
import logging

import pandas as pd

sys.path.extend(['..', '.'])
import kis_auth as ka
from domestic_stock_functions_ws import *

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 인증
ka.auth()
ka.auth_ws()
trenv = ka.getTREnv()

# 웹소켓 선언
kws = ka.KISWebSocket(api_url="/tryitout")

kws.subscribe(request=asking_price_krx, data=["005930", "000660"])


# 시작
def on_result(ws, tr_id, result, data_info):
    print(result)

kws.start(on_result=on_result)




