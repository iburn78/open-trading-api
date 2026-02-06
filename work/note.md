## Purpose
To develop a robust stock 'trader' using the KIS Open API

## Architecture
### core
independent modules 
- base: independent
- comm (communication): 
- kis: independent 
- model: import common, kis 
###_ reorganize this but not now, later after having 20 working strategies

### app
intermediate applications to be used in \base
- imports core

### scripts
- run in the root dir (e.g., work/) as a module ```python -m scripts.xxx```
- for unbuffered terminal output: ```python -u -m scripts.xxx```
- vscode import path even showed as working, it may not actually work when running (depending on how you run it)

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
- caution: once an object is over the stream(reader/writer), no longer it is the same object
- deque is for performance guarantees, not just maxlen. (deque gives O(1) append, appendleft, pop, popleft. list is O(n) for left-side ops. maxlen is just an optional policy layer)
- Python always passes object references; only mutable objects can be changed through them. If an object passed as an argument is immutable (int, str, etc.), you cannot mutate it — only rebind the local name, which does not affect the caller.
    - r=5; f(r) 
    - what is passed is a reference to 5, not a reference to r. that is crux.

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

### [medium topics]
- to speed-up: use string serialization instead of pickle.dumps and json.dumps (as they do type checking encoding/decoding can be costly)
- may relax await dispatch to tasks (however, need to check whether agent logic is solid)

### [AgentManager related]
- make it run each agent only once: use local lock file method etc
- manage agents (easy to see like EXCEL)
- agent manager to use multi threads or multi cmd/terminal 
- sync with account
- agent better to handle only one code (initial qty, price / sync), but if initial value assigned correctly, code can be changed (as sync will check first code and then id)
- every day, agent clean-up is required, such as remaining incompleted order / pending trns has to be handled (STUDY HOW THE API TREATS THIS -- WHETHER IT SENDS SOME NOTICE ON CANCEL OR NOT)
- agent / sever (initial data cleanup logic might be needed - may want to do fresh start: make this easier / can change agent id, but this seems roundabout)

    ###_ check for code (stock code) if vaild
    ###_ check if dp is unique 
    ###_ check if agent ids are unique

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
- make it multi day re-connection
- need to make reset function of server status... etc 

### [Trading Strategy related]
- 유동주식수 and volume: use at the same time
- try make a back tester
- price/volume history: get / save / etc
- develop random price simulator (use custom ones - should exist)
- SEC vs SEC preferred: check arbitrage opp.
- Foreign follower
- Value / Volatility tracker
- Volume trigger strategy
- PER base valuation 


### KeyboardInterrupt & asyncio cancellation model
- asyncio.run() catches KeyboardInterrupt, cancels the main task, and later re-raises KI after cleanup.
- Cancelling a task marks it cancelled immediately, but CancelledError is raised only when the coroutine next resumes at an await.
- The deepest suspended coroutine frame inside the cancelled task is the first to receive CancelledError.
- Cancellation is always delivered to the frame that would resume next (equivalent to raising CancelledError there).
- Cleanup handlers should catch CancelledError, perform cleanup, and re-raise it.
- Typical cleanup includes closing sockets, DB sessions, locks, streams, subscriptions, and releasing resources.
- On Ctrl-C:
    - the main task (and everything it awaits / TaskGroups) is cancelled first
    - during event-loop shutdown, any remaining background tasks are cancelled
- TaskGroup cancels all member tasks together and aggregates exceptions.
- task.cancel() schedules CE at the next await
- gather(..., return_exceptions=True) absorbs child cancellation
- CancelledError should almost never be caught
- except at lifecycle / shutdown boundaries
- because CE can interrupt cleanup
- TaskGroup + try/finally encode the correct ownership model: A structured lifetime boundary for async work / even a single task, there is no other alternatives
- CancelledError (or any exception) inside a Task only escapes when the Task is awaited. so, A task that is fired-and-forgotten does not escape.

## 1️⃣ Role of TaskGroup
- **Primary role:** structured lifetime management of tasks.
- Ensures **all tasks complete or all cancel together**.
- Not a general-purpose “run in parallel” primitive.
- Forces **ownership clarity** and deterministic shutdown.

## 2️⃣ Key Rules / Patterns

1. **Do not put long-lived or infinite tasks directly into a TaskGroup.**
   - Example: `listen_server()` → infinite loop **must be outside**.
   - Reason: TG waits for all tasks to finish. Infinite tasks + dynamically spawned children = **shutdown hangs / deadlock**.

2. **A TG-owned task must not create new concurrent tasks (long-lived).**
   - Safe: `await` calls.
   - Unsafe: `asyncio.create_task()` or TG-`create_task()` inside a TG-owned task.
   - Why: Cancellation races, dynamic task creation breaks structured concurrency.

3. **Short-lived tasks are fine inside TG.**
   - Example: per-message processing, small I/O, computation that finishes quickly.

4. **Cancellation behavior**
   - TG cancels all its tasks upon exit or if an exception occurs.
   - Cancellation is cooperative (only at `await` points).
   - TG waits for **all tasks it owns** to finish.
   - CE is injected into tasks — tasks may still spawn things briefly unless structured correctly.
   - In order to force stopping a TG, to cancel long-running tasks, raise CE is necessary (or any raise) rather than just return (which awaits long-running tasks to finish)

5. **Nested TaskGroups**
   - Allowed and **recommended** for scaling.
   - Ownership graph must remain **acyclic**:
    ```
     Outer TG → TG-owned task → Inner TG → leaf tasks
    ```
   - Ensures structured concurrency, deterministic shutdown.
    ```
        Outer TG
        ├── handler()
        │   └── Inner TG
        │       ├── process()
        │       ├── process()
        │       └── process()
        └── handler()
            └── Inner TG
                ├── process()
                ├── process()
                └── process()
    ```
6. **Outside / detached tasks**
   - Tasks created outside TG are **not managed**.
   - Must be explicitly tracked or safely fire-and-forget.
   - TG does **not** act as an umbrella for outside tasks.


---

## 1. Cancellation Fundamentals

### 1.1 What cancellation actually is
- Cancellation in asyncio is **exception-based**.
- The exception used is `asyncio.CancelledError` (CE).
- CE is **not an error**, but a **control-flow signal** for task lifecycle termination.

---

### 1.2 Two distinct ways `CancelledError` appears

#### ① Injected cancellation (by asyncio)
- Triggered by:
  - `task.cancel()`
  - `KeyboardInterrupt`
  - TaskGroup exit / failure
- The task is **marked cancelled immediately**
- **`CancelledError` is injected only when the coroutine resumes at the next `await`**
- No `await` → no injection

> Cancellation delivery is **cooperative**, not preemptive.

#### ② Manually raised `CancelledError`
- `raise asyncio.CancelledError()`
- Raised **immediately**, at that line
- Behaves like a normal exception
- Does **not** depend on `await`

These two mechanisms share the same exception type but have **different delivery semantics**.

---

## 2. Where Cancellation Is Delivered

- Cancellation is always delivered to:
  > **The coroutine frame that would resume next**
- Practically:
  - The **deepest suspended coroutine** inside the cancelled Task
  - Equivalent to raising `CancelledError` at that `await`

---

## 3. Task Boundaries & Exception Escape

### 3.1 Tasks do not propagate exceptions automatically
- `asyncio.create_task()` **does not** propagate exceptions
- Exceptions (including CE) are **stored inside the Task**

### 3.2 When does `CancelledError` escape?
- **Only when the Task is awaited**

```python
task = asyncio.create_task(worker())
await task  # CE escapes here
```

### 3.3 Fire-and-forget rule
- A task that is fired-and-forgotten does not escape
- If a task is never awaited: CE does not propagate, Other tasks are unaffected, The event loop continues

---

## 4. KeyboardInterrupt & asyncio.run()
- asyncio.run():
  1) Catches KeyboardInterrupt
  2) Cancels the main task
  3) Waits for cleanup
  4) Re-raises KeyboardInterrupt

- Cancellation order:
  - Main task cancelled first
  - Everything it awaits or owns via TaskGroup
  - During shutdown, remaining background tasks are cancelled

---

5. Cleanup Rules (Critical)
5.1 CancelledError handling

CE should almost never be caught

Except at:

lifecycle boundaries

shutdown / ownership boundaries

Correct pattern:

try:
    ...
except asyncio.CancelledError:
    cleanup()
    raise
### 5.2 Why re-raise?
- Swallowing CE breaks cancellation propagation
- Can hang shutdown
- Can leak resources

### 5.3 Typical cleanup
- Close sockets
- Close DB sessions
- Release locks
- Close streams
- Cancel subscriptions
- Release external resources

---

## 6. finally Semantics
- finally is for closing, not logic
- Executes on return, exception, or cancellation
- finally does not guarantee logic completion
- finally may be interrupted if it awaits

---

## 7. TaskGroup: Structured Concurrency

### 7.1 Role of TaskGroup
- Structured lifetime management
- Enforces ownership and deterministic shutdown
- All tasks finish or all cancel together
- Not a general-purpose parallelism tool

### 7.2 Core TaskGroup Rules

1) No infinite tasks inside a TaskGroup
- TaskGroup waits for all tasks
- Infinite tasks cause shutdown deadlock

2) TG-owned tasks must not spawn long-lived tasks
- Await is safe
- asyncio.create_task() inside TG-owned task is unsafe

3) Short-lived tasks are ideal
- Per-message handlers
- Small I/O or computation

### 7.3 Cancellation behavior
- Any exception cancels all TG tasks
- TG waits for all owned tasks
- Cancellation is cooperative
- Returning is not enough to stop long-running tasks
- Raising an exception is required

### 7.4 Nested TaskGroups
- Allowed and recommended
- Ownership graph must be acyclic
- Enables scalable structured concurrency

### 7.5 Outside / detached tasks
- Not managed by TaskGroup
- Must be explicitly tracked or safely fire-and-forget

---

## 8. Important Clarifications
- TaskGroup does not shield CancelledError
- It defers propagation until exit
- Cleanup after async with is not guaranteed
- try/finally is still mandatory

---

## 9. Core Rules to Remember
1) Cancellation is exception-based and cooperative
2) Asyncio injects CE only at await points
3) Manually raised CE is immediate
4) CE escapes only when a Task is awaited
5) Fire-and-forget tasks do not escape
6) Never swallow CE
7) TaskGroup defines ownership and lifetime
8) finally is for cleanup, not logic
