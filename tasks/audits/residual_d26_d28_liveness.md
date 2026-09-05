# D26 and D28 — the two liveness candidates

Execution record for the Priority 2 candidates ranked by
[`review_gate_and_residual_work_plan.md`](../specs/review_gate_and_residual_work_plan.md).

**Baseline:** `aaa20c10` (B3). 3890 passing.

Both claims are true. **Both recorded locations were wrong**, and in D26's case
the error hid which of the two files held the serious defect.

---

## Summary

| | Defect | Verdict |
|---|---|---|
| **D26** | `_ws_lock` held across a timeout-less send loop | ✅ **one hung client deadlocks the whole behaviour-WebSocket subsystem** |
| **D26′** | `ConnectionManager`'s send loop is sequential and unbounded | ✅ head-of-line blocking; no deadlock |
| **D28** | `input()` inside `async def` | ✅ three sites, none in the recorded location |
| **D51** | `_tracker_tasks` never drained | 🔎 **new** — found while fixing D26, recorded not fixed |

---

## D26 — the lock and the send loop

The record read `weebot/interfaces/web/websocket.py:68-72, behavior_router.py:205-228`
and named `_ws_lock`. `[VF]` **`_ws_lock` does not exist in `websocket.py`.** It
is a module global in `routers/behavior_router.py`, and the two files fail
differently:

### behavior_router — a deadlock that closes on itself

```python
async with _ws_lock:            # held for the whole function
    ...
    for ws in _ws_connections:
        await ws.send_json(message)   # ← inside the lock, unbounded
```

A WebSocket send blocks until the peer's receive window opens. A client that
stops reading — suspended laptop, wedged tab, half-open TCP connection — makes
that `await` never return, and the lock is never released.

The same lock guards **registration** (`behavior_websocket`, line 271) and
**removal** (its `finally`, line 339). So:

- no further event can be broadcast,
- no new client can connect,
- **and no client can disconnect** — leaving requires the lock the hang holds.

`[VF]` That last one is what makes the state permanent rather than merely slow:
the one action that would remove the offending connection is the one action the
offending connection blocks. Nothing in the process can clear it short of a
restart.

### websocket.py — starvation, not deadlock

`ConnectionManager` already snapshots under the lock and sends outside it, so it
cannot deadlock. But its loop is sequential and has no timeout, so one hung
peer starves every subscriber positioned after it in the list. `[VF]` Proven by
wall clock: a healthy socket registered alongside a hung one received nothing.

**The recorded location had the severities the wrong way round** — it pointed at
the file that could only starve, and attributed to it the lock that belongs to
the file that could deadlock.

### The fix

One helper, `fan_out`, in `websocket.py`, used by all three broadcast paths:
snapshot under the lock, deliver **concurrently**, bound **every** send, return
the failures for the caller to evict.

```python
results = await asyncio.gather(*(_deliver(c) for c in conns))
return {c for c in results if c is not None}
```

`timeout` is a required keyword rather than a default, so each caller states the
bound its own clients are held to and there is no shared default to drift.
`CancelledError` is not an `Exception`, so an outer cancellation still
propagates instead of being mistaken for a client failure.

---

## D28 — `input()` inside `async def`

The record said `weebot/application/flows/states/`. `[VF]` **There is no
`input()` anywhere under that directory**, and the audit that recorded D28 never
named a site. The three real ones:

| Site | Live? |
|---|---|
| `weebot/core/approval.py:354` — `console_approval_callback` | **No.** Nothing calls `set_approval_callback` with it; the whole module is referenced only by `examples/phase11/02_bash_safety.py`. Latent. |
| `cli/commands/flow.py:92` | Yes — `python -m cli.main flow run` |
| `cli/commands/dream.py:184` | Yes — `dream build` |

`input()` blocks the calling thread until return, and a coroutine runs on the
loop's thread, so nothing else in the process runs while the prompt is on
screen. A CLI prompt is *meant* to wait for a person; only that one task should.

All three now use `await asyncio.to_thread(input, ...)`.

### The proof is a gate, not three tests

The sites were found by grep, and grep runs on nobody's behalf. The proof is an
AST walk over every `async def` in `weebot/` and `cli/`, failing on any bare
`input()` — **zero tolerance, no ceiling**, because the correct count is zero and
the fix is one line. It independently reproduced the same three sites.

Alongside it, one behavioural test drives the real
`console_approval_callback` against an `input` that consumes real wall-clock time
and counts how many times a concurrent task got a turn: **0–1 ticks before, ≥3
after**, against a free-running rate of ~40.

---

## Fixes

| # | File | Change |
|---|---|---|
| 1 | `weebot/interfaces/web/websocket.py` | New `fan_out()`; both `ConnectionManager` broadcasts use it |
| 2 | `weebot/interfaces/web/routers/behavior_router.py` | `broadcast_event` snapshots under `_ws_lock`, sends outside it via `fan_out` |
| 3 | `weebot/core/approval.py` | `await asyncio.to_thread(input, ...)` |
| 4 | `cli/commands/flow.py`, `cli/commands/dream.py` | same |

**Red before green:** D26 **9 failed / 4 passed** → **13 passed**; D28
**2 failed / 5 passed** → **7 passed**. The tests that passed before the fix are
the regression guards — delivery to every client, eviction of broken ones, the
empty-registry no-op, and the two non-interactive deny paths — and they still do.

---

## Phase 6 — six-vector self-review

| Vector | Finding |
|---|---|
| **Boundary** | `[VF]` Empty registry, single hung client with no healthy peer, hung client ordered *before* a healthy one (the only ordering a sequential loop fails on), and a client that never releases at all. |
| **Invalid input** | `[VF]` A socket raising on every send is still evicted, and no longer suppresses delivery to its peers — which the old sequential loop did not guarantee either way. |
| **State** | `[VF]` `behavior_router`'s registry is module-global; the fixture monkeypatches both `_ws_connections` and `_ws_lock` so tests cannot leak into each other. A fresh `asyncio.Lock` per test also avoids binding a lock to a dead event loop. |
| **Regression** | `[VF]` Full suite 3890 → **3910** passed / 0 failed. `lint-imports` 7 kept / 0 broken; ruff with CI's selector clean; all five ratchets unchanged at 139/29/143/73/68. |
| **Concurrency** | `[VF]` The whole candidate is concurrency. Every liveness assertion is bounded by `asyncio.timeout`, so a regression **fails** the test rather than hanging the suite — the failure mode being fixed is precisely one that would otherwise hang CI until its job timeout. |
| **New defects** | `[HYP]` `fan_out` cancels a timed-out send mid-flight. Against a real Starlette `WebSocket` that may abandon a partially written frame, leaving the socket in a state the peer cannot parse. The connection is evicted immediately and the peer was already not reading, so nothing depends on it — but it is **not closed**, and no test drives a real socket through this path. |

---

## Phase 8 — coverage & residual risk

### Not covered

- **The 5.0s timeout is a judgement, not a measurement.** Nothing here
  establishes what a real slow-but-live client needs on a congested link. Too
  low drops healthy peers; too high still lets one client hold a broadcast for
  five seconds. Tests override it, so no test would notice a bad value.
- **`fan_out` is unbounded in width.** One task per connection per broadcast.
  Correct at dashboard scale, a thundering herd at thousands. The design that
  removes the concern entirely — a bounded queue and a writer task per
  connection — was rejected as disproportionate to a module with no prior test
  coverage at all, not because it is wrong.
- **The evicted socket is never closed.** `fan_out` reports it, callers drop it
  from the registry, and nobody calls `close()`. The fd is released when the
  handler's own `finally` runs, which it now can.
- **`ConnectionManager` leaves the empty session key** behind after evicting the
  last connection; only `disconnect()` prunes those. One dict entry per dead
  session. Deliberately out of scope — D26 is liveness.
- **`KeyboardInterrupt` during `to_thread(input)`.** `[HYP]` SIGINT is delivered
  to the main thread, so the coroutine's `except KeyboardInterrupt` should still
  fire, but the worker thread stays blocked on stdin until the process exits.
  Not tested — driving a real terminal interrupt is out of reach here.
- **No test drives a real WebSocket.** Everything uses fakes. What is proven is
  the manager's and router's own logic, not Starlette's behaviour under
  cancellation.

### Residual risks

- **R-1 — the AST gate sees one level.** It attributes a call to its *nearest*
  enclosing function. A synchronous helper that calls `input()` and is invoked
  from a coroutine blocks the loop just as hard and is not caught. Finding that
  needs a call graph. Stated in the test's own docstring so the next reader
  learns it there rather than from a miss.
- **R-2 — the D28 behavioural test measures wall clock.** A 0.4 s block against
  a ≥3-tick floor at a free-running ~40 gives better than 10× margin, but it is
  a timing test and a sufficiently overloaded runner could still starve it.
- **R-3 — D26's tests use a 0.2 s send timeout.** A healthy fake send is an
  in-memory append, so spurious timeouts need pathological scheduling — but the
  margin is smaller than R-2's.
- **R-4 — `routers/__init__.py` shadows its own submodules.**
  `from .behavior_router import router as behavior_router` rebinds the name, so
  `from weebot.interfaces.web.routers import behavior_router` yields the
  `APIRouter`, not the module. The test reaches the module through
  `importlib.import_module`. Nothing is broken, but any future patching of that
  module's globals hits the same trap, silently.

### New candidate — D51

`start_session_tracking` schedules each broadcast with
`loop.create_task(...)` and appends it to `_tracker_tasks`, a list that is
**never awaited, pruned or cancelled**. It grows once per filesystem event for
the life of the session, and nothing observes a broadcast that raises. Adjacent
to D26 and found while fixing it; recorded in the inventory as `open` rather
than fixed, because it is a lifetime defect rather than a liveness one and
widening this change to chase it is the trade B3 already declined once.

### Verdict

**COMPLETE.** Both Priority 2 candidates are fixed and proven, and both
inventory records now name the right files — D26's had the two failure modes
attributed to the wrong halves, D28's pointed at a directory containing no
`input()` at all. 20 tests, 9+2 red before green. Inventory: **23 not closed**,
down from 24, with one new candidate recorded rather than lost.
