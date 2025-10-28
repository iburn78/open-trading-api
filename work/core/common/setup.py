from dataclasses import dataclass

# ----------------------------------------
# ENV setup
# ----------------------------------------
HOST = "127.0.0.1"   # Localhost
PORT = 30001 # 1024–49151 → registered/user ports → safe for your server
# 49152–65535 → ephemeral → usually assigned automatically to clients

@dataclass
class TradePrinciples:
    """
    Principles for trading to be defined
    - all agents have access to this data, and strtegies too via agents
    """
    # safety margin on cash_t2
    MAX_USAGE_CASH_T2: float = 0.9 

    # trade target return 
    TARGET_RETURN: float = 0.1

    # min return to alert
    MIN_RETURN: float = -0.2

    # per agent
    CAP_ON_CASH_AMOUNT = 10**8