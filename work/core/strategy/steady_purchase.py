from .strategy import StrategyBase, StrategyCommand, UpdateEvent

class SteadyPurchase(StrategyBase):
    """
    Purchase strategy to reach target quantity steadily over time.
    """
    def __init__(self):
        super().__init__() 

        self.target_quantity: int = 0
        self.interval_sec: int = 60

    async def on_update_shell(self, on_event: UpdateEvent):
        while True:
            return
