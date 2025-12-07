import pandas as pd
import numpy as np
import os, time
import FinanceDataReader as fdr

from .optlog import log_raise
from .setup import data_dir

# ----------------------------------------
# Float precision adjust
# ----------------------------------------
def excel_round_vector(x: int | list[int], ndigits=0):  # excel like rounding / works for scaler and vector / positive and negative
    x = np.asarray(x)
    eps = 1e-7
    eps_sign = np.where(x >=0, eps, -eps)
    return (np.round(x + eps_sign, ndigits)+eps_sign).astype(int)

def excel_round(x: float, ndigits=0):  # scaler
    eps = 1e-7 if x >= 0 else -1e-7
    return int(round(x + eps, ndigits))

# ----------------------------------------
# Get external data
# ----------------------------------------
df_krx_path = os.path.join(data_dir,"df_krx.feather")
df_krx_refresh_time = 12*60*60

def get_df_krx():
    if not os.path.exists(df_krx_path) or time.time() - os.path.getmtime(df_krx_path) > df_krx_refresh_time:
        return _gen_df_krx()
    return pd.read_feather(df_krx_path)

def _gen_df_krx():
    df_krx = fdr.StockListing('KRX')
    df_krx.drop(columns=['Dept', 'ChangeCode', 'Changes', 'ChagesRatio'], inplace=True)
    df_krx = df_krx[df_krx['MarketId'] != 'KNX']
    df_krx = df_krx.set_index('Code')
    df_krx.to_feather(df_krx_path)
    return df_krx

def get_listed_market(code):
    df_krx = get_df_krx()
    if code not in df_krx.index: 
        log_raise(f'Code {code} not in df_krx ---')
    listed_market = df_krx.at[code, "Market"].strip()
    words = listed_market.replace("_", " ").split()
    return words[0].upper()

def get_df_krx_price(code):
    df_krx = get_df_krx()
    return int(df_krx.loc[code, 'Close'])

# indexed_listing = {key: item, key: item}
# below not used anywhere... may delete
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

# dict merge
# if keys are identical while merge, add "#" to the key of A (until it becomes unique)
def merge_with_suffix_on_A(A: dict, B: dict) -> dict:
    # Start with an empty merged dict
    result = {}

    # 1) Insert A’s keys, renaming if needed to avoid conflicts with B
    for k, v in A.items():
        new_key = k
        # If this key exists in B, or already in result, rename A's key
        while new_key in B or new_key in result:
            new_key += "#"
        result[new_key] = v

    # 2) Insert B’s keys EXACTLY as they are
    for k, v in B.items():
        result[k] = v

    return result

def merge_with_suffix_on_B(A: dict, B: dict) -> dict:
    result = dict(A)  # preserve A order and values (shallow copy of A, and will be the initial starting point)

    for k, v in B.items():
        new_key = k
        while new_key in result:
            new_key = new_key + "#"   # append more '#' until unique
        result[new_key] = v          # preserves B’s order too

    return result