from pathlib import Path
from enum import StrEnum

# ----------------------------------------------------
# project directory structure 
# ----------------------------------------------------
PROJECTS_DIR = Path(__file__).resolve().parents[4]
WORK_DIR = PROJECTS_DIR / 'optrading' / 'work'
LOG_DIR = WORK_DIR / 'log'
DATA_DIR = WORK_DIR / 'data'

config_file = PROJECTS_DIR / 'config' / 'kis_devlp.yaml'

# ----------------------------------------------------
# API control settings
# ----------------------------------------------------
real_sleep = 0.1 # min 0.05
demo_sleep = 0.5 # min 0.5
reauth_margin_sec = 300

# ----------------------------------------------------
# local communication settings
# ----------------------------------------------------
class Service(StrEnum):
    PROD = 'prod'
    AUTO = 'auto'
    DEMO = 'demo'

    def is_real(self): 
        return self is not Service.DEMO

HOST = "127.0.0.1"   # Localhost
SERVER_PORT = {
    Service.PROD: 30001,
    Service.AUTO: 30002,
    Service.DEMO: 30003,
}
# 1024–49151 → registered/user ports → safe for your server
# 49152–65535 → ephemeral → usually assigned automatically to clients

DASHBOARD_MANAGER_PORT = {
    Service.PROD: 9000,
    Service.AUTO: 9010,
    Service.DEMO: 9020,
}
DASHBOARD_SERVER_PORT = {
    Service.PROD: 9001,
    Service.AUTO: 9011,
    Service.DEMO: 9021,
}

# ----------------------------------------------------
# server status save settings
# ----------------------------------------------------
# server may run for each service
OM_save_filename = 'order_manager_' # + service type + date + .pkl
order_manager_keep_days = 7 # days
disk_save_period = 900 # sec
server_broadcast_interval = 30 # sec

# ----------------------------------------------------
# key parameters in trading logic settings
# ----------------------------------------------------
class TradeSettings: 
    # Limit order safety margin
    LIMIT_ORDER_SAFETY_MARGIN: float = 0.015
    # Market order safety margin
    MARKET_ORDER_SAFETY_MARGIN: float = 0.20
