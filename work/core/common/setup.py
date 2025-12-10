import os

# ----------------------------------------------------
# env setup
# ----------------------------------------------------
HOST = "127.0.0.1"   # Localhost
PORT = 30001 # 1024–49151 → registered/user ports → safe for your server
# 49152–65535 → ephemeral → usually assigned automatically to clients
dashboard_manager_port = 9000 
dashboard_server_port = 9001
Server_Broadcast_Interval = 30 # sec

smartSleep_ = 0.1 # min 0.05
demoSleep_ = 0.5 # min 0.5

# ----------------------------------------------------
# save setup
# ----------------------------------------------------
work_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
data_dir = os.path.join(work_dir, 'data')
# log_dir defined in optlog.py

order_manager_keep_days = 7 # days
disk_save_period = 900 # sec

# ----------------------------------------------------
# key parameters in trading logic setup
# ----------------------------------------------------
class TradePrinciples: 
    """
    Principles for trading to be defined
    - all agents have access to this data, and strtegies too via agents

    - THIS TRADER assumes NO CREDIT BUY 
    - ONLY LONG STRATEGY

    """
    # safety margin on cash_t2
    MAX_USAGE_CASH_T2: float = 0.9 

    # trade target return 
    TARGET_RETURN: float = 0.1

    # min return to alert
    MIN_RETURN: float = -0.2

    # per agent
    CAP_ON_CASH_AMOUNT: int = 10**8

    # Limit order safety margin
    LIMIT_ORDER_SAFETY_MARGIN: float = 0.015
    
    # Market order safety margin
    MARKET_ORDER_SAFETY_MARGIN: float = 0.20
