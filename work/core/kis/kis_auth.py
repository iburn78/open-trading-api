# -*- coding: utf-8 -*-
# ====|  (REST) 접근 토큰 / (Websocket) 웹소켓 접속키 발급 에 필요한 API 호출 샘플 아래 참고하시기 바랍니다.  |=====================
# ====|  API 호출 공통 함수 포함                                  |=====================
import asyncio
import copy
import json
# import logging
import os
import time
from base64 import b64decode
from collections import namedtuple
from collections.abc import Callable
from datetime import datetime, timedelta
# from io import StringIO
import pandas as pd
import requests
import websockets
import yaml
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
import httpx 

from ..common.setup import smartSleep_, demoSleep_
from ..common.optlog import optlog, ModuleLogger

### added ###
import threading
_subscription_lock = threading.Lock()
### ----- ###

clearConsole = lambda: os.system("cls" if os.name in ("nt", "dos") else "clear")
# logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
# logger = logging.getLogger(__name__)
# here 'logger' is introduced to replace 'print' in the original code to 'optlog'
logger = ModuleLogger(optlog, default_name="kis_auth")

key_bytes = 32
reauth_safety_seconds = 300

# ppd_ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) # ../..
ppppd_ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))) # ../../../..
config_root = os.path.join(ppppd_, 'config') 
yaml_path = os.path.join(config_root, 'kis_devlp.yaml') 
token_path = os.path.join(config_root, 'KIS_token') 

# 앱키, 앱시크리트, 토큰, 계좌번호 등 저장관리, 자신만의 경로와 파일명으로 설정하시기 바랍니다.
with open(yaml_path, encoding="UTF-8") as f:
    _cfg = yaml.load(f, Loader=yaml.FullLoader)

_TRENV = tuple()
_expire_time = dict()
_expire_time_ws = dict()
_autoReAuth = True   # USAGE: when token file name is static, check token status when _url_fetch called
_DEBUG = False
_isPaper = False
_smartSleep = smartSleep_ # 0.1 # min 0.05
_demoSleep = demoSleep_ # 0.5 # min 0.5

KISEnv = namedtuple(
    "KISEnv",
    ["my_app", "my_sec", "my_acct", "my_svr", "my_prod", "my_htsid", "my_token", "my_url", "my_url_ws", "env_dv", "sleep"],
)

# 기본 헤더값 정의
_min_headers = {
    "Content-Type": "application/json",
    "Accept": "text/plain",
    "charset": "UTF-8",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
}
_base_headers = copy.deepcopy(_min_headers)

_url_real = "https://openapi.koreainvestment.com:9443"
_url_real_ws = "ws://ops.koreainvestment.com:21000" # 웹소켓
_url_demo = "https://openapivts.koreainvestment.com:29443"
_url_demo_ws = "ws://ops.koreainvestment.com:31000" # 모의투자 웹소켓

# 토큰 발급 받아 저장 (토큰값, 토큰 유효시간,1일, 6시간 이내 발급신청시는 기존 토큰값과 동일, 발급시 알림톡 발송)
def save_token(my_token, valid_date, token_file):
    with open(token_file, "w", encoding="utf-8") as f:
        f.write(f"token: {my_token}\n")
        f.write(f"valid-date: {valid_date}\n")

# 토큰 확인 (토큰값, 토큰 유효시간_1일, 6시간 이내 발급신청시는 기존 토큰값과 동일, 발급시 알림톡 발송)
def read_token(token_file):
    try:
        # 토큰이 저장된 파일 읽기
        with open(token_file, encoding="UTF-8") as f:
            tkg_tmp = yaml.load(f, Loader=yaml.FullLoader)   # datetime obj catched

        # 토큰 만료 일,시간 
        # exp_dt = datetime.strftime(tkg_tmp["valid-date"], "%Y-%m-%d %H:%M:%S")
        # check_dt = (datetime.now()+timedelta(seconds=600)).strftime("%Y-%m-%d %H:%M:%S") 

        # 저장된 토큰 만료일자 체크 (만료일시 > 현재일시 인경우 보관 토큰 리턴)
        if tkg_tmp['valid-date'] > datetime.now() + timedelta(seconds=reauth_safety_seconds): # if at least xxx seconds left until exp
            return tkg_tmp["token"], tkg_tmp["valid-date"]
        else:
            # logger.warning(f"Need new token: {tkg_tmp['valid-date']}")
            return None, None
    except Exception as e:
        return None, None

# 토큰 유효시간 체크해서 만료된 토큰이면 재발급처리
def _getBaseHeader(svr):
    if _autoReAuth:
        reAuth(svr) 
    return copy.deepcopy(_base_headers)

# 가져오기 : 앱키, 앱시크리트, 종합계좌번호(계좌번호 중 숫자8자리), 계좌상품코드(계좌번호 중 숫자2자리), 토큰, 도메인
def _setTRENV(cfg):
    # nt1 = namedtuple(
    #     "KISEnv",
    #     ["my_app", "my_sec", "my_acct", "my_svr", "my_prod", "my_htsid", "my_token", "my_url", "my_url_ws", "env_dv", "sleep"],
    # )
    d = {
        "my_app": cfg["my_app"],  # 앱키
        "my_sec": cfg["my_sec"],  # 앱시크리트
        "my_acct": cfg["my_acct"],  # 종합계좌번호(8자리)
        "my_svr": cfg["my_svr"],
        "my_prod": cfg["my_prod"],  # 계좌상품코드(2자리)
        "my_htsid": cfg["my_htsid"],  # HTS ID
        "my_token": cfg["my_token"],  # 토큰
        "my_url": cfg["my_url"],  
        "my_url_ws": cfg["my_url_ws"],
        "env_dv": 'demo' if _isPaper else 'real',
        "sleep": _demoSleep if _isPaper else _smartSleep,
    }  
    global _TRENV
    # _TRENV = nt1(**d)
    _TRENV = KISEnv(**d)

def changeTREnv(token_key, svr):
    cfg = dict()
    global _isPaper
    if svr == 'prod':  # 실전투자 
        cfg["my_app"] = _cfg['main_app']
        cfg["my_sec"] = _cfg['main_sec']
        cfg['my_acct'] = _cfg['main_acct_stock']
        _isPaper = False
    elif svr == 'auto':  # 실전투자 (autotrading)
        cfg["my_app"] = _cfg['autotrading_app']
        cfg["my_sec"] = _cfg['autotrading_sec']
        cfg['my_acct'] = _cfg['auto_acct_stock']
        _isPaper = False
    elif svr == 'vps':  # 모의투자
        cfg["my_app"] = _cfg['paper_app']
        cfg["my_sec"] = _cfg['paper_sec']
        cfg['my_acct'] = _cfg['paper_acct_stock']
        _isPaper = True

    cfg["my_svr"] = svr
    cfg["my_prod"] = _cfg["my_prod"]
    cfg["my_htsid"] = _cfg["my_htsid"]
    cfg["my_url"] = _url_demo if _isPaper else _url_real
    cfg["my_url_ws"] = _url_demo_ws if _isPaper else _url_real_ws

    try:
        my_token = _TRENV.my_token
    except AttributeError:
        my_token = ""
    cfg["my_token"] = my_token if token_key else token_key

    _setTRENV(cfg)

def getTREnv():
    # if not initialized it is just empty
    return _TRENV

def smart_sleep():
    if _DEBUG:
        logger.info(f"[RateLimit] Sleeping {_smartSleep}s")
    try:
        if _isPaper:
            time.sleep(_demoSleep)
        else: 
            time.sleep(_smartSleep)
    except KeyboardInterrupt:
        logger.debug(f'smart_sleep stopped by KeyboardInterrupt')

def _getResultObject(json_data):
    _tc_ = namedtuple("res", json_data.keys())

    return _tc_(**json_data)

# Token 발급, 유효기간 1일, 6시간 이내 발급시 기존 token값 유지, 발급시 알림톡 무조건 발송
# 모의투자인 경우  svr='vps', 투자계좌(01)이 아닌경우 product='XX' 변경하세요 (계좌번호 뒤 2자리)
# 1분안에 두번 요청하면, 오류 
def auth(svr):
    # token_file = os.path.join(token_path, 'KIS_'+datetime.today().strftime("%Y%m%d")+'_'+svr)  # 토큰 파일명
    token_file = os.path.join(token_path, 'KIS_token_'+svr)  # 토큰 파일명

    # 기존 발급된 토큰이 있는지 확인
    saved_token, exp_dt_obj = read_token(token_file)  # 기존 발급 토큰 확인 및 유효시간 체크
    global _expire_time
    if saved_token is None:  # 기존 발급 토큰 확인이 안되면 발급처리
        changeTREnv(None, svr) # initialize _TRENV
        p = {
            "grant_type": "client_credentials",
            "appkey": _TRENV.my_app,
            "appsecret": _TRENV.my_sec, 
        }
        url = f"{_TRENV.my_url}/oauth2/tokenP"
        res = requests.post(
            url, data=json.dumps(p), headers=_min_headers
        )  # 토큰 발급
        rescode = res.status_code
        if rescode == 200:  # 토큰 정상 발급
            my_token = _getResultObject(res.json()).access_token  # 토큰값 가져오기
            my_expired = _getResultObject(
                res.json()
            ).access_token_token_expired  # 토큰값 만료일시 가져오기

            valid_date = datetime.strptime(my_expired, "%Y-%m-%d %H:%M:%S")
            save_token(my_token, valid_date, token_file)  # 새로 발급 받은 토큰 저장
            _expire_time[svr] = valid_date
            if _DEBUG:
                logger.info(f"[{_expire_time[svr]}] => get AUTH Key completed!")
        else:
            logger.error("Get Authentification token fail! - You may have to restart your app!!!")
            return
    else:
        my_token = saved_token  # 기존 발급 토큰 확인되어 기존 토큰 사용
        _expire_time[svr] = exp_dt_obj

    # 발급토큰 정보 포함해서 헤더값 저장 관리, API 호출시 필요
    changeTREnv(my_token, svr)

    _base_headers["authorization"] = f"Bearer {my_token}"
    _base_headers["appkey"] = _TRENV.my_app
    _base_headers["appsecret"] = _TRENV.my_sec

# end of initialize, 토큰 재발급, 토큰 발급시 유효시간 1일
# 프로그램 실행시 _expire_time 에 저장하여 유효시간 체크, 유효시간 만료시 토큰 발급 처리
def reAuth(svr):
    if datetime.now() + timedelta(seconds=reauth_safety_seconds) > _expire_time[svr]:
        auth(svr)

# 주문 API에서 사용할 hash key값을 받아 header에 설정해 주는 함수
# 현재는 hash key 필수 사항아님, 생략가능, API 호출과정에서 변조 우려를 하는 경우 사용
# Input: HTTP Header, HTTP post param
# Output: None
def set_order_hash_key(h, p):
    url = f"{getTREnv().my_url}/uapi/hashkey"  # hashkey 발급 API URL

    res = requests.post(url, data=json.dumps(p), headers=h)
    rescode = res.status_code
    if rescode == 200:
        h["hashkey"] = _getResultObject(res.json()).HASH
    else:
        logger.error(f"Error: {rescode}")

# API 호출 응답에 필요한 처리 공통 함수
class APIResp:
    def __init__(self, resp):
        self._rescode = resp.status_code
        self._resp = resp
        self._header = self._setHeader()
        self._body = self._setBody()
        self._err_code = self._body.msg_cd
        self._err_message = self._body.msg1

    def getResCode(self):
        return self._rescode

    def _setHeader(self):
        fld = dict()
        for x in self._resp.headers.keys():
            if x.islower():
                fld[x] = self._resp.headers.get(x)
        _th_ = namedtuple("header", fld.keys())

        return _th_(**fld)

    def _setBody(self):
        _tb_ = namedtuple("body", self._resp.json().keys())

        return _tb_(**self._resp.json())

    def getHeader(self):
        return self._header

    def getBody(self):
        return self._body

    def getResponse(self):
        return self._resp

    def isOK(self):
        try:
            if self.getBody().rt_cd == "0":
                return True
            else:
                return False
        except:
            return False

    def getErrorCode(self):
        return self._err_code

    def getErrorMessage(self):
        return self._err_message

    def printAll(self):
        logger.info("<Header>")
        for x in self.getHeader()._fields:
            logger.info(f"\t-{x}: {getattr(self.getHeader(), x)}")
        logger.info("<Body>")
        for x in self.getBody()._fields:
            logger.info(f"\t-{x}: {getattr(self.getBody(), x)}")

    def printError(self, url):
        logger.error( 
            f"\n-------------------------------\n" 
            f"Error in response: {self.getResCode()} url={url}\n" 
            f"rt_cd: {self.getBody().rt_cd} / msg_cd: {self.getErrorCode()} / msg1: {self.getErrorMessage()}" 
            "-------------------------------"
        )

    # end of class APIResp

class APIRespError(APIResp):
    def __init__(self, status_code, error_text):
        # 부모 생성자 호출하지 않고 직접 초기화
        self.status_code = status_code
        self.error_text = error_text
        self._error_code = str(status_code)
        self._error_message = error_text

    def isOK(self):
        return False

    def getErrorCode(self):
        return self._error_code

    def getErrorMessage(self):
        return self._error_message

    def getBody(self):
        # 빈 객체 리턴 (속성 접근 시 AttributeError 방지)
        class EmptyBody:
            def __getattr__(self, name):
                return None

        return EmptyBody()

    def getHeader(self):
        # 빈 객체 리턴
        class EmptyHeader:
            tr_cont = ""

            def __getattr__(self, name):
                return ""

        return EmptyHeader()

    def printAll(self):
        logger.error(
            f"\n=== ERROR RESPONSE ===\n"
            f"Status Code: {self.status_code}\n"
            f"Error Message: {self.error_text}\n"
            f"======================"
        )

    def printError(self, url=""):
        logger.error(f"[APIRespError] Error Code: {self.status_code} | {self.error_text}")
        if url:
            logger.error(f"URL: {url}")


########### API call wrapping : API 호출 공통
def _url_fetch(
        api_url, ptr_id, tr_cont, params, appendHeaders=None, postFlag=False, hashFlag=True
):
    url = f"{getTREnv().my_url}{api_url}"

    headers = _getBaseHeader(getTREnv().my_svr)  # 기본 header 값 정리

    # 추가 Header 설정
    tr_id = ptr_id
    if ptr_id[0] in ("T", "J", "C"):  # 실전투자용 TR id 체크
        if _isPaper:  
            tr_id = "V" + ptr_id[1:]

    headers["tr_id"] = tr_id  # 트랜젝션 TR id
    headers["custtype"] = "P"  # 일반(개인고객,법인고객) "P", 제휴사 "B"
    headers["tr_cont"] = tr_cont  # 트랜젝션 TR id

    if appendHeaders is not None:
        if len(appendHeaders) > 0:
            for x in appendHeaders.keys():
                headers[x] = appendHeaders.get(x)

    if _DEBUG:
        logger.debug(
            "< Sending Info >\n"
            f"URL: {url}, TR: {tr_id}\n"
            f"<header>\n{headers}\n"
            f"<body>\n{params}"
        )

    if postFlag:
        # if (hashFlag): set_order_hash_key(headers, params)
        res = requests.post(url, headers=headers, data=json.dumps(params))
    else:
        res = requests.get(url, headers=headers, params=params)

    if res.status_code == 200:
        ar = APIResp(res)
        if _DEBUG:
            ar.printAll()
        return ar
    else:
        logger.error(f"[_url_fetch] Error Code: {res.status_code} | {res.text}")
        return APIRespError(res.status_code, res.text)

####################################################################
# Async version 
####################################################################
async def _url_fetch_async(
    _http, api_url, ptr_id, tr_cont, params, appendHeaders=None, postFlag=False, hashFlag=True
):
    url = f"{getTREnv().my_url}{api_url}"

    headers = _getBaseHeader(getTREnv().my_svr)  # 기본 header 값 정리

    # 추가 Header 설정
    tr_id = ptr_id
    if ptr_id[0] in ("T", "J", "C"):  # 실전투자용 TR id 체크
        if _isPaper:  
            tr_id = "V" + ptr_id[1:]

    headers["tr_id"] = tr_id  # 트랜젝션 TR id
    headers["custtype"] = "P"  # 일반(개인고객,법인고객) "P", 제휴사 "B"
    headers["tr_cont"] = tr_cont  # 트랜젝션 TR id

    if appendHeaders is not None:
        if len(appendHeaders) > 0:
            for x in appendHeaders.keys():
                headers[x] = appendHeaders.get(x)

    if _DEBUG:
        logger.debug(
            "< Sending Info >\n"
            f"URL: {url}, TR: {tr_id}\n"
            f"<header>\n{headers}\n"
            f"<body>\n{params}"
        )
    
    try:
        if postFlag:
            resp = await _http.post(
                url,
                headers=headers,
                json=params,
            )
        else:
            resp = await _http.get(
                url,
                headers=headers,
                params=params,
            )

    except httpx.RequestError as e:
        logger.error(f"[_url_fetch_async] request failed: {e}")
        raise

    if resp.status_code == 200:
        ar = APIResp(resp)
        if _DEBUG:
            ar.printAll()
        return ar
    else:
        logger.error(f"[_url_fetch_async] Error Code: {resp.status_code} | {resp.text}")
        return APIRespError(resp.status_code, resp.text)


########### New - websocket 대응
_min_headers_ws = {
    "content-type": "utf-8",
}
_base_headers_ws = copy.deepcopy(_min_headers_ws)

def _getBaseHeader_ws(svr):
    if _autoReAuth:
        reAuth_ws(svr)

    return copy.deepcopy(_base_headers_ws)

# 접속키의 유효기간은 24시간이지만, 접속키는 세션 연결 시 초기 1회만 사용하기 때문에 접속키 인증 후에는 세션종료되지 않는 이상 접속키 신규 발급받지 않아도됨
def auth_ws(svr):
    changeTREnv(None, svr) # initialize _TRENV
    p = {
        "grant_type": "client_credentials",
        "appkey": _TRENV.my_app,
        "secretkey": _TRENV.my_sec, 
    }

    url = f"{_TRENV.my_url}/oauth2/Approval" 
    try:
        res = requests.post(url, data=json.dumps(p), headers=_min_headers_ws)  # 토큰 발급
    except Exception as e:
        logger.error(f"Check internet connection: {e}")
        return 
        
    rescode = res.status_code
    if rescode == 200:  # 토큰 정상 발급
        approval_key = _getResultObject(res.json()).approval_key
    else:
        logger.error("Get Approval token fail! - You may have to restart your app!!!")
        return

    _base_headers_ws["approval_key"] = approval_key

    global _expire_time_ws
    _expire_time_ws[svr] = datetime.now() + timedelta(hours = 24)

    if _DEBUG:
        logger.info(f"[{_expire_time_ws[svr]}] => get AUTH Key completed!")

def reAuth_ws(svr):
    if datetime.now() + timedelta(seconds=reauth_safety_seconds) > _expire_time_ws[svr]:
        auth_ws(svr)

def data_fetch(tr_id, tr_type, params, appendHeaders=None) -> dict:
    headers = _getBaseHeader_ws(getTREnv().my_svr) # 기본 header 값 정리

    headers["tr_type"] = tr_type
    headers["custtype"] = "P"

    if appendHeaders is not None:
        if len(appendHeaders) > 0:
            for x in appendHeaders.keys():
                headers[x] = appendHeaders.get(x)

    if _DEBUG:
        logger.debug(
            "< Sending Info >\n"
            f"TR: {tr_id}\n"
            f"<header>\n{headers}"
        )

    inp = {
        "tr_id": tr_id,
    }
    inp.update(params)

    return {"header": headers, "body": {"input": inp}}


# iv, ekey, encrypt 는 각 기능 메소드 파일에 저장할 수 있도록 dict에서 return 하도록
def system_resp(data):
    isPingPong = False
    isUnSub = False
    isOk = False
    tr_msg = None
    tr_key = None
    encrypt, iv, ekey = None, None, None

    rdic = json.loads(data)

    tr_id = rdic["header"]["tr_id"]
    if tr_id != "PINGPONG":
        tr_key = rdic["header"]["tr_key"]
        encrypt = rdic["header"]["encrypt"]
    if rdic.get("body", None) is not None:
        isOk = True if rdic["body"]["rt_cd"] == "0" else False
        tr_msg = rdic["body"]["msg1"]
        # 복호화를 위한 key 를 추출
        if "output" in rdic["body"]:
            iv = rdic["body"]["output"]["iv"]
            ekey = rdic["body"]["output"]["key"]
        isUnSub = True if tr_msg[:5] == "UNSUB" else False
    else:
        isPingPong = True if tr_id == "PINGPONG" else False

    nt2 = namedtuple(
        "SysMsg",
        [
            "isOk",
            "tr_id",
            "tr_key",
            "isUnSub",
            "isPingPong",
            "tr_msg",
            "iv",
            "ekey",
            "encrypt",
        ],
    )
    d = {
        "isOk": isOk,
        "tr_id": tr_id,
        "tr_key": tr_key,
        "tr_msg": tr_msg,
        "isUnSub": isUnSub,
        "isPingPong": isPingPong,
        "iv": iv,
        "ekey": ekey,
        "encrypt": encrypt,
    }

    return nt2(**d)


def aes_cbc_base64_dec(key, iv, cipher_text):
    if key is None or iv is None:
        logmsg = "key and iv cannot be None"
        logger.critical(logmsg)
        raise AttributeError(logmsg)

    cipher = AES.new(key.encode("utf-8"), AES.MODE_CBC, iv.encode("utf-8"))
    return bytes.decode(unpad(cipher.decrypt(b64decode(cipher_text)), AES.block_size))


# subscription management 
open_map: dict = {} # comprehensive dict for all subscribed

def add_open_map(
        name: str,
        request: Callable[[str, str, ], (dict, list[str])],
        data: str | list[str],
        kwargs: dict = None,
):
    # [revised version] -----------------------------------------------------
    with _subscription_lock:
        global open_map

        # normalize to list
        if isinstance(data, str):
            data = [data]

        # remove duplicates while keeping order    
        data = list(dict.fromkeys(data))

        # initialize to_add_map
        to_add_map = {}
    
        # initialize open_map entry if missing
        if name not in open_map:
            open_map[name] = {
                "func": request,
                "items": [],
                "kwargs": kwargs,
            }

        # find only new items (avoid duplicates)
        new_items = [x for x in data if x not in open_map[name]["items"]]
        subscribed_items = [x for x in data if x in open_map[name]["items"]]
        if new_items:
            to_add_map = {
                name: {
                    "func": request,
                    "items": new_items,
                    "kwargs": kwargs,
                }
            }
            open_map[name]["items"].extend(new_items)
    
        if subscribed_items:
            logger.warning(f"{name} already subscribed for {subscribed_items}")

        return to_add_map

    # [original version] -----------------------------------------------------
    # if open_map.get(name, None) is None:
    #     open_map[name] = {
    #         "func": request,
    #         "items": [],
    #         "kwargs": kwargs,
    #     }

    # if type(data) is list:
    #     open_map[name]["items"] += data
    # elif type(data) is str:
    #     open_map[name]["items"].append(data)

def remove_open_map(
        name: str,
        request: Callable[[str, str, ], (dict, list[str])],
        data: str | list[str],
        kwargs: dict = None,
):
    with _subscription_lock:
        global open_map

        # normalize to list
        if isinstance(data, str):
            data = [data]

        # remove duplicates while keeping order    
        data = list(dict.fromkeys(data))

        # initialize to_remove_map
        to_remove_map = {}

        if name not in open_map:
            # func (name) not subscribed
            logger.warning(f"{name} is not subscribed - nothing to remove")
            return

        # find only items that actually exist in open_map
        subscribed_items = open_map[name]["items"]
        remove_items = [x for x in data if x in subscribed_items]
        non_exist_items = [x for x in data if x not in subscribed_items]

        if remove_items:
            to_remove_map = {
                name: {
                    "func": request,
                    "items": remove_items,
                    "kwargs": kwargs,
                }
            }
            # update open_map (remove)
            open_map[name]["items"] = [x for x in subscribed_items if x not in remove_items]

            # if no more items, optionally remove the entry entirely
            if not open_map[name]["items"]:
                del open_map[name]

        if non_exist_items:
            logger.warning(f"{non_exist_items} not subscribed under {name} - unable to remove")
        
        return to_remove_map

# simply every increasing record of tr_id and corresponding info like columns
data_map: dict = {}

def add_data_map(
        tr_id: str,
        columns: list = None,
        encrypt: str = None,
        key: str = None,
        iv: str = None,
):
    if data_map.get(tr_id, None) is None:
        data_map[tr_id] = {"columns": [], "encrypt": False, "key": None, "iv": None}

    if columns is not None:
        data_map[tr_id]["columns"] = columns

    if encrypt is not None:
        data_map[tr_id]["encrypt"] = encrypt

    if key is not None:
        data_map[tr_id]["key"] = key

    if iv is not None:
        data_map[tr_id]["iv"] = iv


class KISWebSocket:
    api_url: str = ""
    on_result: Callable[
        [websockets.ClientConnection, str, pd.DataFrame, dict], None
    ] = None
    result_all_data: bool = False

    retry_count: int = 0

    # init
    def __init__(self, api_url: str, max_retries: int = 3):
        self.api_url = api_url
        self.max_retries = max_retries
        self.queue = asyncio.Queue()  # for dynamic subscription updates

    # private
    async def __subscriber(self, ws: websockets.ClientConnection):
        async for raw in ws:
            # logging.info("received message >> %s" % raw)
            show_result = False

            df = pd.DataFrame()

            if raw[0] in ["0", "1"]:
                d1 = raw.split("|")
                if len(d1) < 4:
                    logmsg = "data not found..."
                    logger.critical(logmsg)
                    raise ValueError(logmsg)

                tr_id = d1[1]

                dm = data_map[tr_id]

                d = d1[3]

                # [modification 1] ----------------------------------------------------- 
                # system_resp().encrypt 는 해당 메세지 자체의 Encrypt 여부인것으로 보임... 
                # if dm.get("encrypt", None) == "Y":             
                if raw[0] == "1": # 실시간 응답의 경우, 0: 암호화되지 않은 데이터, 1: 암호화된 데이터
                    d = aes_cbc_base64_dec(dm["key"], dm["iv"], d)

                # [modification 2] ----------------------------------------------------- 
                # read csv blow needs modification to read multiple lines to df
                # df = pd.read_csv(
                #     StringIO(d), header=None, sep="^", names=dm["columns"], dtype=object,
                #     on_bad_lines='error'   # default / does not raise for mismatched columns
                # )
                n_rows = int(d1[2]) # data의 개수 (예, DF의 행수)
                parts = d.split("^")  # split all fields
                n_cols = len(dm["columns"])

                # Safety check
                if len(parts) != n_rows * n_cols:
                    logmsg = f"Data length ({len(parts)}) does not match n_rows × n_cols ({n_rows * n_cols})"
                    logger.critical(logmsg)
                    raise ValueError(logmsg)

                rows = [parts[i * n_cols : (i + 1) * n_cols] for i in range(n_rows)]
                df = pd.DataFrame(rows, columns=dm["columns"], dtype=object)
                # [end of modification 2] -----
                
                show_result = True

            else:
                rsp = system_resp(raw)

                tr_id = rsp.tr_id
                add_data_map(
                    tr_id=rsp.tr_id, encrypt=rsp.encrypt, key=rsp.ekey, iv=rsp.iv
                )
                # raw_data = json.loads(raw)
                if rsp.isPingPong:
                    # logger.info(f"### RECV [PINGPONG] [{raw}]")
                    await ws.pong(raw)
                    # logger.info(f"### SEND [PINGPONG] [{raw}]")
                    # ------------
                    # logger.info(f"# pingpong ---- {raw_data['header']['datetime'][-6:]}")
                    # ------------
                if self.result_all_data:
                    show_result = True

            if show_result is True and self.on_result is not None:
                self.on_result(ws, tr_id, df, data_map[tr_id])

    # [newly added] -----------------------------------------------------
    async def __subscription_manager(self, ws):
        """Listen for updates from self.queue and apply them dynamically."""
        while True:
            action, to_do_map = await self.queue.get()  # signal to recheck subscription
            try:
                # adjust subscriptions
                if action == "subscribe":
                    # request subscribe
                    for name, obj in to_do_map.items():
                        await self.send_multiple(
                            ws, obj["func"], "1", obj["items"], obj["kwargs"]
                        )
                        logger.info(f'{name} for {obj["items"]} subscribed')
                elif action == "unsubscribe":
                    for name, obj in to_do_map.items():
                        await self.send_multiple(
                            ws, obj["func"], "2", obj["items"], obj["kwargs"]
                        )
                        logger.info(f'{name} for {obj["items"]} unsubscribed')

            except Exception as e:
                logger.error(f"{action} action failed for: {e}")
            self.queue.task_done()

    async def __runner(self):
        if len(open_map.keys()) > 40:
            logmsg = "Subscription's max is 40 - as defined in kis_auth.py"
            logger.critical(logmsg)
            raise ValueError(logmsg)

        url = f"{getTREnv().my_url_ws}{self.api_url}"

        while self.retry_count < self.max_retries:
            try:
                async with websockets.connect(url) as ws:
                    # [original version] -----------------------------------------------------
                    # # request subscribe
                    # for name, obj in open_map.items():
                    #     await self.send_multiple(
                    #         ws, obj["func"], "1", obj["items"], obj["kwargs"]
                    #     )

                    # # subscriber
                    # await asyncio.gather(
                    #     self.__subscriber(ws),
                    # )
                    
                    # [modified version - subscriptions handled dynamically] -----------------------------------------------------
                    await asyncio.gather(
                        self.__subscription_manager(ws), 
                        self.__subscriber(ws),
                    )
            except Exception as e:
                logger.error(f"Connection exception >> {e}")
                self.retry_count += 1
                await asyncio.sleep(1)

    @classmethod
    async def send(
            cls,
            ws: websockets.ClientConnection,
            request: Callable[[str, str, ], (dict, list[str])],
            tr_type: str,
            data: str,
            kwargs: dict = None,
    ):
        k = {} if kwargs is None else kwargs
        msg, columns = request(tr_type, data, **k)

        add_data_map(tr_id=msg["body"]["input"]["tr_id"], columns=columns)

        # logger.info(f"send message >> {json.dumps(msg)}")

        await ws.send(json.dumps(msg))
        smart_sleep()

    async def send_multiple(
            self,
            ws: websockets.ClientConnection,
            request: Callable[[str, str, ], (dict, list[str])],
            tr_type: str,
            data: list | str,
            kwargs: dict = None,
    ):
        if type(data) is str:
            await self.send(ws, request, tr_type, data, kwargs)
        elif type(data) is list:
            for d in data:
                await self.send(ws, request, tr_type, d, kwargs)
        else:
            logmsg = "data must be str or list"
            logger.critical(logmsg)
            raise ValueError(logmsg)

    # [modified version: subs and unsubs] -----------------------------------------------------
    def subscribe(
            self,
            request: Callable[[str, str, ], (dict, list[str])],
            data: list | str,
            kwargs: dict = None,
    ):
        to_add_map = add_open_map(request.__name__, request, data, kwargs)
        self.queue.put_nowait(("subscribe", to_add_map))

    def unsubscribe(
            self,
            request: Callable[[str, str, ], (dict, list[str])],
            data: list | str,
            kwargs: dict = None,
    ):
        to_remove_map = remove_open_map(request.__name__, request, data, kwargs)
        self.queue.put_nowait(("unsubscribe", to_remove_map))

    # [original version] -----------------------------------------------------
    # @classmethod
    # def subscribe(
    #         cls,
    #         request: Callable[[str, str, ...], (dict, list[str])],
    #         data: list | str,
    #         kwargs: dict = None,
    # ):
    #     add_open_map(request.__name__, request, data, kwargs)

    # def unsubscribe(
    #         self,
    #         ws: websockets.ClientConnection,
    #         request: Callable[[str, str, ...], (dict, list[str])],
    #         data: list | str,
    # ):
    #     self.send_multiple(ws, request, "2", data)

    # [original version - left uncommented out for compatibility] -----------------------------------------------------
    def start(
            self,
            on_result: Callable[
                [websockets.ClientConnection, str, pd.DataFrame, dict], None
            ],
            result_all_data: bool = False,
    ):
        self.on_result = on_result
        self.result_all_data = result_all_data
        try:
            asyncio.run(self.__runner())  # not used and asyncio.run moved to server.py
        except KeyboardInterrupt:
            # when cancelling, the logging could cause unnecessary noise
            # logger.error("Closing by cancel (e.g., by task-group cancel or keyboard)")
            pass

    # [modified version as async] -----------------------------------------------------
    async def start_async(
        self,
        on_result: Callable[
            [websockets.ClientConnection, str, pd.DataFrame, dict], None
        ],
        result_all_data: bool = False,
    ):
        self.on_result = on_result
        self.result_all_data = result_all_data
        try:
            await self.__runner()
        except asyncio.CancelledError:
            # when cancelling, the logging could cause unnecessary noise
            # logger.info("Closing by cancel (e.g., by task-group cancel or keyboard)")
            raise  # re-raise for proper TaskGroup shutdown
        except KeyboardInterrupt:
            # when cancelling, the logging could cause unnecessary noise
            # logger.info("Closing by cancel (e.g., by task-group cancel or keyboard)")
            raise 