# V3 static defect audit — execution record

Running [`static_defect_audit_v3_execution_plan.md`](../specs/static_defect_audit_v3_execution_plan.md)
over `weebot/` and `cli/`. One section per pass.

---

## P1 — `weebot/core/`

**Diversity mode:** `1A: ON · B: ON · C: ON · k=6`
**Surface:** `weebot/core/`, 43 files, 12,042 lines, **64 importing modules** — the
widest blast radius in the backend.

### Summary

| | |
|---|---|
| Findings (survived innocence) | **2** — VERIFIED-EXECUTED: 1 · deferred-unreachable: 1 |
| Cleared (innocent, disproven) | **2** — `is_enforcing` None-deref, `bash_guard` callback swallow |
| Fix packages provided | **1** (D52) |
| Deferred — manual review | **1** (D53) |
| Unresolved | 0 |

### D52 — one interrupted write erases an access-control list `[VERIFIED-EXECUTED]`

**Violated property:** *a persisted access-control decision survives a process
restart.* `block_user` is durable by contract — after it returns, the block must
still be recoverable.

**Severity:** HIGH · **Reach:** REACHABLE from `weebot/interfaces/gateways/base.py:69`
(gateway message handling) and `cli/commands/gateway.py:40`.

Two halves of one root cause, at two sites:

1. **The write truncates.** `Path.write_text` opens with `w`, so a write that
   dies partway — full disk, killed process, evicted container — leaves the
   previous contents destroyed and the new ones incomplete.
2. **The load substitutes.** `_load` answers the parse failure with defaults, and
   the next administrative action saves those defaults *over* the unreadable
   file. A recoverable problem becomes unrecoverable, and the only record of
   what the control used to say is gone.

Proven by trigger before any fix (`4 failed`):

```
test_a_save_that_dies_partway_does_not_leave_the_gateway_config_unreadable   FAILED
test_an_unreadable_gateway_config_is_preserved_rather_than_overwritten       FAILED
test_an_unreadable_gateway_config_is_reported_loudly                         FAILED
test_a_save_that_dies_partway_does_not_lose_the_egress_allowlist             FAILED

WARNING weebot.core.egress_guard: allowlist save failed
OSError: [Errno 28] No space left on device
E   assert False
E    +  where False = is_known('finance@example.com')
```

That last one is the sharpest: a previously **approved egress recipient was
gone**, the failure was logged, and the guard carried on as though nothing had
been lost.

**Fix.** `weebot/core/durable_state.py` — `write_text_atomic` (temp file in the
destination directory, `fsync`, `os.replace`) and `preserve_unreadable`
(`*.corrupt.bak`, a rule `.gitignore` already carried at line 121 for a
convention nothing had implemented). Both call sites converted. The gateway now
reports the loss at ERROR: an access-control list disappearing is not a warning.

The fix does **not** change any authorization verdict. Falling back to
deny-by-default was already correct; what was wrong was destroying the evidence.

### D52, second half — found by the RAR invalid-input vector

Reviewing the fix surfaced a **pre-existing** defect the fix had not addressed:

```
[]                              -> AttributeError: 'list' object has no attribute 'get'
"a string"                      -> AttributeError: 'str' object has no attribute 'get'
null                            -> AttributeError: 'NoneType' object has no attribute 'get'
{"allowed_platforms": null}     -> TypeError: argument of type 'NoneType' is not iterable
```

Every payload is **valid JSON**, and every one raised out of the authorization
decision itself. An access-control gate must not be crashable by editing its own
config file. `_load` now validates shape, and anything of the wrong type falls
back to its default — which denies.

**The first draft of that validation was itself fail-open.** A `setdefault` pass
over the raw payload put the rejected value straight back, so
`allow_all_by_default: "yes"` returned as a truthy string and opened the gate —
the recovery path re-admitting exactly what it had just rejected. It has its own
regression test, because it is the same shape as the defect being fixed and will
be reintroduced by anyone who "simplifies" the merge.

### Cleared

| Candidate | Why innocent |
|---|---|
| `egress_guard.is_enforcing()` calls `.lower()` on `SecretAccessor.get(...)`, which is typed `str \| None` | `_get_source()` returns `dict[str, str]` or `dict(os.environ)`; `dict.get(key, "true")` cannot return `None` with a non-None default. The `or` guard on the adjacent `_ALLOWLIST_PATH` line looked like evidence the author knew of a None path — it is defensive, not evidential |
| `bash_guard.evaluate` swallows the security-event callback | `max_risk` is computed before the callback and returned regardless, so no swallow can change the verdict. Recorded as D54 rather than dropped: it is still an instrument that can fail unobserved |

### RAR self-review — all six vectors, re-run after the revision

| Vector | Verdict |
|---|---|
| Boundary (empty file, missing parent dirs, zero-length payload) | FIX HOLDS |
| Invalid input (8 malformed payloads) | FIX HOLDS *(BREAKS on first pass → revised once)* |
| State (corrupt at execution, second corruption over an existing `.corrupt.bak`) | FIX HOLDS |
| Regression (every authorization verdict unchanged) | FIX HOLDS |
| Concurrency (8 threads × 15 saves) | FIX HOLDS — 0 errors, file always valid JSON |
| New defect (forced write failure) | FIX HOLDS — no leaked temp files, original intact |

### Verification

```
tests/unit/core/test_security_state_durability.py   4 failed  -> 14 passed
tests/unit/                                         3919 passed / 0 failed  (was 3905)
tests/unit/test_candidate_inventory.py              11 passed
ruff check --select F821,E9 weebot/ cli/            clean
lint-imports                                        7 kept / 0 broken
ratchets  139 / 29 / 143 / 73 / 68                  all unchanged, at ceiling
```

`weebot/core/durable_state.py` is stdlib-only, so it adds no import edge.

### Prevention

- **`weebot/core/` holds 8 more non-atomic `write_text` calls** to state files:
  `behavior_tracker.py:121,190,286,324`, `circuit_breaker.py:391`,
  `behavior_reporting.py:473`. Two of them (`TRUST_FILE`, breaker state) carry
  decisions the system acts on. Route them through `write_text_atomic`.
- Add a lint rule — an AST check in the style of `scripts/lint_except_pass.py` —
  forbidding `Path.write_text` on anything under a `*_FILE` / config path
  constant, so the next one is caught rather than found.

### Coverage & residual risk

**Surface audited:** `weebot/core/` — the security and access-control cluster in
depth (`gateway_auth`, `egress_guard`, `bash_guard`, `trust_boundary`, `safety`,
`secret_redaction`, `credential_sanitizer`), plus a whole-package AST scan for
fail-open exception handlers (12 sites reviewed).

**Surface NOT audited:** the remaining 35 modules were scanned only by the
fail-open sweep, not read line by line — `dashboard.py` (722),
`behavior_tracker.py` (548), `workflow_tracer.py` (529), `structured_logger.py`
(499), `workflow_orchestrator.py` (497), `circuit_breaker.py` (492),
`behavior_reporting.py` (490), `agent_context.py` (455), `dependency_graph.py`
(440), `memory_monitor.py` (438), `adaptive_concurrency.py` (417),
`approval.py` (414), `alerting.py` (363), `approval_policy.py` (362), and the
error-system trio. `model_cascade_config.py` (579) is deferred to pass P2, where
it belongs with the other model registries.

**Defect classes covered:** fail-open error paths; instruments that cannot fail;
durability of persisted security state; type-confusion in config loading;
reachability of auth accessors.

**Clean-claim scope:** *region P1's security/access-control cluster was audited
for the classes above with one VERIFIED-EXECUTED defect found and fixed.* This
says nothing about the 35 modules read only by the sweep, and nothing about
classes not hunted (concurrency interleavings, resource lifetimes, injection).

**Residual risk, stated:**

- A second corruption **overwrites the first** `.corrupt.bak`. The most recent
  damage is the most relevant, so this was accepted rather than versioned.
- `GatewayAuth` still does read-modify-write with no file lock, so two processes
  mutating concurrently can lose one update. Atomicity fixes torn *files*, not
  lost *updates*. Pre-existing, out of scope, and now the sharpest remaining
  defect in this file.
- `preserve_unreadable` returns `None` on failure rather than raising: recovery
  must not fail the caller that is already recovering. If the preserve fails, the
  next save still destroys the file — the ERROR log says which happened.

### Uncertainty acknowledgment

**Most likely false positive:** D54 (`bash_guard` callback swallow). Cleared as a
decision defect and it genuinely is one, but calling it a monitoring gap may be
too generous to a `pass` in a security path.

**Real defect most likely missed:** `approval.py` (414) + `approval_policy.py`
(362) were read only for their signatures. The approval gate is the highest-value
unread surface in P1, and CLAUDE.md names it as the interlock protecting inbound
untrusted mail.

**Tail coverage:** Toggle C probed leak-on-error, ordering/idempotency, and
type-confusion in config parsing. The last one paid — it is what the RAR vector
caught. Not probed: DST/timezone, integer overflow, lock ordering.

**Requires runtime validation:** nothing outstanding — every claim here was
executed. Coverage under the E2E, CQRS, Persistence and Docker suites has not
been observed because CI has been unable to schedule runners since 21:33Z.

**What static analysis could not determine:** whether a partial write is
*likely* in this deployment (needs disk/eviction telemetry); whether two gateway
processes ever run concurrently against one config.
