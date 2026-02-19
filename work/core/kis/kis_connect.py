import asyncio
import json
import websockets
import yaml
import httpx 
import time
from base64 import b64decode
from collections import namedtuple
from datetime import datetime, timedelta
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from ..base.settings import Service, config_file, real_sleep, demo_sleep, reauth_margin_hr 

class KIS_Connector: 
    # default values
    _stock_products = '01'

    # default urls
    _url_real = "https://openapi.koreainvestment.com:9443"
    _url_real_ws = "ws://ops.koreainvestment.com:21000" # 웹소켓
    _url_demo = "https://openapivts.koreainvestment.com:29443"
    _url_demo_ws = "ws://ops.koreainvestment.com:31000" 
    _ws_api_url ="/tryitout" 

    # control settings
    _max_ws_tries = 5
    _resubs_event = asyncio.Event()

    def __init__(self, logger, service: Service, on_result=None, server_env:dict=None):
        self.logger = logger
        self.service = service
        self.on_result = on_result

        self.product_no = self._stock_products
        if self.service.is_real():
            self.url = self._url_real
            self.url_ws = self._url_real_ws + self._ws_api_url
            self.sleep = real_sleep
        else:
            self.url = self._url_demo
            self.url_ws = self._url_demo_ws + self._ws_api_url
            self.sleep = demo_sleep

        self.read_config_file()
        self.base_header = {
            "content-type": "application/json",
            "charset": "utf-8",
            "appkey": self.app_key, 
            "appsecret": self.sec_key, 
            "custtype": "P",
        }
        if server_env:
            self.token = server_env.get('token')
            self.token_exp = datetime.strptime(server_env.get('token_exp'),'%Y-%m-%d %H:%M:%S')
        else: 
            self.token = None
            self.token_exp = None

        self.httpx_client: httpx.AsyncClient = httpx.AsyncClient()
        self._last_call_time = None

        # Websocket part ----------------
        self.base_header_ws = { 
            "content-type": "utf-8", # not "charset"
            "custtype": "P",
        }

        # for websocket, do not save token in file
        self.token_ws = None
        self.token_ws_exp = None

        self.ws = None # websocket to be initialized in runner
        self.ws_ready = asyncio.Event()

        self._ws_try_count = 0
        self.tr_id_map = {}
        self._tr_id_map_lock = asyncio.Lock()

    def read_config_file(self): # shouldn't be called too frequently
        with open(config_file, encoding="UTF-8") as f:
            _cfg = yaml.load(f, Loader=yaml.FullLoader)

        self.htsid = _cfg['htsid']
        if self.service == Service.PROD:
            self.app_key = _cfg['main_app']
            self.sec_key = _cfg['main_sec']
            self.account_no = _cfg['main_acct_stock']
        elif self.service == Service.AUTO:
            self.app_key = _cfg['autotrading_app']
            self.sec_key = _cfg['autotrading_sec']
            self.account_no = _cfg['auto_acct_stock']
        elif self.service == Service.DEMO:
            self.app_key = _cfg['paper_app']
            self.sec_key = _cfg['paper_sec']
            self.account_no = _cfg['paper_acct_stock']

    async def set_token(self):
        if self.token:
            if self.token_exp > datetime.now() + timedelta(hours = reauth_margin_hr):
                return
        p = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.sec_key,
        }
        token_url = f"{self.url}/oauth2/tokenP"

        try:
            resp = await self.httpx_client.post(token_url, json=p)
        except httpx.RequestError as e:
            self.logger.error(f"[KIS_Connector] getting token failed: {e}", exc_info=True)
            raise
        
        if resp.status_code != 200:
            self.logger.error(f"[KIS_Connector] getting token failed, {self.service}: {resp.status_code} | {resp.text}")
            raise Exception("token error")

        r = resp.json()
        self.token = r['access_token'] 
        self.token_exp = datetime.strptime(r['access_token_token_expired'], "%Y-%m-%d %H:%M:%S")
        self.base_header["authorization"] = f"Bearer {self.token}"

    async def url_fetch(self, api_url, tr_id, tr_cont, params, post=False):
        '''
        if error, returns (None, None)
        proper error handling (e.g. checking None) should be implemented in the caller
        '''
        await self.set_token()

        # guarantees self.sleep time dealy between calls
        now = time.monotonic() # less overhead and ever increasing (error proof)
        if self._last_call_time is not None:
            delay = self._last_call_time + self.sleep - now
            if delay > 0:
                # self.logger.info(f'[KIS_Connector] delay: {delay}') 
                await asyncio.sleep(delay)
        self._last_call_time = time.monotonic()

        url = self.url + api_url
        h = {
            "tr_id": tr_id,
            "tr_cont": tr_cont,
        }
        try:
            if post:
                resp = await self.httpx_client.post(
                    url,
                    headers=self.base_header | h,
                    json=params,
                )
            else:
                resp = await self.httpx_client.get(
                    url,
                    headers=self.base_header | h,
                    params=params,
                )
        except httpx.RequestError as e: # network level / transport errors
            self.logger.error(f"[url_fetch] request failed: {e}") # exc_info=True, solution: safe reconnect is the solution
            return None, None

        # resp is an httpx.Response object
        if resp.status_code == 200:
            res = resp.json() # only returns body part of response as dict, if header info needed, use resp.headers: dict
            h = resp.headers
            if res['rt_cd'] == "0": # if success 
                return res, h

        self.logger.error(f"[url_fetch] error code: {resp.status_code} | {resp.text}")
        return None, None

    # -------------------------------------------------------------------
    # WebSocket part
    # -------------------------------------------------------------------
    async def set_token_ws(self):
        if self.token_ws: 
            if self.token_ws_exp > datetime.now() + timedelta(hours = reauth_margin_hr):
                return

        p = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "secretkey": self.sec_key,
        }
        token_ws_url = f"{self.url}/oauth2/Approval" 

        try:
            resp = await self.httpx_client.post(token_ws_url, json=p)
        except httpx.RequestError as e:
            self.logger.error(f"[KIS_Connector] getting token_ws failed: {e}", exc_info=True)
            raise

        if resp.status_code != 200:
            self.logger.error(f"[KIS_Connector] getting token_ws failed, {self.service}: {resp.status_code} | {resp.text}")
            raise Exception("token_ws error")

        r = resp.json()
        self.token_ws = r['approval_key'] 
        self.token_ws_exp = datetime.now() + timedelta(hours=24)
        self.base_header_ws["approval_key"] = self.token_ws

    async def ws_send(self, tr_type, tr_id, tr_key): 
        if self.ws is None: return # when socket is lost (e.g., closing up)

        await self.set_token_ws()
        # tr_type: "1" subscribe, "2" unsubscribe
        headers = self.base_header_ws | {"tr_type": tr_type}
        input = {
            "tr_id": tr_id,
            "tr_key": tr_key,
        } 
        # required structure for KIS ws
        msg = {"header": headers, "body": {"input": input}}
        # fire and forget
        await self.ws.send(json.dumps(msg))

    async def _subscriber(self):
        async for raw in self.ws:
            if raw[0] in ["0", "1"]:
                dr = raw.split("|")
                if len(dr) < 4:
                    self.logger.error("[KIS_Connector] data not found ...")
                    raise
                tr_id = dr[1]
                n_rows = int(dr[2]) # record의 수

                if raw[0] == "1": # 실시간 응답 0: 암호화되지 않은 데이터, 1: 암호화된 데이터
                    dm = self.tr_id_map[tr_id]
                    d = self.aes_cbc_base64_dec(dm["key"], dm["iv"], dr[3]).split("^")
                else: 
                    d = dr[3].split("^")
                # safety check: len(d) == n_rows * n_cols:

                if self.on_result:
                    self.on_result(tr_id, n_rows, d)

            else:
                rsp = self.system_resp(raw)
                if rsp.isPingPong:
                    await self.ws.pong(raw)
                    continue

                self.logger.info(self.sys_resp_to_str(rsp))
                if not rsp.tr_id.strip() or 'null' in rsp.tr_id.lower(): 
                    continue
                await self.register_tr_id(
                    tr_id=rsp.tr_id, key=rsp.ekey, iv=rsp.iv
                )
            
    def sys_resp_to_str(self, rsp):
        parts = []
        parts.append("SysMsg:OK" if rsp.isOk else "SysMsg:Not_OK")
        parts.append(f"tr_id:{rsp.tr_id}")
        parts.append(f"tr_key:{rsp.tr_key}")
        parts.append(rsp.tr_msg)
        return ', '.join(parts)

    def system_resp(self, data):
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

        nt = namedtuple(
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
        return nt(**d)

    def aes_cbc_base64_dec(self, key, iv, cipher_text):
        if key is None or iv is None:
            self.logger.error("[KIS_Connector] key and iv cannot be None")
            raise ValueError

        cipher = AES.new(key.encode("utf-8"), AES.MODE_CBC, iv.encode("utf-8"))
        return bytes.decode(unpad(cipher.decrypt(b64decode(cipher_text)), AES.block_size))

    async def register_tr_id(
            self, 
            tr_id: str,
            columns: list = None,
            encrypt: str = None,
            key: str = None,
            iv: str = None,
    ):
        async with self._tr_id_map_lock:
            entry = self.tr_id_map.setdefault(tr_id, {"key": None, "iv": None})

            updates = {
                "columns": columns,
                "encrypt": encrypt,
                "key": key,
                "iv": iv,
            }

            for k, v in updates.items():
                if v is not None:
                    entry[k] = v

    async def run_websocket(self):
        WEBSOCKET_RUN_DURATION_UNTIL_RESET = 300 # count reset after normal run of this duration
        while self._ws_try_count < self._max_ws_tries:
            try:
                async with websockets.connect(self.url_ws) as ws:
                    self.ws = ws
                    self.ws_ready.set() 

                    # session start timestamp 
                    started = asyncio.get_event_loop().time()

                    await self._subscriber()
                    # ---- normal exit (no exception) ----
                    session = asyncio.get_event_loop().time() - started
                    if session > WEBSOCKET_RUN_DURATION_UNTIL_RESET:
                        self._ws_try_count = 0
            except Exception as e: # asyncio.CancelledError is not caught here, so escape while
                self._ws_try_count += 1
                exp_delay = min(2 ** self._ws_try_count, 30)
                rec = "closed" if self._ws_try_count == self._max_ws_tries else f"reconnecting in {exp_delay} sec"
                self.logger.error(f"[KIS_Connector] ws error {self._ws_try_count}/{self._max_ws_tries}, {rec}: {e}") #, exc_info=True)
                await asyncio.sleep(exp_delay)

            finally:
                self.ws = None
                
    async def close_httpx(self):
        if self.httpx_client is not None:
            try:
                await self.httpx_client.aclose()
            except Exception:
                pass
            self.httpx_client = None