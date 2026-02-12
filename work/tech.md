## python

### script running
- running as a module enables using package structure, and relative imports
- run in the root dir (e.g., work/) as a module ```python -m scripts.xxx```
- for unbuffered terminal output: ```python -u -m scripts.xxx```
- vscode import path even showed as working, it may not actually work when running (depending on how you run it)
- [alternative] during development: may use pip install -e (but in production, should not use, as this pollutes pip list)

### Python general
- variables are just references to objects, and everything is passed by reference (i.e., passing variables)
    - mutables (list, dict, set, custom classes) vs immutables (int, float, str, tuple, frozenset)
        - mutables are passed by reference
        - immutables are reassigned if values are changed (behaves like not passed by value)
        - only mutable objects can be changed through them. If an object passed as an argument is immutable (int, str, etc.), you cannot mutate it — only rebind the local name, which does not affect the caller.
    - r=5; f(r): what is passed is a reference to 5, not a reference to r. that is crux.

- caution: once an object is over the stream(reader/writer), no longer it is the same object

- is vs == (__eq__) 
    - is: identity check (same object in memory)
    - ==: executes __eq__, which is defined differently for objects
    - behavior of 'if i in a_list: ...' internally applies '=='

- use pickle internal only: efficient, tailored to python objects, but executable

- deque is for performance guarantees, not just defining maxlen. 
    - list is O(n) for left-side ops 
    - deque gives O(1) append, appendleft, pop, popleft (strong point)
    - however, when using slicing like [n:] then deque is O(n), should consider native list

- asyncio._lock: 
    - if a coroutine holds the lock for a long time, all others waiting for the same lock will be blocked.
    - always release (or return) the lock as soon as processing is done to avoid blocking others.
    - caution: calling a function using _lock inside a function that uses _lock results in a deadlock. (take it out)

- KeyboardInterrupt(KI) & asyncio CancelledError(CE) model
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
    - gather(..., return_exceptions=True) absorbs child cancellation by returning the CE as value / if False, all tasks are cancelled as normal (as gather itself is cancelled)
    - CancelledError should almost never be caught except at lifecycle / shutdown boundaries because CE can interrupt cleanup
    - TaskGroup + try/finally encode the correct ownership model: A structured lifetime boundary for async work / even a single task, there is no other alternatives
    - CancelledError (or any exception) inside a Task only escapes when the Task is awaited. so, A task that is fired-and-forgotten does not escape.

### TaskGroup
#### Role of TaskGroup
- Primary role: structured lifetime management of tasks.
- Ensures all tasks complete or all cancel together.
- Not a general-purpose run in parallel primitive.
- Forces ownership clarity and deterministic shutdown.

#### Key Rules / Patterns
1. **Do not put long-lived or infinite tasks directly into a TaskGroup.**
- Example: `listen_server()` → infinite loop **must be outside**.
- Reason: TG waits for all tasks to finish. Infinite tasks + dynamically spawned children = **shutdown hangs / deadlock**.

2. **A TG-owned task must not create(spawn) new concurrent tasks (long-lived).**
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
- In order to force stopping a TG, to cancel long-running tasks, raise CE is required/necessary (or any raise) rather than just return (which awaits long-running tasks to finish)

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

#### Core Rules to Remember
- Cancellation is exception-based and cooperative
    - asyncio signals cancellation by raising CancelledError (CE) at await points.
    - Tasks must reach an await or explicitly check for cancellation to respond.
- Manually raising CancelledError is immediate
    - If you raise CE inside a task, it propagates right away, bypassing normal await suspension.
- TaskGroup behavior
    - A TaskGroup does not shield CancelledError; cancellations still propagate.
    - Propagation is deferred until the TaskGroup exits, allowing remaining tasks to run to completion if possible.
    - Ownership and lifetime of tasks are defined by the TaskGroup.
- Cleanup considerations
    - Cleanup inside an async with TaskGroup() is not guaranteed unless you explicitly use try/finally.
    - finally blocks should be reserved for cleanup, not core logic.
- Awaiting and fire-and-forget tasks
    - CE only escapes when a task is awaited.
    - Tasks that are fire-and-forget will not propagate their CE outside.
    - Never swallow CancelledError; let it propagate to signal cancellation properly.
- Practical takeaway
    - Always handle cleanup with try/finally.
    - Treat TaskGroups as defining ownership and controlled lifetime of tasks.
    - Respect cooperative cancellation: CE is your signal to stop, not just an exception to catch.

### Ctrl-C Cancellation Fundamentals
1. What cancellation actually is
- Cancellation in asyncio is **exception-based**.
- The exception used is `asyncio.CancelledError` (CE).
- CE is **not an error**, but a **control-flow signal** for task lifecycle termination.
- Two distinct ways `CancelledError` appears
    - Injected cancellation (by asyncio)
        - Triggered by:
            - `task.cancel()`
            - `KeyboardInterrupt`
            - TaskGroup exit / failure
        - The task is **marked cancelled immediately**
        - **`CancelledError` is injected only when the coroutine resumes at the next `await`**
        - No `await` → no injection
        > Cancellation delivery is **cooperative**, not preemptive.
    - Manually raised `CancelledError`
        - `raise asyncio.CancelledError()`
        - Raised **immediately**, at that line
        - Behaves like a normal exception
        - Does **not** depend on `await`

2. Where Cancellation Is Delivered
- Cancellation is always delivered to:
    > **The coroutine frame that would resume next**
- Practically:
    - The **deepest suspended coroutine** inside the cancelled Task
    - Equivalent to raising `CancelledError` at that `await`

3. Task Boundaries & Exception Escape
- Tasks do not propagate exceptions automatically
    - `asyncio.create_task()` **does not** propagate exceptions
    - Exceptions (including CE) are **stored inside the Task**
- When does `CancelledError` escape?
    - **Only when the Task is awaited**
        ```python
        task = asyncio.create_task(worker())
        await task  # CE escapes here
        ```
- Fire-and-forget rule
    - A task that is fired-and-forgotten does not escape
    - If a task is never awaited: CE does not propagate, Other tasks are unaffected, The event loop continues

4. KeyboardInterrupt & asyncio.run()
- asyncio.run():
    1) Catches KeyboardInterrupt
    2) Cancels the main task
    3) Waits for cleanup
    4) Re-raises KeyboardInterrupt
- Cancellation order:
   - Main task cancelled first
   - Everything it awaits or owns via TaskGroup
   - During shutdown, remaining background tasks are cancelled

5. Cleanup Rules (Critical)
- CancelledError handling
    - CE should almost never be caught
    - Except at:
        - lifecycle boundaries
        - shutdown / ownership boundaries
    - Correct pattern:

        ```python
        try:
            ...
        except asyncio.CancelledError:
            cleanup()
            raise
        ```
- Why re-raise?
    - Swallowing CE breaks cancellation propagation
    - Can hang shutdown
    - Can leak resources
- Typical cleanup
    - Close sockets
    - Close DB sessions
    - Release locks
    - Close streams
    - Cancel subscriptions
    - Release external resources
- on finally (try-finally): 
    - finally is for closing, not logic
    - Executes on return, exception, or cancellation
    - finally does not guarantee logic completion
    - finally may be interrupted if it awaits


---
---

# Python & Asyncio Notes (Regen by AI)

---

## 1. Python Script Running

- **Running as a module** enables proper package structure and relative imports.  
  ```bash
  python -m scripts.xxx
  python -u -m scripts.xxx  # unbuffered output
  ```
- VSCode may show imports as working, but runtime execution depends on **current working directory**.  
- During development, you may use:
  ```bash
  pip install -e .
  ```
  *Do not use in production* (pollutes pip list).

---

## 2. Python General Concepts

### Variables & Object References

- Variables are **references to objects**; everything is passed by reference.  
- **Mutable vs Immutable**:
  - Mutable (list, dict, set, custom classes): passed by reference; can be mutated in-place.
  - Immutable (int, float, str, tuple, frozenset): cannot be mutated; reassignment only rebinds local reference.
- Example:
  ```python
  r = 5
  def f(x):
      x += 1  # does not affect r
  f(r)
  ```
  > The reference to the object `5` is passed, not the variable `r`.

### Identity vs Equality

- `is`: checks **identity** (same object in memory).  
- `==`: checks **equality**, using `__eq__`.  
- Example: `if i in a_list:` internally uses `==`.

### Deque vs List

- `deque` provides **O(1)** `append`, `appendleft`, `pop`, `popleft`.  
- List is **O(n)** for left-side operations.  
- Slicing a deque (`[n:]`) is O(n); consider native list if slicing frequently.  

### Locks

- Asyncio locks (`_lock`) block all coroutines waiting for the lock.  
- Always **release the lock promptly**.  
- Avoid **nested lock calls** inside functions using the same lock → can cause deadlocks.

### Pickle

- Use **only for internal Python object persistence**.  
- Executable and efficient, but not cross-language safe.

---

## 3. Asyncio: CancelledError & KeyboardInterrupt

### Cancellation Fundamentals

- **Cancellation is cooperative and exception-based**.  
- Exception used: `asyncio.CancelledError` (CE).  
- CE is **not an error**, but a **control-flow signal**.  

**Two ways CE appears:**

1. **Injected cancellation**  
   - Triggered by `task.cancel()`, `KeyboardInterrupt`, TaskGroup exit/failure.  
   - Task is **marked cancelled immediately**.  
   - CE is raised **only at the next `await` point**.  

2. **Manually raised CE**  
   - `raise asyncio.CancelledError()` → raised immediately, like a normal exception.  

**Delivery rules:**

- CE is delivered to the **frame that would resume next**, usually the deepest suspended coroutine.  
- Fire-and-forget tasks: CE does **not propagate** unless awaited.  
- Only **awaited tasks propagate CE**.

---

### Ctrl-C & `asyncio.run()`

- `asyncio.run()` behavior on Ctrl-C:
  1. Catches KeyboardInterrupt.
  2. Cancels the main task.
  3. Waits for cleanup.
  4. Re-raises KeyboardInterrupt.
- Cancellation order:
  - Main task and all awaited tasks / TaskGroups first.  
  - Background tasks cancelled during shutdown.

---

### Cleanup & Finally

- CE should almost **never be caught** except at lifecycle/shutdown boundaries:
  ```python
  try:
      ...
  except asyncio.CancelledError:
      cleanup()
      raise
  ```
- Always **re-raise CE** to avoid hanging shutdown.  
- Typical cleanup: close sockets, DB sessions, streams, locks, subscriptions.  
- `finally` is **for cleanup only**, not logic.  
- `finally` runs on return, exception, or cancellation; may be interrupted at `await` points.

---

## 4. `asyncio.gather`

- Default: `return_exceptions=False`  
  - Propagates first exception (or CE).  
  - Cancels other tasks if gather itself is cancelled.  

- `return_exceptions=True`  
  - Exceptions, including CE, are **returned as results**.  
  - CE does **not propagate** to parent; other tasks continue running.

---

## 5. TaskGroup

### Role

- Structured lifetime management for tasks.  
- Ensures **all tasks complete or cancel together**.  
- Not a general-purpose “run-in-parallel” primitive.  
- Forces **ownership clarity** and **deterministic shutdown**.

### Rules / Patterns

1. **Do not put infinite/long-lived tasks directly inside a TG.**
   - Example: `listen_server()` → infinite loops **must be outside**.  

2. **TG-owned tasks must not spawn new concurrent long-lived tasks.**
   - Safe: `await` calls.  
   - Unsafe: `asyncio.create_task()` inside TG task unless managed by TG.  

3. **Short-lived tasks are fine** inside TG.  
   - Example: per-message processing, quick I/O or computation.  

4. **Cancellation**  
   - TG cancels all its tasks upon exit or exception.  
   - CE injected cooperatively at `await` points.  
   - To stop a long-running TG task, **raise CE explicitly**, do not just return.  

5. **Nested TaskGroups**  
   - Recommended for scaling.  
   - Ownership must remain acyclic:
     ```
     Outer TG
     ├─ handler() → Inner TG → leaf tasks
     └─ handler() → Inner TG → leaf tasks
     ```
   - Ensures structured concurrency and deterministic shutdown.  

6. **Outside / detached tasks**  
   - TG does **not** manage tasks created outside.  
   - Must be tracked manually or safely fire-and-forget.

### Key Takeaways for TaskGroup

- Cancellation is cooperative; CE propagates at await points.  
- TG does **not shield CE**; it is deferred until exit.  
- Cleanup **must use try/finally**.  
- CE escapes only when **awaited**; fire-and-forget tasks do not propagate CE.  
- Treat TG as **ownership boundary** for task lifetime and cleanup.  

---

## 6. Practical Takeaways

- Always use **try/finally** for cleanup.  
- Never swallow `CancelledError`; always re-raise.  
- Respect **cooperative cancellation**: CE is a signal to stop.  
- Use `TaskGroup` for **structured concurrency**, not parallel execution.  
- Fire-and-forget tasks are isolated; only awaited tasks propagate exceptions.


