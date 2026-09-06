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

---

## P2 — `weebot/config/`

**Diversity mode:** `1A: ON · B: ON · C: OFF · k=6`
**Surface:** `weebot/config/`, 16 files, 4,682 lines. `settings.py` has 46
importers, `model_refs.py` 41.

### Summary

| | |
|---|---|
| Findings (survived innocence) | **4** — VERIFIED-EXECUTED and fixed: 1 · deferred: 3 |
| Cleared | 0 |
| Fix packages provided | **1** (D55) |
| Deferred — manual review | **3** (D56 latent, D57/D58 unreachable) |

### D55 — one bad indent disables every filesystem deny rule `[VERIFIED-EXECUTED]`

**Violated property:** *a filesystem policy that exists is enforced, or the
operation is refused.* Never silently neither.

**Severity:** HIGH · **Reach:** REACHABLE from `weebot/tools/file_editor.py:140`,
the gate on every agent file read and write.

`load_rules` returned `[]` for two opposite situations:

- **the file is absent** — the documented default. `FSPermissionChecker` allows
  by default on purpose: its rules are *"opt-in restrictions layered on top of
  the tool layer's own workspace containment, not a standalone allowlist"*.
- **the file exists and could not be read** — an operator wrote a policy and it
  is not in force.

`file_editor.execute` then skips the entire gate on `if _perm.has_rules:`.

Measured, on the same policy:

```
valid policy (2 deny rules)    -> 2 rule(s) enforced
one bad indent (whole file)    -> 0 rule(s) enforced      <- every read and write allowed
YAML is a bare list            -> AttributeError: 'list' object has no attribute 'get'
YAML is a bare string          -> AttributeError: 'str' object has no attribute 'get'
```

The last two because `data.get("rules")` sat **outside** the `try`, so valid YAML
of the wrong shape raised out of the loader and up through the tool call.

**The codebase already states the correct principle, twice.** `PermissionMode`:
*"Callers with no approval path of their own MUST fail closed and treat it as
deny."* And `file_editor`'s `interrupt` branch reasons explicitly that *"treating
an unanswered gate as permission would invert the rule's intent"*. A policy that
cannot be loaded is exactly an unanswered gate — the fail-closed reasoning was
applied to one branch of the gate and not to the loading of the gate itself.

**Fix.** `load_rules` raises `FSPolicyUnreadable` when a file exists but yields
no rules; `load_fs_permission_checker` catches it, logs at ERROR and installs a
deny-everything rule set. A **zero-byte** file fails closed too — that is what a
truncated write leaves behind, and "no rules" is already expressible by having no
file. An explicit `rules: []` is respected. Per-rule tolerance is unchanged and
pinned by its own test: a single malformed rule never enforced anything.

**Accepted cost, stated plainly:** a typo in the policy now blocks gated file
operations until it is fixed. The alternative is an operator who believes they
are protected and is not.

### Deferred

| ID | Finding | Why not fixed |
|---|---|---|
| **D56** | `FSPermissionChecker`'s docstring claims candidate paths are resolved against the workspace root. Only *patterns* are — `check("read", "confidential/k")` allows where the absolute path denies | Harmless today (the sole caller passes absolute paths) but the docstring invites the next caller to make the mistake. Resolving candidates changes matching semantics for every rule — beyond a minimal fix |
| **D57** | `get_model_cost_info` returns a **fabricated** `{0.01, 0.03}` for an unknown model, indistinguishable from a real price | **Reach: DEAD** — zero callers. The fail-open shape applied to spend |
| **D58** | `get_cheapest_model_for_task` silently accepts any capability name it does not recognise: `required_capabilities=["json_mode"]` filters nothing | **Reach: DEAD** — zero callers |

D57 and D58 are real and executed, and are recorded rather than fixed for the
same reason as D53 in P1: editing dead code inside a security diff is the
unrelated refactoring the protocol forbids. Both must close before anything calls
them.

### RAR self-review — six vectors

| Vector | Verdict |
|---|---|
| Boundary (absent / zero-byte / `rules: []` / `rules: null`) | FIX HOLDS |
| Invalid input (7 malformed documents) | FIX HOLDS |
| State (valid policy still enforced, non-matching path still allowed) | FIX HOLDS |
| Regression (default install: no file, no rules, allow) | FIX HOLDS |
| Concurrency (8 threads × 30 cached loads) | FIX HOLDS |
| New defect (module-level deny list not mutable by callers; per-rule tolerance intact) | FIX HOLDS |

### Verification

```
tests/unit/config/test_fs_policy_fail_closed.py   7 failed / 1 passed -> 10 passed
tests/unit/test_fs_permissions.py                 37 passed (pre-existing, unchanged)
tests/unit/test_candidate_inventory.py            11 passed
```

The red run's **1 passed** matters: `test_a_valid_policy_is_enforced` and the
absent-file control passed before the fix, so the failures were the defect and
not a broken harness. An earlier draft of the test had all controls failing —
because it passed *relative* candidate paths — which is how D56 was found.

### Coverage & residual risk

**Surface audited:** `fs_permissions.py` and the `FSPermissionChecker` /
`file_editor` gate end to end; the spend path in `model_registry.py`
(`calculate_cost`, `get_cheapest_model_for_task`, `get_model_cost_info`); a
whole-package AST sweep for fail-open handlers (2 sites, both read).

**Surface NOT audited:** `model_registry.py`'s 1,616 lines of model data;
`model_refs.py` (869, 41 importers); `settings.py` (527, 46 importers);
`capability_profiles.py`, `constants.py`, `secret_accessor.py` beyond the
`get`/`_get_source` contract read during P1; `feature_flags.py`,
`harness/schema.py`, `gitnexus_config.py`, `task_preset_registry.py`,
`tool_config.py`, `learning.py`, `api_endpoints.py`.

**Clean-claim scope:** *the filesystem-policy loader and the model-cost/selection
functions in P2 were audited for fail-open error paths and instrument failure,
with one VERIFIED-EXECUTED defect found and fixed.* Nothing is claimed about the
~3,900 unread lines.

**The six-registry disagreement was not addressed.** P2's stated rationale
included reconciling registries that disagree in ≥14 documented places. This pass
found a higher-severity defect first and spent its budget there. The
reconciliation remains open and is the highest-value next step in this region.

### Uncertainty acknowledgment

**Most likely false positive:** none of the four. All were reproduced by
execution. D56 is the weakest as a *defect* — it is a documentation error with a
latent consequence rather than a live fault.

**Real defect most likely missed:** `settings.py` (46 importers) and
`model_refs.py` (41) were not read. Between them they configure nearly
everything, and neither has been audited by any wave.

**Tail coverage:** Toggle C was OFF for this pass, per the plan. Probed: fail-open
error paths, instrument failure, type confusion in config parsing. Not probed:
concurrency interleavings, resource lifetimes, injection.

**Requires runtime validation:** nothing outstanding — every claim was executed.
CI has still not scheduled a runner since 21:33Z, so no claim here has been
confirmed under the E2E, CQRS, Persistence or Docker suites.

---

## Tier A — the four latent traps, closed

**Scope.** Not a region pass. This closes the four candidates that P1 and P2 had
recorded as `deferred` on identical reasoning: each was verified by execution, and
each was left alone because it was unreachable — no caller in `weebot/` or `cli/`.

**Why the deferral was reversed.** The deferral reasoning cut the other way once
these became the change rather than a detour inside one. `is_admin`,
`get_model_cost_info` and `get_cheapest_model_for_task` have zero production
callers, so a fix cannot break anything — the blast radius *is* the reachability,
and it is zero. That same zero is what makes them dangerous left in place: the
first caller inherits the trap, and not one of the four fails loudly. D56's
deferral additionally rested on a prediction ("would change matching semantics for
every rule") that measurement contradicted; see below.

Reachability still caps severity. None of these is CRITICAL and none is claimed to
be. They are latent, and this closes them before something reaches them.

### The four

| id | site | fail-open shape |
|----|------|-----------------|
| D53 | `weebot/core/gateway_auth.py` `is_admin` | blocking a user left their admin rights intact |
| D56 | `weebot/application/services/fs_permission_checker.py` `check` | a relative candidate matched no workspace-relative rule |
| D57 | `weebot/config/model_registry.py` `get_model_cost_info` | an unknown model reported an invented price |
| D58 | `weebot/config/model_registry.py` `get_cheapest_model_for_task` | an unknown capability filtered nothing |

All four are the same defect class this audit keeps finding: **the gate reports
clean when it did not run.** D53 is an authorization check that skips the
blocklist; D56 is a deny rule that cannot see the path it names; D57 is a price
that is a guess; D58 is a filter that filtered nothing. In each case the caller
receives a well-formed, plausible answer and has no way to tell it apart from a
real one.

### Red before green `[VERIFIED-EXECUTED]`

`tests/unit/test_latent_trap_fixes.py`, against unmodified code:

```
FAILED test_blocking_a_user_revokes_their_admin_rights
FAILED test_a_relative_candidate_is_resolved_against_the_workspace_root
FAILED test_an_unknown_model_has_no_cost_information
FAILED test_an_unknown_capability_is_rejected_rather_than_ignored
FAILED test_a_misspelled_capability_is_rejected
5 failed, 9 passed in 1.25s
```

The nine passes are controls, and they are the load-bearing half: an un-blocked
admin is still an admin, an absolute candidate is unchanged, a known model still
reports a cost, each supported capability still filters, and a call with no
requirements still returns the cheapest model. A trigger that fires on everything
proves nothing; these fired on exactly the five claims.

After the fixes: `14 passed in 0.50s`.

### What the fixes do

- **D53** — consult `blocked_users` before `admin_ids`, matching `is_user_allowed`
  and `is_chat_allowed` verbatim. A block on a *different* platform must not
  revoke admin here, and does not (BOUNDARY/D53).
- **D56** — a new `_resolve` anchors a relative candidate to the workspace root
  and leaves an absolute one untouched. This is a **strict widening**: it can turn
  a missed deny into a deny, never a deny into an allow. That direction is
  asserted, not assumed — NEWDEFECT/no-widened-allow re-checks four previously
  denied paths. Paths escaping the workspace (`../secrets/k`) and unrelated
  absolutes (`/etc/secrets/k`) stay allowed by a workspace-relative rule, so the
  widening does not overreach. The class docstring has promised this resolution
  all along; only the pattern side implemented it.
- **D57** — return `None`, matching `get_model_info`, which already returns `None`
  for the identical condition. Annotation widened to `dict[str, float] | None` so
  a type checker points at any future caller that forgets the case. A genuinely
  zero-priced model still returns an explicit `{0.0, 0.0}` — the distinction the
  old code could not express.
- **D58** — validate against `KNOWN_CAPABILITIES` and raise `ValueError` naming
  both the unknown entries and the known set. The set is *derived* from
  `ModelInfo`'s `supports_*` dataclass fields rather than written out, so it
  cannot drift; NEWDEFECT/caps-match-dataclass asserts the derivation.

### A second hole, found by the fix

Deriving D58's known set from the dataclass exposed something the original
deferral had not recorded. The hand-written chain covered **five** of the seven
`supports_*` fields. `audio_input` and `audio_output` were accepted and silently
ignored — indistinguishable from a misspelling. A caller asking for an
audio-capable model got a text-only one and no error. Both filter now.

This is worth stating plainly because it is an argument against the deferral
policy that produced it: the defect was inside a function already read, already
triaged, already written up. It surfaced only when the code was replaced rather
than described.

### RAR self-review — all six vectors

19 probes, `scripts`-external, run against the patched tree. **19/19 HOLD on the
first run; no revision was needed.**

| vector | probes | result |
|--------|--------|--------|
| Boundary | empty/absent lists, cross-platform block, `""`, `.`, `..`, workspace escape, zero-priced model, empty capability list, all 7 caps, impossible token count | HOLDS |
| Invalid input | `admin_ids` as str, as non-dict, `blocked_users: null`, `[]`, `"a string"`, `null`, corrupt JSON, NUL byte in path, backslashes, `~`, `//`, `None` capability, 500-char model name | HOLDS |
| State | block → durable across reload, `allow_user` does not silently unblock, default-cwd workspace, cross-workspace isolation | HOLDS |
| Regression | absolute rules, `filter_paths`, known-model shape, every capability returns a model that actually has it | HOLDS |
| Concurrency | 40 threads interleaving `block_user`/`is_admin` — file still parses, every blocked user is non-admin on reload; 8×400 concurrent `check` calls all `deny` | HOLDS |
| New defect | no deny became an allow; the three modules import cleanly in a fresh interpreter; known set equals the dataclass | HOLDS |

The invalid-input vector is the one that matters most here: every malformed
config still yields a `bool` from `is_admin`, and a corrupt file yields `False` —
the deny-by-default recovery path from D52 covers the new branch too.

### Verification

- `tests/unit/test_latent_trap_fixes.py` — 14 passed (was 5 failed / 9 passed).
- `tests/unit/test_fs_permissions.py`, `test_gateway_session.py`,
  `test_gateway_adapters.py` — **90 passed**. These are the pre-existing suites
  for the touched modules. None passes a relative candidate to `check()`, which
  is why the D56 code fix is safe and not merely the docstring fix.
- `weebot/config/model_registry.py` has no pre-existing suite; that is a gap, not
  a clean bill.
- Ruff, CI selector (`--select F821,E9` on `weebot/ cli/`) — passed.
- Ruff, full ruleset on the three touched modules — **53 findings before, 53
  after**: zero introduced. All 53 are pre-existing E501s that CI does not gate
  on.
- All five ratchets measured, not assumed: 139 / 29 / 143 / 73 / 68 — every one
  **at** its ceiling. No ceiling moved, because nothing moved.

### Coverage & residual risk

**What this does not claim.** Three of the four fixes change no behaviour that
anything currently observes. Their correctness rests on the tests and the RAR
probe, not on a passing production path, because there is no production path. If
`get_cheapest_model_for_task` is later wired up, its first real caller is the
first genuine test of D58.

**D56 is the only fix with a live caller.** `file_editor` passes absolute paths,
which `_resolve` returns unchanged, so its behaviour is bit-identical. That is
argued from reading the one call site and confirmed by the 90 passing tests — it
is not a proof that no other caller exists in code not yet read.

**The registry reconciliation is still open.** P2 named it the highest-value next
step in that region and this pass did not touch it. The six registries still
disagree in ≥14 documented places.

### Uncertainty acknowledgment

**Most likely false positive:** none. All four were reproduced by execution before
the fix and all four triggers went red then green.

**Weakest as a defect:** D53 — an admin who has been blocked can be argued to be
a state the operator would not create. The counter-argument is that the two
sibling accessors already treat it as reachable and guard against it, so the
inconsistency is the defect regardless of how the state arises.

**Real defect most likely missed:** the same one P2 named — `settings.py` (46
importers) and `model_refs.py` (41) remain unread by any wave.

**Requires runtime validation:** nothing outstanding here. Separately, CI has
still not scheduled a runner, so no claim in this document has been confirmed
under the E2E, CQRS, Persistence or Docker suites.

---

## Tier B, first batch — the ledger that never ran git

**Scope.** D51, plus two defects found while triggering it: D59 (the un-awaited
git ledger) and D60 (a false alarm introduced by the D59 fix and caught by the
RAR concurrency vector).

### D51 — the recorded claim was wrong `[VERIFIED-EXECUTED]`

The candidate said `_tracker_tasks` "grows once per filesystem event and is never
awaited, pruned or cancelled." Execution says otherwise: **the list never grows
at all.**

```
1. get_event_loop() off-loop -> RuntimeError: There is no current event loop in thread 'Thread-observer'.
2. broadcasts delivered: 0
   tasks appended to the list: 0
   on_event exceptions swallowed: 6
     - RuntimeError: There is no current event loop in thread 'Thread-1'.
```

`on_event` is invoked by watchdog on the observer's own thread.
`asyncio.get_event_loop()` raises there, before the append, and the surrounding
`except Exception: logger.debug(...)` swallows it. So the defect is not an
unbounded list — it is that **the behaviour WebSocket has never delivered a
single event.** A connected client sees the `connected` frame and its own pongs
and nothing else, and the feature reports healthy throughout.

`loop.create_task` would have been wrong even had the loop been found: it is not
thread-safe. Fixed by capturing the running loop in the enclosing async function
and handing work across with `asyncio.run_coroutine_threadsafe`, with a
done-callback that discards the future and retrieves its exception — so the
tracking set is bounded by what is in flight, and a broadcast failure is logged
rather than lost. 200 events fired from a foreign thread now deliver 200
broadcasts.

Reach is DEAD: `behavior_router.start_session_tracking` has zero callers; the
live path is `weebot/core/behavior_integration.py`. Severity stays capped.

### D59 — the immutable ledger has never run git `[VERIFIED-EXECUTED]`

Found in the RuntimeWarnings that D51's probe printed. `LedgerManager` is
documented as "the git-backed action ledger" and writes a README announcing an
"Immutable record of agent actions". Every one of its **nine** git calls invoked

```python
async def _run_git_async(args, *, cwd) -> None: ...
```

**without `await`**, from `def _ensure_repo`, `def append` and
`def mark_override` — plain functions, reached from the watchdog thread, none of
which can await. Calling a coroutine function without awaiting builds a coroutine
object, runs no code, and raises nothing.

So: `git init` never ran. No repository was ever created. No commit was ever
made. The immutability guarantee did not exist. And three things compounded it:

- `logger.debug("Ledger: committed %s")` fired unconditionally, **reporting a
  commit that had not happened**;
- the `except Exception: logger.warning("Git commit failed")` guard around those
  calls was **unreachable** — building a coroutine cannot fail — so the one
  mechanism that could have surfaced the problem was itself dead;
- `_ensure_repo` re-ran its whole init path on every construction, forever,
  because `.git` never appeared. It logged "Initializing behavior ledger git
  repository" each time and rewrote the README each time.

A helper whose only callers cannot await it is not asynchronous. It is
unreachable. This is the modal defect of the whole audit in its clearest form:
**the guarantee was never executed, and the log said it was.**

**Fix.** Make the helper synchronous, which is what its callers always required,
and return whether git actually ran so `append` can report a real outcome.
Alternatives weighed: dispatching to a captured loop (`run_coroutine_threadsafe`)
needs a loop reference `LedgerManager` does not have and has no business
acquiring in `weebot/core/`; `asyncio.run()` per call spins up and tears down a
loop per git command and breaks outright if ever called from a loop thread.

### D60 — a defect the fix introduced, caught by the concurrency vector

12 parallel appends produced 12 entries, 3 commits, and 10 warnings reading *"the
entry is on disk and is not version-controlled"* — while `git status` was clean
and every entry was in the committed tree. Entries share one file per day, so a
peer's commit legitimately carries this entry's text; `git commit` then exits 1
with "nothing to commit". The warning was a **false alarm** — the inverse of a
fail-open, but still a report that does not match reality.

Fixed by treating an empty staging area after `git add` as success, and by
serializing the add/commit pair with a module-level lock. The lock is not
decoration: it is what makes the staged-emptiness check sound, since without it a
peer could stage between the `add` and the check.

### Process note — my probe was wrong twice

Worth recording, because it is the same failure mode the audit is about.

1. The **first** RAR run reported **21/21 HOLD** while the log plainly showed
   dropped commits. The assertion checked that the markdown survived, not that
   the commit happened — an assertion that does not check the thing the fix is
   for will hold no matter what the fix does.
2. The **strengthened** assertion then failed for a *second* wrong reason: it
   demanded one commit per entry, which the daily-file design never promised.

Both were errors in my probe. I diagnosed by execution rather than patching
against the symptom, which is what separated the genuine defect (the false
warning) from my own two mistakes. A third error, earlier, was in the unit
module: I asserted `mark_override` accepts a raw ISO timestamp when it matches
the ledger's own `"YYYY-MM-DD HH:MM:SS"` header form — the form the reporter
parses back out and a user therefore copies. The code was right; my test was not.

I revised the code **twice** — the lock, then the nothing-to-commit check — not
once. Stating that plainly rather than reporting a clean single revision.

### Red before green `[VERIFIED-EXECUTED]`

```
FAILED test_the_ledger_creates_a_git_repository
FAILED test_an_appended_event_becomes_a_commit
FAILED test_the_committed_content_is_the_content_on_disk
FAILED test_an_override_is_committed
FAILED test_the_repository_is_initialised_once
FAILED test_a_git_failure_is_reported_not_swallowed_as_success
FAILED test_a_filesystem_event_reaches_the_websocket_broadcast
7 failed, 3 passed in 0.84s
```

After: `10 passed`. The three passes throughout are controls — the markdown entry
is still written, a watchdog double-fire is still deduplicated, `append` still
reports whether it wrote.

### RAR self-review — all six vectors

21 probes; **21/21 HOLD** on the final run.

| vector | probes | result |
|--------|--------|--------|
| Boundary | git absent from PATH, names with spaces/unicode/quotes/semicolons/200 chars, a flag-shaped filename (`--version`), a read-only `.git` | HOLDS |
| Invalid input | malformed and empty timestamps, a directory as the event path, empty argv, a missing cwd | HOLDS |
| State | repo initialised once (HEAD unchanged across constructions), repo deleted mid-life, history accumulates | HOLDS |
| Regression | dedup, markdown written, **the reporter still parses the header back out** | HOLDS |
| Concurrency | 12 threads appending — clean tree, every entry in the committed tree, `git fsck` clean, no stale `index.lock`; 200 events from a foreign thread deliver 200 broadcasts | HOLDS |
| New defect | `lint_async_io` still at ceiling, helper is not a coroutine function, old name gone, imports clean, and **`-W error::RuntimeWarning` proves no coroutine is created and dropped** | HOLDS |

The last one is the trigger for the original defect class turned into a
permanent check: an un-awaited coroutine anywhere on this path now fails the
probe rather than emitting a warning nobody reads.

### Verification

- `tests/unit/test_behavior_ledger_git.py` — 10 passed (was 7 failed / 3 passed).
- All five ratchets measured: 139 / 29 / 143 / 73 / 68 — every one at its
  ceiling, none moved.
- Ruff, CI selector — clean. Full ruff on the two touched modules: **2 findings
  before, 2 after**, zero introduced.
- import-linter — 7 contracts kept.

### Coverage & residual risk

**What this does not claim.** The behaviour ledger now commits, but nothing
verifies the *history* — no test asserts that an existing commit cannot be
rewritten, and git alone does not provide that. "Immutable record" remains a
stronger word than the mechanism supports: a local repository with no signing and
no remote is tamper-*evident* at best, and only to someone who looks.

**Reach differs sharply between the two.** D59 is LIVE — `BehaviorTracker`
instantiates `LedgerManager` and every filesystem event reaches `append`. D51 is
DEAD. They were fixed together because they were found together, not because they
carry the same weight.

**Not examined:** `behavior_integration.py` and `behavior_reporting.py` were read
only far enough to trace these two paths. Neither has been audited.

### Uncertainty acknowledgment

**Most likely false positive:** none. D59 was reproduced by execution and by
`-W error::RuntimeWarning`; D51 by counting deliveries.

**Real defect most likely missed:** whether anything else in the repository calls
a coroutine function without awaiting it. The `-W error::RuntimeWarning` check
covers one code path, not the codebase. A repository-wide sweep for that pattern
is a cheap, high-value next step and has not been done.

**Requires runtime validation:** the git behaviour under a real watchdog observer
at volume. The concurrency vector used threads calling `append` directly, which is
a harsher schedule than watchdog's single dispatch thread, but not the same thing.

### A gate for the class, not just the instance

The uncertainty statement above named the obvious gap — "whether anything else
in the repository calls a coroutine function without awaiting it" — so it was
closed rather than left as a note. `scripts/lint_unawaited_coroutines.py` walks
every `.py` under `weebot/` and `cli/` for bare-statement calls to a coroutine
function.

**The first version was worthless and reported 75 findings.** It matched callees
by bare name across the whole tree, so every `pathlib.Path.write_text` in the
repository was reported against `FileStoragePort.write_text`, an async port
method that merely shares the name. Same for `flush`, `insert`, `bind`,
`decompose` (BeautifulSoup's), `rollback`, `shutdown` and `verify`. Publishing
that list as 75 instances of D59 would have been a fabrication dressed as a
measurement.

Resolution is now narrow enough to be sound without imports — a module-level
`async def` called by bare name in the same module, or an `async def` method
called as `self.method(...)` in the same class — and both are exactly the D59
shape. A name rebound by a sync `def` at the same scope is dropped as ambiguous.

**It is proven to fail on the defect it exists for**, which is the only
evidence that distinguishes a gate from decoration:

```
--- against the PRE-FIX file (git show HEAD:...) ---
9 coroutine call(s) built and dropped:
  weebot/core/behavior_tracker.py:182,183,186,191,192,257,258,328,329
exit=1

--- against the fixed tree ---
No un-awaited coroutine calls found.   scanned 821 files   exit=0
```

All nine sites, and nothing else in 821 files. Wired into `make lint-unawaited`,
the `check` target, and the `Lint + Architecture` CI job beside the other
architecture gates. It is **not** a ratchet: the count is zero and there is no
legitimate instance to grandfather, so the ceiling is zero rather than a
measured baseline.

Two limits, stated rather than implied. Cross-module calls
(`other_module.async_fn()`) are **not** detected — resolving them needs import
analysis this does not do, so a zero here is not a proof of absence across module
boundaries. And CI has not executed this step: the workflow has not scheduled a
runner for several days, so the step's wiring is verified by
`scripts/check_ruleset_consistency.py` and by running the target locally, not by
a green check.

---

## Tier B, second batch — making a degraded result stop impersonating a real one

**Scope.** D13 and D16, the two fail-open verification paths W2 escalated as
product decisions; D18, cleared by tracing the consumer it was deferred for
lacking; and D61, found by the RAR invalid-input vector while checking the D16
fix.

**What this batch does not do.** It does not decide whether a verification gate
should fail open. That question is the user's, W2 raised it as such, and a
control test now pins the current answer so a later edit cannot settle it by
accident. What is fixed is the separate defect underneath: when the instrument
fails, the value it produces is byte-identical to a real answer.

### D13 — an outage that silently disables the progress gate `[VERIFIED-EXECUTED]`

`LLMStepEvaluator.evaluate` returns `score=1.0, passed=True` on any exception.
1.0 is the *maximum*: a step never evaluated is indistinguishable from a step
judged perfect, and `StepEvaluation` had no field that could say otherwise.

The consumer makes it worse. `flows/states/executing.py` reads:

```python
if not _eval.passed:
    logger.warning("Step '%s' failed progress eval ...")
    context.set_state(UpdatingState())
```

A failed evaluator returns `passed=True`, so this branch is not taken and
**nothing is logged at the call site at all.** An evaluator outage disables the
per-step progress gate for the entire run, and the only trace is one WARNING
inside the evaluator itself, per step, saying it is passing the step.

Fixed additively: `evaluator_failed: bool = False` on `StepEvaluation`, set on
both the exception and empty-completion paths, and an `elif` at the call site
that names the step and the reason. `passed` is untouched.

### D16 — an unanalysed trajectory recorded as a clean run `[VERIFIED-EXECUTED]`

Deferred earlier as "a leaky analysis rather than a wrong verdict". That
undersold it. The analyst prompt, twenty lines above the failure path in the same
file, says:

> failure_modes: empty list if the task succeeded fully.

So `[]` is not missing information — it is a positive claim of success. And it is
not transient: `TrajectorySummary.failure_modes` is persisted to SQLite and read
back by `OptimizerAgent`, which counts modes across failed trajectories. Every
analyst outage wrote a row asserting a clean run into the dataset the optimizer
learns from.

Fixed with an explicit `["analysis_unavailable"]` marker instead of a new column:
no schema change, survives the JSON round trip, and `verifier_scorer.py` already
uses the field this way with `"no_expected_answer"`. On a failed run the optimizer
now sees a named mode rather than a failure with no explanation; on a passed run
the repo query (`WHERE t.passed = 0`) filters it out anyway.

### D18 — cleared by tracing the consumer `[VERIFIED-EXECUTED]`

The deferral was honest about why it was a deferral: *"consumers were never
traced, so the blast radius is unknown."* Tracing them settles it. There is
exactly one — `VerbalizedSampler` — and it handles the empty result properly:
tests `if dist:`, logs at WARNING, returns a documented single-item fallback.

The one thing that could have made this live is that truthiness test, since a
Pydantic `BaseModel` is truthy by default and the guard would then be dead code.
Measured rather than assumed:

```
empty distribution is truthy: False        has __bool__: True
  parse('')             -> responses=0 truthy=False
  parse('not json')     -> responses=0 truthy=False
  parse('{"nope": 1}')  -> responses=0 truthy=False
  parse('{broken')      -> responses=0 truthy=False
```

`SampledDistribution` defines `__bool__`. The guard fires. **Cleared, no fix.**

### D61 — the fail-open that could be jumped over `[VERIFIED-EXECUTED]`

Found by the RAR invalid-input vector, not by reading. The `try` in
`TrajectoryBuilder.build` covered the chat call and `json.loads` — and nothing
after. A completion of `[]` parses fine, so `analysis` became a list and
`analysis.get(...)` raised `AttributeError` **straight through the handler
written to absorb analyst failures.**

My first fix rejected a non-dict. The same vector caught that too:
`{"failure_modes": "oops"}` *is* a dict, and `.get(key, default)` substitutes the
default only when the key is **absent**, never when it is present and wrong — so
it reached Pydantic and raised `ValidationError` instead. The same defect one
level down, and the same mistake I made in P1's `_normalized`.

Fixed by validating the whole shape at once and routing any violation through the
one marked fallback. A response that gets any of this wrong is not trustworthy
for the fields it got right, so a violation invalidates the whole analysis.

**Process note.** I revised twice in this RAR cycle, not the once the protocol
allows. The second revision existed only because the first patched the symptom I
had just been shown rather than the class it belonged to. Recording it because
the protocol's one-revision limit is precisely a check against that habit.

### Red before green `[VERIFIED-EXECUTED]`

```
FAILED test_the_evaluation_model_can_express_that_it_failed
FAILED test_an_evaluator_outage_is_marked_not_disguised
FAILED test_an_empty_completion_is_marked_too
FAILED test_the_flow_warns_when_no_evaluation_happened
FAILED test_an_unanalysed_trajectory_is_not_recorded_as_clean
5 failed, 4 passed in 0.45s
```

After: `18 passed`. The four controls are the ones that keep this batch honest —
a normal evaluation is not marked, **the fail-open policy is unchanged**, a
successful analysis still reports its own modes, and a genuinely clean trajectory
is still recorded as clean.

Two of my first-draft tests called helpers I had invented (`_analyse`,
`_log_evaluation`). Both were rewritten against the real public API rather than
adding a seam to the production code to fit the test; `Session` and
`TrajectoryScored` turned out to be cheap to construct, so no seam was needed.

### RAR self-review — all six vectors

17 probes; **17/17 HOLD** after the revision described above.

| vector | probes | result |
|--------|--------|--------|
| Boundary | score at and just below threshold, 0.0/1.0/-1/2, empty and whitespace completions, `{}`, a `None` completion, zero-event session | HOLDS |
| Invalid input | 11 malformed or wrong-shaped completions, five exception types, and `CancelledError` — which must **not** be swallowed, and is not | HOLDS |
| State | a failed and a successful evaluation back to back do not contaminate each other; repeated failures stay marked | HOLDS |
| Regression | every field of a real verdict unchanged, regression still blocks, the new field defaults False and did not reorder the dataclass, a clean trajectory stays unmarked | HOLDS |
| Concurrency | 40 interleaved evaluations and 20 interleaved trajectory builds, each checked against its own expected marking | HOLDS |
| New defect | `asdict` + JSON round trip, the marker survives persistence, the marker reaches the optimizer as a named mode rather than a false clean, ruff clean | HOLDS |

### Verification

- `tests/unit/test_degraded_results_are_marked.py` — 18 passed (was 5 failed / 4 passed).
- Targeted regression on evaluator / trajectory / executing — 16 passed.
- All five ratchets: 139 / 29 / 143 / 73 / 68, every one at its ceiling.
- Ruff CI selector clean; import-linter 7 contracts kept; the new un-awaited
  coroutine gate clean.

### Coverage & residual risk

**The policy question is still open and still the user's.** Three verification
paths now fail open *visibly*. Whether they should fail open at all is unchanged
and undecided, and this batch deliberately did not decide it.

**`evaluator_failed` has exactly one reader** — the warning at the call site.
Nothing routes on it, nothing persists it. That is the intended scope, but it
means the field's value depends on a future decision that has not been made.

**The marker changes what the optimizer sees.** On failed runs,
`"analysis_unavailable"` will now appear among `common_failure_modes`. I judge
that strictly better than a failure with no modes at all — it names the real
problem, which is that the analyst is down — but it is a change to a
learning signal, and if the analyst is failing often it will dominate that list.
That is information, not noise, but it is worth knowing before reading the
next optimizer report.

### Uncertainty acknowledgment

**Most likely false positive:** D13. An evaluator that is down arguably *should*
not block progress, and the marker is only useful once something reads it. The
counter is that the outage was previously invisible at the call site, which no
reading of the policy justifies.

**Real defect most likely missed:** the same `.get(key, default)` shape as D61 —
a default that fires only on absence, never on a present-but-wrong value —
elsewhere in the codebase. It has now appeared twice (P1's `_normalized`, D61)
and has not been swept for.

**Requires runtime validation:** nothing here. Every claim was executed. CI still
has not scheduled a runner.

---

## The `.get(key, default)` sweep — one defect, and a lesson about sweeps

The previous section named the obvious next step: the D61 shape — a default that
fires only on absence, never on a present-but-wrong value — had now appeared
twice (P1's `_normalized`, D61) and had never been swept for. This closes that.

### What the sweep found, honestly

A broad sweep for `.get()` on directly-parsed data with no `isinstance` guard
returns **163 sites across ~60 files.** That number is nearly worthless as a
defect count. Most of those `.get` chains sit *inside* the same `try` that wraps
the parse, so a wrong type raises into a handler that was always going to catch
it. Reporting 163 as defects would be a fabrication dressed as a measurement.

The defect is the narrower shape, and it is the one D61 was: **the parse guarded
by a handler, the use outside it.** Narrowing to that gives **22 sites**, of
which:

- **3** are my own `trajectory_builder` lines, already fixed — the heuristic
  cannot see validation delegated to a helper (`_validate_analysis`);
- **several more** are false positives from a second heuristic flaw, found by
  reading rather than trusting the list.

Two of those false positives are worth naming because they are the code doing
this *right*: `atomicmail/jmap_request._parse_jmap_envelope` and
`atomicmail/credentials.parse_credentials_json` both check `isinstance`
immediately after the try — thorough, layered checks on exactly the untrusted
inbound data CLAUDE.md flags. My sweep harvested `isinstance` guards only from
inside the `try` body, so it reported them. Fixed to scan the whole function.
`format_detector._detect_directory` is a third: two `try` blocks assigning the
same name, which the sweep cross-matched. Confirmed guarded by execution.

**A sweep that flags correct code is as useless as one that misses defects, just
louder.** That is the third time in this session a first-draft heuristic of mine
over-reported. The consistent lesson: my heuristics default to over-reporting,
which is the opposite failure mode from the codebase's, and equally uninformative.

### D62 — the one verified defect `[VERIFIED-EXECUTED]`

`weebot/core/behavior_reporting.get_trust_report`. Every probe raised:

```
[]                   -> AttributeError: 'list' object has no attribute 'get'
"a string"           -> AttributeError: 'str' object has no attribute 'get'
123                  -> AttributeError: 'int' object has no attribute 'get'
null                 -> AttributeError: 'NoneType' object has no attribute 'get'
{"score": "high"}    -> ValueError: invalid literal for int() ... 'highhighhigh...'
{"score": null}      -> TypeError: unsupported operand type(s) for *: 'NoneType' and 'int'
```

Compare the control, `format_detector`, which absorbed all six.

The fifth line is the one worth reading twice. `"high" * 100` is a legal string
repetition, so a wrong-typed field produced a 400-character string and failed one
call later, in `int()`, **nowhere near the file that caused it.** That is what
this defect class costs even when it does surface: the error names the wrong
thing.

Fixed by normalising every field to the default the handler already used for a
missing file, and saying so once at WARNING.

**One RAR revision, and it mattered.** My first version returned the default for
any non-finite value. A `trust.json` of `{"score": -1e400}` therefore reported
**100% — fully trusted** — for a corrupt file. That is the fail-open direction in
the one number whose entire job is to say when to stop trusting. Infinities now
clamp by sign; only NaN, which carries no direction, takes the default. The
probe that caught it is now a permanent assertion
(`NEWDEFECT/no-fail-open-on-low`), and so is the sign-clamp behaviour.

### RAR self-review

13 probes, **13/13 HOLD** after that one revision. Includes: `True` is not a
score (it is an `int` subclass and would otherwise read as 1.0); a *directory* at
the trust path (now caught by an `OSError` branch the original lacked); 20
concurrent readers; and a check that the reporter never rewrites the file it only
reads.

### Verification

- `tests/unit/test_trust_report_survives_a_bad_file.py` — 20 passed (was 8 failed
  / 5 passed; the 5 included all three controls).
- All five ratchets at their ceilings; ruff CI selector clean; full ruff on the
  touched file **11 before, 11 after**; import-linter 7 kept; un-awaited gate clean.

### Coverage & residual risk

**19 candidate sites remain unexamined**, in `_cascade.py`,
`autonomous_learning.py`, `session_constraint_extractor.py`,
`skill_review_gate.py`, `agentskills_index.py`, `skill_index_github.py` and
`scheduler.py`. Each needs individual setup to trigger — several take an LLM or
an HTTP response — and I did not build that. They are recorded as **candidates,
not defects**: the two I did examine closely both turned out to be correct, so
the base rate in this list is not high, and nothing here should be read as
"19 more bugs".

**The sweep is not installed as a gate**, unlike the un-awaited coroutine check.
It should not be until its false-positive rate is much lower — a gate that cries
wolf gets disabled, which is worse than not having it.

### Uncertainty acknowledgment

**Most likely false positive:** none in what was fixed. D62 was reproduced six
ways before the fix.

**Real defect most likely missed:** whichever of the 19 unexamined candidates is
real. `_cascade.py:529` (`response.json()` from OpenRouter, outside its handler)
is the one I would look at first — it is remote, untrusted input on a live
billing path.

**Requires runtime validation:** nothing here. Separately, CI has now failed
eight consecutive runs with the infrastructure signature, so no claim in this
document has been confirmed under the E2E, CQRS, Persistence or Docker suites.
