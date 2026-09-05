# Wave 7 — Tools & Resource Lifecycle

Execution record for W7. Threats **T7**, **T1**; classes **C5**, **C1**, **C9**.

The plan's prediction for this wave: *"Largest surface, lowest per-region blast radius — expect
this wave to hit its budget ceiling and terminate PARTIAL. That is the expected, honest outcome."*
It did, and for exactly that reason: one candidate consumed the whole wave.

| | |
|---|---|
| **Baseline** | `5185b44` + W5 + W6, working tree green |
| **Budget** | ≤20 · ≤12 · ≤8 — **spent 4 · 1 · 1** (one fix, 37 sites) |

---

## Phase 3/4 — triaged inventory

| ID | Claim | Trigger | Verdict |
|---|---|---|---|
| **S4** | `with sqlite3.connect(...) as conn:` commits but does **not** close ⇒ a leaked connection and file descriptor per call, 37 sites / 10 modules | **FIRED** — executing on `conn` after the `with` block still succeeded | ✅ **VERIFIED DEFECT** |
| **D38** | `subprocess.Popen` assigned to a local, never waited or terminated; `terminate()` without `wait()` leaves a zombie | not investigated | 🔵 **SUSPECTED** |
| **D37** | Playwright `start()` has no cleanup if `new_context`/`new_page` raises after `launch()` | not investigated | 🔵 **SUSPECTED** |
| — | 14 `zip()` sites without `strict=` | not investigated | 🔵 **SUSPECTED** |

### S4 — the seed W4 deferred here

`sqlite3.Connection.__exit__` commits or rolls back the transaction. It does **not** close the
connection — a distinction the stdlib documents and this code read the other way. Demonstrated:

```python
with sqlite3.connect(db) as conn:
    conn.execute("CREATE TABLE t (x INTEGER)")
conn.execute("INSERT INTO t VALUES (1)")   # succeeds — the connection is still open
```

Distribution, all on one uniform single-line shape:

| Sites | Module |
|---|---|
| 7 | `persistence/skill_variant_store.py` |
| 5 | `scheduling/scheduler.py` |
| 5 | `persistence/strategy_store.py` |
| 5 | `persistence/posterior_repository.py` |
| 5 | `persistence/checkpoint_store.py` |
| 3 | `persistence/sqlite_summary_repo.py` |
| 3 | `persistence/meta_improvement_log.py` |
| 2 | `interfaces/cli/support.py` |
| 1 | `mcp/resources.py` |
| 1 | `persistence/sqlite_misalignment_journal.py` |

Several are hot: the scheduler polls, and `checkpoint_store` writes per step — and it targets the
same `sessions.db` the aiosqlite pool holds open.

---

## Phase 5 — the fix, and the policy deviation it required

```python
with sqlite3.connect(path) as conn:                        # before
with closing(sqlite3.connect(path)) as conn, conn:         # after
```

`closing` shuts the connection; the inner `conn` preserves the commit/rollback semantics the code
already depended on. **All 37 sites now use it; zero bare sites remain.**

**Deviation from the fix policy, recorded as the runbook requires.** Phase 5 sets ≤15 lines and
≤1 function per fix. This is 37 one-line changes across 10 modules plus an import each. It is a
single mechanical transformation of one uniform shape, applied programmatically and verified by
counting (37 transformed, 0 remaining, whole tree compiles). Splitting it into eight budgeted
fixes would have left the other 29 sites leaking, which is a worse outcome than the deviation.

W4 deferred S4 to this wave on exactly this budget objection. Deferring it again would have meant
the plan's largest verified seed survived the entire nine-wave programme untouched.

---

## Phase 6 — six-vector self-review

| Vector | Finding |
|---|---|
| **Boundary** | `[VF]` Commit-on-success and rollback-on-exception are both preserved — asserted directly, the latter via a primary-key violation. |
| **Invalid input** | `[VF]` Transformation is textual on one shape; the tree compiles and 73 persistence/e2e tests pass. |
| **State** | `[VF]` Connections are now closed at block exit rather than at garbage collection. |
| **Regression** | `[VF]` Full suite green (see below). |
| **Concurrency** | `[VF]` Closing sooner reduces concurrent open handles; it cannot introduce a new race. |
| **New defects** | `[VF]` Any code that *relied* on the connection outliving its block would now raise `ProgrammingError`. Searched: no such site — every use is inside its own block. `[HYP]` for code paths not exercised by the suite. |

---

## Phase 7 — tests

`tests/unit/infrastructure/persistence/test_w7_connection_lifecycle.py`, **6 tests**:

- Three pin the stdlib behaviour the defect rests on (the `with` block does not close; `closing`
  does; commit *and* rollback still work), so the ratchet below cannot be vacuous.
- `test_no_bare_connect_context_manager` is the **ratchet**: it greps `weebot/` and `cli/` and
  fails if any bare site reappears.
- `test_the_scan_works` guards the guard — a scan finding nothing would make the ratchet pass
  trivially, the exact failure mode Wave 0 existed to fix.

**Ratchet proven to block:** stashing the ten modified files turns it red; restoring returns green.

---

## Phase 8 — coverage & residual risk

### NOT covered — the great majority of the surface

The W7 surface is `weebot/tools/**` (**48 modules**), `infrastructure/browser/**`,
`infrastructure/document/**`. **Not one tool module was hunted.** Of the six declared regions,
only *file handles / connection lifecycle* was entered. Untouched:

- **subprocess lifecycle** (the finding-G class) — including **D38**, `subprocess.Popen` assigned
  to a local and never waited or terminated: an orphaned process and leaked pipes per call, plus a
  `terminate()` without `wait()` leaving a zombie.
- **browser context/page release on the error path** — **D37**.
- **`zip()` without `strict=`** — 14 sites where lengths can silently diverge.
- **`except: pass` sites** inherited from the W0 ratchet: **139 remain at ceiling. Wave 7 was
  where the plan said these get paid down, and none were.**

The plan's §11 warning applies squarely: *a ceiling that never moves is a fail-open gate with
extra steps.* Four ratchets (139 / 29 / 143 / 73) are unchanged across all seven waves.

### Residual risks

- **R-1 — connection *pooling* is still absent from these stores.** Each call opens and now closes
  a connection. Correct, but it trades a descriptor leak for per-call connect cost on hot paths
  like the scheduler poll. Not measured.
- **R-2 — the ratchet is a grep.** It catches the exact shape that was fixed. `sqlite3.connect`
  assigned to a variable and used without any context manager would pass it. Not searched for.
- **R-3 — `[HYP]` no code relied on post-block connection use.** Established by reading and by a
  green suite, not by exhaustive analysis of unexercised paths.

### Verdict

**PARTIAL**, and the most lopsided of the programme: one candidate investigated, one fixed, 37
sites repaired, and 48 tool modules plus five of six regions never opened. The plan predicted this
wave would terminate at its ceiling. It terminated well short of it, on a single high-value target.
