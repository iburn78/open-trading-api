# Python & Asyncio Notes 

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
      x += 1  
  f(r) # does not affect r
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


### Ctrl-C & `asyncio.run()`

- `asyncio.run()` behavior on Ctrl-C:
  1. Catches KeyboardInterrupt.
  2. Cancels the main task.
  3. Waits for cleanup.
  4. Re-raises KeyboardInterrupt.
- Cancellation order:
  - Main task and all awaited tasks / TaskGroups first.  
  - Background tasks cancelled during shutdown.


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


## 4. `asyncio.gather`

- Default: `return_exceptions=False`  
  - Propagates first exception (or CE).  
  - Cancels other tasks if gather itself is cancelled.  

- `return_exceptions=True`  
  - Exceptions, including CE, are **returned as results**.  
  - CE does **not propagate** to parent; other tasks continue running.


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


## 6. Practical Takeaways

- Always use **try/finally** for cleanup.  
- Never swallow `CancelledError`; always re-raise.  
- Respect **cooperative cancellation**: CE is a signal to stop.  
- Use `TaskGroup` for **structured concurrency**, not parallel execution.  
- Fire-and-forget tasks are isolated; only awaited tasks propagate exceptions.


