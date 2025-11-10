import pandas as pd
import numpy as np
import os

from .optlog import log_raise

# ----------------------------------------
# Float precision adjust
# ----------------------------------------
def excel_round_int(x: int | list[int], ndigits=0):  # excel like rounding / works for scaler and vector / positive and negative
    x = np.asarray(x)
    eps = 1e-7
    eps_sign = np.where(x >=0, eps, -eps)
    return (np.round(x + eps_sign, ndigits)+eps_sign).astype(int)

def adj_int(x: float | list[float]):   # int() with float issue removed / works for scaler and vector / positive and negative
    x = np.asarray(x)
    eps = 1e-7
    eps_sign = np.where(x >=0, eps, -eps)
    return (x+eps_sign).astype(int)

# ----------------------------------------
# Get external data
# ----------------------------------------
_df_krx_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))), 'trader/data_collection/data/df_krx.feather')
df_krx = pd.read_feather(_df_krx_path)

def get_market(code):
    if code not in df_krx.index: 
        log_raise(f'Code {code} not in df_krx ---')
    market = df_krx.at[code, "Market"].strip()
    words = market.replace("_", " ").split()
    return words[0].upper()


# indexed_listing = {key: item, key: item}
def compare_indexed_listings(prev: dict, new: dict):
    # check if equal (using __eq__ in the item object)
    if prev == new:
        return True, ''

    # key comparison
    diff_msg = ''
    for key in set(prev.keys())-set(new.keys()):
        diff_msg += f'    {key} in the existing dict removed: \n'
        diff_msg += f'        ext: {prev.get(key)}\n'
    for key in set(prev.keys()) & set(new.keys()):
        if prev.get(key) != new.get(key):
            diff_msg += f'    {key} in the existing dict has updated: \n'
            diff_msg += f'        ext: {prev.get(key)}\n'
            diff_msg += f'        new: {new.get(key)}\n'
    for key in set(new.keys())-set(prev.keys()):
        diff_msg += f'    {key} newly added: \n'
        diff_msg += f'        new: {new.get(key)}\n'
    return False, diff_msg