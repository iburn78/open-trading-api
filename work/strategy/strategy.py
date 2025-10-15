from dataclasses import dataclass 
import pandas as pd

from common.optlog import optlog, log_raise
from common.tools import adj_int

from model.account import Account

# -----------------------------------------------------------------------------------
# Top level target setting and stregety definining
# -----------------------------------------------------------------------------------

# -----------------------------------------------------------------------------------
# Rule: 
# - Trade target should set once 
# - And, should not be chaning in one main.py running
# -----------------------------------------------------------------------------------

@dataclass
class TradeTarget:
    # target has to reflect the current account situation
    the_account: Account

    # safety margin on cash_t_2
    MAX_USAGE_CASH_T_2 = 0.9 

    # may read this from an Excel file (then format checker is required)
    target_df: pd.DataFrame = None
    _columns = [
        'code', 'max_exposure', 'cash_t_2', 'quantity', 'avg_price', 'bep_price'
    ]

    def __post_init__(self):
        self.target_df = pd.DataFrame(columns=self._columns)
        target_codes = self._temporary_target_code_gen()
        self._initialize_target_df(target_codes)
        self._sync_with_account()
        # ----------------------------------------------------
        # self._check_cash_t_2_total()  # need to de-comment this...
        # ----------------------------------------------------

    def _temporary_target_code_gen(self):
        some_codes = ['000660', '001440', '000240', '003230']
        return some_codes

    def _initialize_target_df(self, target_codes: list):
        for code in target_codes:
            new_row = {
                'code': code,
                'max_exposure': self._get_max_exposure(code),
                'cash_t_2': self._get_max_exposure(code),
                'quantity': 0, 
                'avg_price': 0, 
                'bep_price': 0, 
                'active': False, 
            } 
            self.target_df.loc[len(self.target_df)] = new_row

    def _get_max_exposure(self, code):
        # implementation needed for each code or some rule... 
        # e.g., MarCap, Volume, Volatility, etc
        max_exp = 30_000_000
        return max_exp

    def _sync_with_account(self):
        # create a lookup dict for holdings: code -> holding
        holdings_map = {h.code: h for h in self.the_account.holdings}

        # function to get values for each row
        def _get_values(code):
            h = holdings_map.get(code)
            if h:
                return h.quantity, h.avg_price, h.bep_price
            return 0, 0, 0

        # apply to all rows
        self.target_df[['quantity', 'avg_price', 'bep_price']] = self.target_df['code'].apply(
            lambda code: pd.Series(_get_values(code))
        )
        self.target_df['cash_t_2'] = adj_int(self.target_df['cash_t_2'] - self.target_df['quantity']*self.target_df['bep_price'])
    
    def _check_cash_t_2_total(self):
        max_exposure_exceeded = []
        mask = self.target_df['cash_t_2'] < 0
        max_exposure_exceeded = self.target_df.loc[mask, 'code'].tolist() 
        if max_exposure_exceeded:
            optlog.warning(f"Codes exceed the max exposure: {max_exposure_exceeded}") 
            # these holdings can only be sold...
            # May introduce some follow-up action

        cash_t_2_total_allocated = self.target_df.loc[~mask, 'cash_t_2'].sum() 
        if self.the_account.cash.t_2*self.MAX_USAGE_CASH_T_2 <= cash_t_2_total_allocated:
            # this case needs attention in allocating cash
            log_raise("Total allocated exposure exceeds the available cash ---")
        
    def get_target_codes(self):
        return self.target_df['code'].to_list()


# Below define strategies
# - Foreign follower
# - Value / Volatility tracker
# - Volume trigger strategy
