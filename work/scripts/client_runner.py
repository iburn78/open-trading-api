from core.common.optlog import set_logger
set_logger()

import asyncio
import sys

from core.common.optlog import optlog
from core.model.agent import Agent
from core.strategy.brute_rand import BruteForceRandStrategy
from core.strategy.double_up import DoubleUpStrategy
from core.strategy.null_str import NullStr

# from rich.live import Live
# from rich.table import Table

# async def monitor_agent_live(agent, interval=1):
#     with Live(refresh_per_second=4) as live:
#         while not agent.hardstop_event.is_set():
#             table = Table(title=f"Agent {agent.id} Status")
#             table.add_column("Var", justify="right")
#             table.add_column("Value", justify="left")

#             table.add_row("holding", f"{agent.order_book.orderbook_holding_qty:,.0f}")
#             table.add_row("Holdings", str(agent.pm.initial_allocated_cash))

#             live.update(table)
#             await asyncio.sleep(interval)

async def main(sw=None): # switch
    if sw == "1":
        # A = Agent(id = 'A1', code = '000660', strategy=NullStr())
        A = Agent(id = 'A2', code = '000660', strategy=DoubleUpStrategy())
        A.initial_value_setup(init_cash_allocated=100000000, init_holding_qty=20, init_avg_price=500000)
        # A.initial_value_setup(init_cash_allocated=100000000)
        task1 = asyncio.create_task(A.run())  

        # B = Agent(id = 'B1', code = '001440', strategy=NullStr())
        # B.initial_value_setup(init_cash_allocated=10000000)
        # task2 = asyncio.create_task(B.run())  

        # task_monitor = asyncio.create_task(monitor_agent_live(A))

        await asyncio.sleep(1000)

        A.hardstop_event.set()
        # B.hardstop_event.set()

        # await asyncio.gather(task1, task2)
        # await asyncio.gather(task1, task2, task_monitor)

    elif sw == "2":
        C = Agent(id = 'F1', code = '099440', strategy=DoubleUpStrategy())
        C.initial_value_setup(init_cash_allocated=100000000)
        task3 = asyncio.create_task(C.run())  

        await asyncio.sleep(1000)

        C.hardstop_event.set()
        await asyncio.gather(task3)
    
    elif sw == "3": 
        pass


if __name__ == "__main__":
    try:
        asyncio.run(main(sys.argv[1]))
    except KeyboardInterrupt:
        optlog.info("[ClientRunner] Clients stopped by user (Ctrl+C).\n")
    