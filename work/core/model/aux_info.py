from ..base.settings import Service

class AuxInfo:
    """
    code_market_map: {
        code: market, # KOSPI, KOSDAQ, etc
        code: market,
        ...
    }
    """
    def __init__(self, service: Service):
        self.service = service

        # data add/remove handled in conn_agents
        # stores listed_market
        self.code_market_map: dict[str, dict] = {} 
        
        # to expand managed data ... 
