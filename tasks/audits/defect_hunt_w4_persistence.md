# Wave 4 — Persistence & Data Integrity

Execution record for W4 of [`tasks/specs/defect_hunt_v7_execution_plan.md`](../specs/defect_hunt_v7_execution_plan.md).
Threat **T5** (state corruption); classes **C5**, **C7**, **C4**, **C9**.

---

## Phase 0-WAVE

| | |
|---|---|
| **Baseline** | `3d4ce0a`, working tree clean, all 8 CI checks green. |
| **Budget** | ≤20 generated · ≤12 investigated · ≤8 fixed |
| **Actually spent** | 10 generated · 6 investigated · 4 fixed |

---

## Phase 3/4 — triaged inventory

| ID | Claim | Trigger (3a) | Verdict |
|---|---|---|---|
| **D31** | `close()` never evicts from `_pool_registry`; the next `get_or_create_pool()` returns the closed pool | **FIRED** — same object returned, `_closed=True`, `execute_read` raised `RuntimeError: Connection pool is closed` | ✅ **VERIFIED DEFECT** |
| **D30** | The configured `timeout` never reaches sqlite | **FIRED** — pool configured 30.0 s, `PRAGMA busy_timeout` reported **5000 ms** | ✅ **VERIFIED DEFECT** |
| **D33** | The FTS5 watermark advances past events that failed to index | **FIRED** — watermark set to `len(session.events)` unconditionally | ✅ **VERIFIED DEFECT** |
| **D35** | `PERSISTENCE_RETRY_CONFIG` retries permanent errors | **FIRED** — `retryable=None`, which `backoff.py:56` treats as retry-everything | ✅ **VERIFIED DEFECT** |
| **D36** | `close()` drains only the idle queue; a checked-out read connection leaks its worker thread | not triggered | 🔵 **SUSPECTED — deferred** |
| **D32** | `save_session` spans three separate write transactions | not triggered | 🔵 **SUSPECTED — deferred** |

### D31 — the one that turns a normal lifecycle into a hard failure

`SQLiteStateRepository.close()` and `EventStore.close()` both call `pool.close()` directly and
drop their reference. `pool.close()` sets `_closed = True` but leaves the object in the
module-level `_pool_registry`. `get_or_create_pool()` tested only `if path_key not in
_pool_registry`, so it returned the dead pool — and every operation on it raised.

**A correction to an earlier reading of mine.** I first stated that both repositories share
`sessions.db`, making one repo's `close()` brick the other. That is **wrong**: the defaults are
`./weebot_sessions.db` and `~/.weebot/events.db`. Same-path cross-contamination requires them to
be configured onto one file, which DI permits but does not do by default. The defect does not
need that scenario — a single repository closing and reopening is enough.

### D30 — a configured value that governed the wrong thing

`SQLiteConnectionPool(timeout=30.0)` documents *"Maximum seconds to wait for a connection"*, and
the value was used **only** for the read-queue `asyncio.wait_for`. `aiosqlite.connect()` was
called with no `timeout=`, so sqlite applied its own 5-second default and no `PRAGMA
busy_timeout` was ever issued. A writer blocked past 5 s raised `database is locked` however
generously the pool was configured. Measured, not inferred: **5000 ms against a 30 s setting.**

### D33 — a failure that is logged and then stepped over

```python
try:
    await index_event(...)
except Exception:
    logger.warning("Failed to index event for FTS5", exc_info=True)   # swallowed
self._fts5_indexed[session.id] = len(session.events)                  # runs anyway
```

The watermark is the *only* record of what reached the index. Advancing it past a failed event
means that event is never retried: its content is permanently unsearchable while the repository
believes it is indexed. The surrounding code shows the author already reasoning about
"permanently unindexed" content in the event-list-shrank branch (`:297-301`) — the failure branch
was missed.

---

## Phase 5 — fixes

| # | File | Change | Lines |
|---|---|---|---|
| 1 | `connection_pool.py` | `get_or_create_pool` replaces a registry entry whose pool is closed | +9 |
| 2 | `connection_pool.py` | Pass `timeout=self.timeout` to both `aiosqlite.connect` calls | +5 |
| 3 | `sqlite_state_repo.py` | Count what was indexed; `break` on the first failure; advance the watermark by exactly that | +10 |
| 4 | `session_persistence_adapter.py` | `retryable=_is_transient`, a **denylist** of permanent errors | +22 |

**D31 was fixed at the point of use, not by evicting in `close()`.** The invariant that matters is
*never hand a caller a dead pool*, and enforcing it in `get_or_create_pool` covers a pool closed by
any route, not just the one path. The stale entry is replaced on the next request and
`close_all_pools()` still clears the registry — see residual risk R-1.

**D33 advances the watermark to the first failure rather than not at all.** Refusing to advance
would re-index the already-successful events on the next save and duplicate their FTS5 rows;
stopping at the failure retries exactly the event that failed.

**D35 is deliberately a denylist.** An unrecognised exception keeps the old retrying behaviour, so
the change cannot make the adapter *less* resilient than it was. Pydantic's `ValidationError`
subclasses `ValueError` and is therefore covered — asserted explicitly.

### Architecture invariants (plan §6)

1 `lint-imports` 7/7 KEPT · 2 no new `ignore_imports` · 3 domain untouched · 6 no port signature
changed · 7 no Pydantic widening · 8 no new subprocess site · 10 fixes and proof tests in one
commit. All ✅.

---

## Phase 6 — six-vector self-review

| Vector | Finding |
|---|---|
| **Boundary** | `[VF]` `timeout=5.0` still yields `busy_timeout=5000` — indistinguishable from the old default, which is why the parametrised test also covers 30.0. Watermark with zero events indexed stays at `last_indexed`. |
| **Invalid input** | `[VF]` `get_or_create_pool` on a path never seen behaves unchanged. `retryable` handles any `Exception` subclass. |
| **State** | `[VF]` The registry can briefly hold a closed pool between `close()` and the next request — bounded by the number of distinct paths, and replaced on use. |
| **Regression** | `[VF]` A live pool is still shared per path; distinct paths still get distinct pools; a clean indexing run still reaches the end and does not re-index. All asserted. |
| **Concurrency** | `[VF]` The registry replacement happens inside `_get_pool_lock()`, the same lock creation already used. `_fts5_locks[session.id]` still serialises watermark updates per session. |
| **New defects** | `[HYP]` `break` on the first index failure means a single poison event blocks indexing of every later event in that session until it succeeds. That is the correct trade against silent permanent loss, but it converts a per-event failure into a per-session stall. Not verified against a real poison-event case. |

---

## Phase 7 — tests

`tests/unit/infrastructure/persistence/test_w4_pool_and_index_integrity.py`, **13 tests, new
file**, all against real sqlite files rather than mocks: proof-of-defect for all four, plus
no-regression (pool sharing, distinct paths, clean indexing run) and boundary cases.

**Red before, green after, verified by reverting:** the three production files stashed →
**9 failed / 4 passed**; restored → **13 passed**.

---

## Phase 8 — coverage & residual-risk statement

### NOT covered — stated plainly

- **S4 was not addressed.** The plan's executably-verified seed — **37 sites across 10 modules**
  using `with sqlite3.connect(...) as conn:`, where the context manager commits but does **not**
  close, leaking a connection and file descriptor per call — is untouched. It is the largest
  single finding in this wave's scope. It was skipped because a 37-site sweep across 10 modules
  does not fit a ≤15-line-per-fix budget, not because it is disputed.
- **D32** (`save_session` spans three separate write transactions, so a crash between them leaves
  partial state), **D34** (a truncation rule implemented twice, only one copy resetting the FTS
  watermark), **D36** (a checked-out read connection is never closed by `close()`), **D37**
  (playwright adapter leaks browser and driver on an error path) and **D38** (`subprocess.Popen`
  assigned to a local, never waited or terminated) were **generated and not investigated**.
- **The plan's named "known gap to close" was not closed.** `implementation_audit_report.md` §6
  records no tests for `backup.py`, `restore.py` or `_database_backup_job`, and the plan calls
  that the highest-value place in the repo to add proof tests. **No backup or restore test was
  written.** Of the five declared regions, *backup round-trip integrity* was never entered, and
  neither was *migration/code column-name agreement* — a class the plan notes has bitten this repo
  before.

### Residual risks

- **R-1 — a closed pool lingers in the registry until its path is next requested.** Bounded by the
  number of distinct database paths, and replaced on use, so it is retention rather than growth.
  Evicting inside `close()` would be tidier but couples the instance to module state.
- **R-2 — `break`-on-first-failure can stall a session's indexing.** A permanently unindexable
  event blocks every later event in that session. Preferable to silent permanent loss, but it
  trades one failure mode for another, and nothing surfaces a session stuck this way.
- **R-3 — the retry denylist is a judgement call.** `sqlite3.OperationalError` covers both
  `database is locked` (transient) and `no such table` (permanent); the former is by far the more
  common and the denylist keeps both retryable. `[HYP]`, not measured.
- **R-4 — `busy_timeout` is now 30 s by default.** A writer that would previously have failed fast
  with `database is locked` will now block for up to 30 s. That is the configured intent, but it
  converts a fast error into a slow one under contention.

### Verdict

**PARTIAL.** Four verified defects fixed and proven against real databases. The wave's own
headline seed (S4, 37 verified leaks) was not addressed, five candidates were generated but never
investigated, and the plan's explicitly named test gap — backup/restore, a subsystem whose last
three defects were CRITICAL — remains open.
