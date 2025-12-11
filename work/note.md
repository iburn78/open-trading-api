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
- run in the root dir (e.g., work/) as a module ```python -m scripts.xxx```
- for unbuffered terminal output: ```python -u -m scripts.xxx```

or more modern way (only for development situation)
- Define pyproject.toml in the project root (see example pyproject.toml file).
    - It declares your project metadata, dependencies, and packages to be installed.
    - In [tool.setuptools.packages.find], you can use include = ["*"] to automatically include all packages.
    - Packages (folders) should have __init__.py to be recognized as proper Python packages (required for relative imports).
- (venv) pip install -e . performs an editable install, making the packages importable immediately.
    - If metadata or dependencies in pyproject.toml change, you should rerun pip install -e . to update the environment.
    - Adding files / modifying files are ok, but when the package names are changed (directory name changes), rerun pip install -e .
    - After that, you can run scripts or modules without import errors — no need to manually adjust sys.path.
- all subpackages have to be declared, and need to be accessed from the respective parent packages
- now you can run py files independently in script folder
- HOWEVER, WHEN IN PRODUCTION, don't do pip install -e . stuff... as, it pollutes pip freeze

## Notes 
### Market knowledge
- Every orders that are not processed is cancelled over night
- 모의투자 has some limitations: e.g., price < 1000 does not go through.
- Revise is basically the same as cancel and then re-order

### Design notes
- Race conditions could occur when getting responses from API server: e.g., 1) direct response of the command, 2) websocket response 
- Cancelled order is only progressed up to order.processed quantity
- Each agent has a client instance (one to one)
- Agent registration is done by AgentCard
- A client can send a command but the corresponding agent has to be registered already
- let's use "###(underbar_)" to mark places that need attention / fix / develop
- Order submission: Strategy-Agent(Client)-OrderBook: single order communication, Client-Server: List[Order] communication, Server-API: single order communication

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
- in Linux: OpenBLAS optimization might be needed to use all threads
- in Linux: install Intel MKL NumPy to boost speed 
    - pip install numpy -U --extra-index-url https://pypi.anaconda.org/intel/simple


### Tips
- Update windows terminal from old CMD to windows terminal and use this: winget install --id Microsoft.WindowsTerminal -e 

## To develop

### [big topics]
- Risk management and position Limits etc... 
- Disaster recovery (disconnect from the API server - how to reconnect safely)
- Save state (to disk) 
- State reconciliation - e.g., periodic sync with account and OrderManager/Agent
- Monitoring and alert / overall dashboard on health and status
- Back-testing framework
- Configuration management - centralized control/constants/set-up panel
- Testing (how?)
- Documentation
- Performance profiling with cProfile(sync), yappi(async)

### [AgentManager related]
- make it run each agent only once: use local lock file method etc
- manage agents (easy to see like EXCEL)
- agent manager to use multi threads or multi cmd/terminal 
- sync with account
- agent better to handle only one code (initial qty, price / sync), but if initial value assigned correctly, code can be changed (as sync will check first code and then id)
- every day, agent clean-up is required, such as remaining incompleted order / pending trns has to be handled (STUDY HOW THE API TREATS THIS -- WHETHER IT SENDS SOME NOTICE ON CANCEL OR NOT)
- agent / sever (initial data cleanup logic might be needed - may want to do fresh start: make this easier / can change agent id, but this seems roundabout)

### [long term strategy related]
- review over-night behavior of server and agent: technically
    * order_manager records data daily (keeps for multiple days)
    * agent order_book keeps all orders
- make multi-day (longer terms) strategy/sync possible 
    * currently agent sync with daily data
    * may need to engage agent manager 
- may need to build server/agent scheduler/controller

### [immediate next]

#### snapshot
- viewing the snapshot of an agent (using rich or FastAPI etc for web) and more specific feedback on actions
- performance measure: agent order_book has to have parse function (to get the summary of orders)

#### server/reconnect
- when reconnect / check if really continuous / how it works now and how should it work
- when load/save pkl, may print status to log
- make it multi day re-connection
- need to make reset function of server status... etc 
- three level reconnection: 1) kis_auth level (already in place, need to study/understand), 2) websocket_loop() level, 3) server level (entire off and on / should make data continuity seamless)

- for example, following errors stop subsequent actions being correctly performed or suspend system
    ```
    1205_160813.367 [ERROR] sv> kis_auth> Connection exception >> no close frame received or sent 
    1205_160822.854 [ERROR] sv> kis_auth> Connection exception >> [WinError 121] 세마포 제한 시간이 만료되었습니다
    1207_141451.014 [ERROR] sv> A1> [Agent] agent A1 (port 54406) disconnected - dispatch msg failed: [WinError 10053] 현재 연결은 사용자의 호스트 시스템의 소프트웨어의 의해 중단되었습니다
    ```

### [Trading Strategy related]
- 유동주식수 and volume: use at the same time
- try make a back tester
- price/volume history: get / save / etc
- develop random price simulator (use custom ones - should exist)
- SEC vs SEC preferred: check arbitrage opp.


