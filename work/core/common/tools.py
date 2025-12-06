import pandas as pd
import numpy as np
import os

from .optlog import log_raise

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
_df_krx_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))), 'trader/data_collection/data/df_krx.feather')
df_krx = pd.read_feather(_df_krx_path)

def get_listed_market(code):
    if code not in df_krx.index: 
        log_raise(f'Code {code} not in df_krx ---')
    listed_market = df_krx.at[code, "Market"].strip()
    words = listed_market.replace("_", " ").split()
    return words[0].upper()

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