from .optlog import log_raise
import pandas as pd
import numpy as np
import os

# ----------------------------------------
# Float precision adjust
# ----------------------------------------
def excel_round_int(x: int | list[int], ndigits=0):  # excel like rounding / works for scaler and vector
    x = np.asarray(x)
    eps = 1e-10
    eps_sign = np.where(x >=0, eps, -eps)
    return (np.round(x + eps_sign, ndigits)+eps_sign).astype(int)

def adj_int(x):   # int() with float issue removed / works for scaler and vector
    x = np.asarray(x)
    eps = 1e-10
    eps_sign = np.where(x >=0, eps, -eps)
    return (x+eps_sign).astype(int)

# ----------------------------------------
# Get external data
# ----------------------------------------
_df_krx_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), 'trader/data_collection/data/df_krx.feather')
df_krx = pd.read_feather(_df_krx_path)

def get_market(code):
    if code not in df_krx.index: 
        log_raise(f'Code {code} not in df_krx ---')
    market = df_krx.at[code, "Market"].strip()
    words = market.replace("_", " ").split()
    return words[0].upper()

