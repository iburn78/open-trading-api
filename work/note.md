## Purpose
To develop a robust stock 'trader' using the KIS Open API for Korean public stocks


## Architecture
### core
independent modules 

- common: independent 
- kis: independent 
- model: import common, kis 

### app
intermediate applications to be used in scripts/
- imports core

### scripts
entry point to run
- imports core and app
- run in the root dir (e.g., work/) as a module ```python -m scripts.xxx```
- for unbuffered terminal output: ```python -u -m scripts.xxx```

## Notes 
### Market knowledge
- Every orders that are not processed is cancelled over night
- 모의투자 has some limitations: e.g., price < 1000 does not go through.
- Revise is basically the same as cancel and then re-order

### Design notes
- Race conditions could occur when getting responses from API server: e.g., 1) direct response of the command, 2) websocket response 
- Cancelled order is only progressed up to order.processed quantity
- Each agent is a client (one to one)
- Agent registration is done by AgentCard
- A client can send command but the corresponding agent has to be registered already
- let's use "###(underbar_)" to mark places that need attention / fix / develop
- Order submission: Strategy-Agent/Client-OrderBook: single order communication, Client-Server: List[Order] communication, Server-API: single order communication

### Python knowledge
- variables are just references to objects, and everything is passed by reference (i.e., passing variables)
    - mutables (list, dict, set, custom classes) vs immutables (int, float, str, tuple, frozenset)
    - mutables are passed by reference
    - immutables are reassigned if values are changed (behaves like not passed by value)
- is vs == (__eq__) 
    - is: identity check (same object in memory)
    - ==: executes __eq__, which is defined differently for objects
    - behavior of 'if i in a_list: ...' internally applies '=='
- asyncio._lock: 
    - if a coroutine holds the lock for a long time, all others waiting for the same lock will be blocked.
    - always release (or return) the lock as soon as processing is done to avoid blocking others.
    - caution: calling a function using _lock inside a function that uses _lock results in a deadlock. (take it out)
- asyncio.event:
    - once set(), it could lost subsequent events until clear()
    - use queue accordingly
- use pickle internal only: efficient, tailored to python objects, but executable
- use in cmd: set PYTHONASYNCIODEBUG=1 (async performance measure)

## To develop
### [incremental]
- make it run each agent only once: use local lock file method etc
- manage agents using AgentManager (easy to see like EXCEL)

### [big topics]
- Risk management and position Limits etc... 
- Disaster recovery (disconnect from the KIS API server - how to reconnect safely)
- Save state (to disk) 
- State reconciliation - sync with account (periodically)
- Monitoring and alert / overall dashboard on health and status
- Back-testing framework
- Configuration management - centralized control/constants/set-up panel
- Testing (how?)
- Documentation
- Performance profiling with cProfile(sync), yappi(async)