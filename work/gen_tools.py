import os
import logging
from logging.handlers import RotatingFileHandler
import pandas as pd
import numpy as np

HOST = "127.0.0.1"   # Localhost
PORT = 30001 # 1024–49151 → registered/user ports → safe for your server
# 49152–65535 → ephemeral → usually assigned automatically to clients

_df_krx_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'trader/data_collection/data/df_krx.feather')
df_krx = pd.read_feather(_df_krx_path)

def get_market(code):
    if code not in df_krx.index: 
        log_raise(f'Code {code} not in df_krx ---')
    market = df_krx.at[code, "Market"].strip()
    words = market.replace("_", " ").split()
    return words[0].upper()

optlog: logging.Logger = None
MAX_BYTES = 10_000_000 
BACKUP_COUNT = 5 # num of files
def get_logger(name: str, log_file: str, level=logging.INFO,
            max_bytes=MAX_BYTES, backup_count=BACKUP_COUNT) -> logging.Logger:
    """
    max_bytes: max size in bytes before rotation
    backup_count: number of backup files to keep
    """
    global optlog
    if optlog is not None:
        return optlog  # already initialized

    optlog = logging.getLogger(name) # name is necessary not to override root logger
    optlog.setLevel(level)
    optlog.propagate = False

    if not optlog.handlers:  # avoid duplicate handlers on re-import
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%m/%d %H:%M:%S"
        )

        fh = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
        fh.setFormatter(formatter)

        sh = logging.StreamHandler()
        sh.setFormatter(formatter)

        optlog.addHandler(fh)
        optlog.addHandler(sh)

def log_raise(msg, logger=None):
    logger = logger or optlog # arg default value looped up only once in reading func def. when dynamically initiallizing, need to catch dynamically.
    logger.error(msg)
    raise Exception(msg) 

# only works for int!
def excel_round_int(x, ndigits=0):  # excel like rounding / works for scaler and vector
    x = np.asarray(x)
    eps = 1e-10
    eps_sign = np.where(x >=0, eps, -eps)
    return (np.round(x + eps_sign, ndigits)+eps_sign).astype(int)

def adj_int(x):   # float issue removed / works for scaler and vector
    x = np.asarray(x)
    eps = 1e-10
    eps_sign = np.where(x >=0, eps, -eps)
    return (x+eps_sign).astype(int)