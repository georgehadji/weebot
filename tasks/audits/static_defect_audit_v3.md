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

---

## The alerting module that could not be imported

**Scope.** D23, whose recorded location did not exist; and D63 and D64, two
modules that raise at import time and had never run.

### How this started

D23 read: *"`get_event_loop()` + `create_task` from the watchdog observer thread,
swallowed"*, at `weebot/infrastructure/watchers/`. That directory **does not
exist**, and the verdict said *"generated and read; not triggered within W3's
budget."* The candidate named a region, not a site, and was never verified.

An AST sweep for the actual shape — `asyncio.get_event_loop()` together with
`create_task`/`ensure_future` inside a **synchronous** function — found exactly
**one** instance in 821 files: `AlertManager._dispatch`.

Trying to trigger it produced something else entirely.

### D63 — the alerting subsystem has never loaded `[VERIFIED-EXECUTED]`

```
AttributeError: module 'asyncio' has no attribute 'coroutine'
```

`weebot/core/alerting.py:105`:

```python
AsyncAlertHandler = Callable[[Alert], asyncio.coroutine]
```

`asyncio.coroutine` was deprecated in Python 3.8 and **removed in 3.11**. This
project runs 3.12.3 and its CI pins `python-version: "3.12"`. The statement is at
module level, so `import weebot.core.alerting` raises. **The entire alerting
subsystem — AlertManager, severities, grouping, deduplication, handler dispatch —
could not load.**

Nothing caught it, and the reasons matter:

- **ruff's CI selector is `F821,E9`.** `asyncio.coroutine` is an ordinary
  attribute access on a module that exists, not an undefined name. F821 has
  nothing to say about it.
- **No test imported the module.** So the suite was green on a file that raises
  at import.
- **Nothing in production imports it either** — zero importers across `weebot/`,
  `cli/`, `tests/` and `scripts/`. That is why it stayed broken for however long,
  and why fixing it is safe.

An alerting system that cannot be imported is the failure this audit keeps
finding, in the one component whose job is to report failures.

### D64 — a stale import path from the refactor `[VERIFIED-EXECUTED]`

`strategy_adaptation.py` imports `weebot.workflow_planner`, a path that has not
existed since the Clean Architecture refactor moved it to
`weebot.application.flows.workflow_planner`. Also zero importers, also unnoticed.

**Fixing it tripped the architecture gate, correctly.** `flows/` already imports
`services/` at module level, so a module-level edge back closes an import-time
cycle — `test_no_services_flows_cycle` failed on my first attempt. That test's
docstring tolerates lazy imports inside functions, so the two construction sites
import locally and the annotations rely on `from __future__ import annotations`
plus `TYPE_CHECKING`. Smoke-tested by actually calling `adapt_workflow_plan` with
a real `WorkflowPlan`, which executes both lazy imports — the specific risk of a
`TYPE_CHECKING` refactor is an annotation-only import that turns out to be needed
at runtime.

### The measurement, and a gate with a real zero

```
scanned 807 modules

=== BROKEN CODE: 1 ===
   weebot.core.alerting: AttributeError: module 'asyncio' has no attribute 'coroutine'

=== missing optional dependency: 1 ===
   weebot.application.services.strategy_adaptation: No module named 'weebot.workflow_planner'
```

Two out of 807, and the second is misfiled by my own classifier: a missing
**first-party** module is a stale path, not an optional dependency. The committed
gate makes that distinction — a missing `weebot.*` or `cli.*` module fails; a
genuinely absent third-party package skips.

`tests/unit/test_every_module_imports.py` went from **2 failed / 805 passed** to
**807 passed, 0 skipped**. The ceiling is zero, not a measured baseline: unlike
the debt ratchets there is no legitimate un-importable module to grandfather.

### D23 — verified at last, and it is the D51 defect again `[VERIFIED-EXECUTED]`

With the module importable, `_dispatch` could finally be run:

```
from the loop thread    -> ok,        1 async handler delivered
from a foreign thread   -> RuntimeError: no current event loop in thread 'Thread-worker'.  0 delivered
from a plain script     -> RuntimeError: no current event loop in thread 'MainThread'.     0 delivered
```

The raise comes from `loop = asyncio.get_event_loop()` — **a variable the
function never reads.** And it happens inside `fire_alert`, while holding the
RLock, *after* the synchronous handlers have already run: a partial dispatch and
an exception, from a dead assignment, in a class whose docstring says
*"Thread-safe for concurrent access."*

`ensure_future` was the other half — not thread-safe, and the task it returned
was dropped, so a failing handler was never heard from.

Fixed with the pattern proven on D51: an optional bound loop (`bind_loop()`),
`get_running_loop()` when there is one, `run_coroutine_threadsafe` when there is
not, an explicit ERROR when no loop exists at all so an undeliverable alert is
never silent, and a done-callback that retrieves each handler's exception.

### Red before green `[VERIFIED-EXECUTED]`

Importability: `2 failed, 805 passed` → `807 passed`.
Dispatch: `4 failed, 2 passed` → `6 passed`.

**One of those two initial passes was passing for the wrong reason.**
`test_synchronous_handlers_run_with_no_loop` ran on the main thread, where an
earlier async test leaves a loop *set* (not running), so `get_event_loop()`
returned it and the test was green for a reason unrelated to the code. Both
no-loop tests now fire from a brand-new thread, which is the state a plain script
is actually in.

### The ratchet caught me

My first version of the done-callback contained `except asyncio.CancelledError:
pass`, and:

```
silent_except_handlers: 140 exceeds the ceiling of 139 by 1.
New debt of this kind was added. Fix it -- do not raise the ceiling.
```

That is the bidirectional ratchet working exactly as designed, on the person who
has spent this session building gates. Fixed by logging at DEBUG — a cancelled
handler is still an alert that was not delivered — not by raising the ceiling.

### RAR self-review

13 probes, **13/13 HOLD**. Includes a *closed* loop bound (the alert must survive),
a failing synchronous handler (must not stop the async ones), a registered
"async" handler that is not a coroutine function, and 30 threads firing
concurrently — all 30 delivered.

One probe BROKE on the first run and it was mine: `NEWDEFECT/old-apis-gone`
grepped the source of `_dispatch` for `get_event_loop()` and matched **the comment
explaining why it was removed.** Re-checked by parsing the AST for actual calls:
`{add_done_callback, create_task, error, get_running_loop, is_closed,
run_coroutine_threadsafe}` — the removed APIs are genuinely gone.

### Verification

- `tests/unit/test_every_module_imports.py` — 807 passed.
- `tests/unit/test_alerting_dispatch.py` — 6 passed, and again under a different
  test order to prove no ordering dependence.
- `tests/unit/test_architecture_fitness.py` — passed after the lazy-import fix.
- All five ratchets back at their ceilings; ruff CI selector clean; full ruff on
  the two touched files **4 findings before, 2 after** — the fix removed two.
- import-linter 7 contracts kept; un-awaited coroutine gate clean.

### Coverage & residual risk

**The alerting subsystem still has zero importers.** It now loads and dispatches
correctly, and no alert has ever been fired by this application. Making it work
is not the same as wiring it up, and this pass did not wire it up.

**`bind_loop()` must be called at startup** for off-thread firing to reach async
handlers. Nothing calls it, because nothing uses the module. When it is wired up,
that call is a prerequisite — the ERROR log says so by name.

### Uncertainty acknowledgment

**Most likely false positive:** none. All three were reproduced by execution.

**Real defect most likely missed:** the importability sweep skips
`GitNexus-main/` and `osworld/` as vendored trees with their own dependency sets.
If either is actually first-party code, it has never been checked.

**Requires runtime validation:** nothing here. CI has now failed eight
consecutive runs with the infrastructure signature.

---

## Two instruments reporting on the wrong object

**Scope.** D29 and D41. Both were recorded with the same note — *"generated and
read; not triggered within W3's / W5's budget"* — and both named a directory
rather than a site. Locating them precisely was most of the work.

### D29 — `Task.exception()` on a cancelled task `[VERIFIED-EXECUTED]`

There are exactly two `.exception()` calls in `weebot/` and `cli/`, and only one
is unguarded. `_cascade.py:463` already reads `if not pf.cancelled()` inside a
`contextlib.suppress(InvalidStateError, CancelledError)` and is correct.
`task_runner.py:142` was not.

```
unguarded form -> loop exception handler saw ['CancelledError']
guarded form   -> loop exception handler saw []
```

`Task.exception()` raises `CancelledError` when the task was cancelled, and
cancelling a session is an ordinary operation — `flow cancel <id>` is a CLI
command. So this fired on a normal path, every time.

**Severity LOW, and stated as such**: the pops above it have already run, so no
state is corrupted. The harm is that a real cleanup failure is now one more
`CancelledError` in a stream of identical ones.

### D41 — the breaker you can see is not the one that tripped `[VERIFIED-EXECUTED]`

`chat` keys the breaker on `model or self._model_name` — the **runtime** model,
so each cascade tier gets its own. That is deliberate; the comment above it says
so. But `get_circuit_state`, `get_metrics` and `reset_circuit` all read
`self._model_name`, the **construction-time** name.

Under a cascade — which is exactly what drives one adapter across several models
— eight consecutive failures on `"runtime/model"` opened its breaker, and
`get_circuit_state()` reported the configured model's, which had never been
touched. It read CLOSED while requests were being rejected.

And `reset_circuit()`, the manual recovery lever, reset a breaker that was never
open, leaving the real one closed to traffic. **The control did nothing and said
nothing.**

This is the audit's modal defect applied to an instrument: it reports on a
different object than the one being measured, and the recovery control is inert.

Fixed by remembering every key the adapter has driven; `model` is now an optional
argument on `get_circuit_state` and `reset_circuit` (default `None` keeps the old
behaviour exactly); `get_metrics` gains a `circuit_states` map **alongside** the
existing `circuit_state`, so no current reader changes; and a no-argument
`reset_circuit()` clears every key *this adapter* opened — never another
component's, which is asserted rather than assumed.

Zero external callers of all three, so nothing changes behaviour today.

### Red before green `[VERIFIED-EXECUTED]`

`7 failed, 1 passed` → `8 passed`. Worth being precise about that single pass:
of the two tests written as controls, one (`a healthy model is not reported
open`) could not run before the fix because it uses the new signature — so it is
not really a control. The genuine one is `the default key is still the configured
model`, and it is the one that passed both before and after.

### RAR self-review

15 probes, **15/15 HOLD on the first run**, no revision. Includes: an adapter
with the breaker disabled entirely; an empty `model_name`; resetting a model that
was never used; 6 models tripped concurrently then all reset; 50 simultaneous
cancellations; and a check that one adapter's `reset_circuit()` cannot clear
another adapter's breaker.

### Verification

- `tests/unit/test_breaker_key_and_cancelled_task.py` — 8 passed.
- Targeted regression (`task_runner`, `resilient`, `cascade`, `circuit`) — 116
  passed.
- All five ratchets at their ceilings; ruff CI selector clean; full ruff on the
  two touched files **13 before, 13 after**; import-linter 7 kept; un-awaited
  gate clean.

### Coverage & residual risk

**`circuit_state` in `get_metrics` is still the configured model's.** That was
deliberate — changing it would alter what an existing reader sees — so the
misleading value is still present, now beside a correct `circuit_states` map. A
future change should probably retire it, and that is a decision for whoever owns
the metrics contract, not for this pass.

**D29's guard is in one place.** Nothing prevents the next done-callback from
calling `.exception()` unguarded. Unlike the un-awaited coroutine check, this is
not gated — there are only two such call sites in the whole tree, and a gate for
a two-instance pattern is more maintenance than it is worth.

### Uncertainty acknowledgment

**Most likely false positive:** D29, on severity rather than existence. It is
real and reproduced, but it corrupts nothing; if the log noise does not bother
anyone, the fix buys little.

**Real defect most likely missed:** whether anything reads `circuit_state` from
`get_metrics` and acts on it. I found no caller, but `health.py:377` mentions
`adapter.get_metrics()` in a note, which suggests someone intended to.

**Requires runtime validation:** the cascade's actual per-tier breaker behaviour
under load. My probes drove the adapter directly rather than through
`CascadeExecutor`.

### D65 — a test that fails at random, measured but not fixed

Not my defect and not fixed, recorded because it is measured and because it is
the mirror image of this audit's thesis. An instrument that cannot fail proves
nothing; **one that fails at random proves nothing either, while training
everyone to ignore red.**

`tests/stress/test_llm_resilience.py::TestMixedFailureModes::test_partial_outage_with_retries`
injects a 50% failure rate and asserts ≥18 of 20 requests succeed.

| claim | status | evidence |
|-------|--------|----------|
| Fails ~1 run in 7 | **VERIFIED** | 6 failures in 42 isolated runs (14.3%) |
| Not caused by my changes | **VERIFIED** | 12 runs on my tree: 10/2. 12 runs with my changes stashed: 10/2. Identical. |
| The retry makes 7 attempts | **VERIFIED** | measured directly with a 100%-failing inner adapter |
| Predicted rate is 0.05% | **VERIFIED** | 0.5⁷ = 0.0078 per request; P(>2 of 20) = 0.0005 |
| Attempts are not independent trials | **INFERENCE** | 14.3% observed vs 0.05% predicted — a factor of ~280 |
| The 30s per-request timeout truncates retries under 20-way concurrency | **HYPOTHESIS** | consistent with batches exceeding 18s, but not isolated |
| The actual mechanism | **UNKNOWN** | two direct measurement attempts exceeded their own time budget and were killed |

**Deliberately not fixed.** Without the mechanism, the available moves are
widening the tolerance — which weakens the assertion — or raising the timeout,
which is a guess. An accurate record is worth more than either. If this test is
the only red when CI recovers, it is flake, not regression.

**The inventory gate corrected my bookkeeping here.** I first recorded it as
`open` with a verdict note, and
`test_open_records_have_no_verdict_note` failed: *"an `open` candidate has not
been judged, so it cannot carry a verdict."* It has been judged — investigated,
verified, and deliberately left — which is `deferred`. That is a real
distinction and the gate was right to enforce it.

---

## A tool that registers clean and answers nobody

Written after CI recovered from the eight-run Actions outage, against a live
run (`34037918394`) that exercised the previous six commits for the first time.

### D48 — the claim was wrong, the code was worse `[VERIFIED-EXECUTED]`

The recorded claim was *"dynamic tools forward unvalidated `**kwargs` to
`tool.execute()`"*. It is **refuted**. Nothing was forwarded, because nothing
ever reached `execute`.

`_wrap_base_tool` registered `async def wrapper(**kwargs)` with the MCP SDK.
The SDK derives a tool's advertised JSON Schema by introspecting the
registered function, and it does not understand `**kwargs`: it read the bare
`**kwargs` as **one required string field literally named `"kwargs"`**.

Measured on the unmodified code:

```
SCHEMA: {"properties": {"kwargs": {"title": "kwargs", "type": "string"}},
         "required": ["kwargs"], "title": "wrapperArguments", "type": "object"}
WRAPPER SIG: (**kwargs) -> 'CallToolResult'

CALL {'a': 1, 'b': 'x'}            -> ToolError: kwargs  Field required
CALL {}                            -> ToolError: kwargs  Field required
CALL {'path': '../../etc/passwd'}  -> ToolError: kwargs  Field required
```

Every call failed argument validation before dispatch — including the call
with no arguments at all. `list_tools` advertised a tool that no client could
invoke under any input. This is the ledger's shape again: registers cleanly,
reports availability, works never.

**Severity is capped by reach.** `dynamic_tools` is a constructor parameter
defaulting to `None`, and no caller anywhere in the repository passes it:

```
weebot/mcp/server.py:120:        dynamic_tools: list | None = None,
weebot/mcp/server.py:133:        self._dynamic_tools = dynamic_tools or []
weebot/mcp/server.py:181:        self._register_dynamic_tools()
weebot/mcp/server.py:251:    def _register_dynamic_tools(self) -> None:
weebot/mcp/server.py:253:        for tool in self._dynamic_tools:
```

DEAD reach, so not CRITICAL by the reachability gate. It is fixed anyway
because it is an advertised public parameter: the next caller to use it would
have inherited a facility that cannot work, with no signal saying so.

### The fix, and the approach that was ruled out first

The clean fix would be to hand the SDK an explicit schema. **It has no such
API** — this is the official `mcp.server.fastmcp`, not the third-party
`fastmcp` package, and `add_tool` takes only `fn`, `name`, `title`,
`description`, `annotations`, `icons`, `meta`, `structured_output`. Everything
else is introspected. Measured, not assumed:

```
--- add_tool ---
(self, fn, name=None, title=None, description=None, annotations=None,
 icons=None, meta=None, structured_output=None) -> None
```

So the only channel into the schema is the signature. `func_metadata` honours
a synthesized `__signature__`:

```
SCHEMA: {"properties": {"command": {...,"type":"string"},
                        "count": {"default": null, ..., "type":"integer"},
                        "path":  {"default": null, ..., "type":"string"}},
         "required": ["command"], ...}
```

`_apply_schema_signature` replays the tool's own `.parameters` — which every
`BaseTool` already carries as a JSON Schema object — as a keyword-only
signature. Optional parameters are given a `None` default and then stripped in
the wrapper, so `execute(**kwargs)` sees exactly what the client sent. That is
not a new convention: `_run_file_tool`'s own callers at lines 454-463 already
build kwargs by omitting optional keys rather than passing `None`.

### Red before green `[VERIFIED-EXECUTED]`

`tests/unit/interfaces/test_dynamic_mcp_tools_are_callable.py`, 19 tests:

```
pre-fix  (git stash push -- weebot/mcp/server.py):  18 failed, 1 passed
post-fix:                                                    19 passed
```

### RAR self-review

| vector | probe | result |
|---|---|---|
| Boundary | tool with `properties: {}` | `ok:{}` — callable with no args. HOLD |
| Boundary | `properties` is the string `"not-a-dict"` | degrades to a no-arg tool, no crash. HOLD |
| Boundary | schema is `None` / `"a string"` / `[]` / `42` / `{}` | empty signature, no raise. HOLD |
| Invalid input | required arg omitted | rejected, naming `command`. HOLD |
| Invalid input | `count="not-an-int"` | rejected, naming `count`. HOLD |
| Invalid input | `path=None` on a `"type":"string"` param | rejected — schema-correct; the tool declared a string. HOLD |
| Invalid input | property named `bad-name` / `class` | dropped, WARNING names both. HOLD |
| State | omitted optional | arrives **absent**, not as `None`. HOLD |
| Regression | tool returns `is_error` | `isError=True`, text `"boom"` — contract unchanged. HOLD |
| Concurrency | n/a — registration is synchronous and per-instance | not applicable |
| New defect | undeclared arg `zzz` | dropped by the SDK, never reaches `execute`. HOLD |

Six vectors, no BREAKS, no revision needed.

### Verification

| gate | result |
|---|---|
| `ruff check weebot/ cli/ --select F821,E9` | All checks passed |
| `make lint-unawaited` | clean, 821 files |
| `lint-imports` | 7 kept, 0 broken |
| `silent_except_handlers` | 139, at ceiling |
| `blocking_io_in_async` | 29, at ceiling |
| `print_in_production` | 143, at ceiling |
| `bare_env_reads` | 73, at ceiling |
| `bandit_b110` | 68, at ceiling |
| candidate inventory | 11 passed |

### Coverage & residual risk

What this does **not** cover:

- **A parameter name that is not a Python identifier still cannot be passed.**
  `bad-name` and `class` are dropped from the signature. They are named at
  WARNING rather than dropped silently, but a tool declaring them is still
  partially unreachable. Fixing that needs an SDK that accepts an explicit
  schema; this one does not.
- **`Any` is the fallback annotation** for an unrecognised or absent JSON
  Schema `type`. That accepts the value as-is rather than rejecting one the
  tool would have handled — deliberately permissive, since the alternative is
  rejecting valid input.
- **Nested object/array schemas are flattened to `dict`/`list`.** A tool
  declaring `{"type":"object","properties":{...}}` for one parameter gets
  `dict` — the inner shape is not validated.
- **Still DEAD reach.** Nothing in the repository registers a dynamic tool, so
  none of this executes in production today. The tests are the only caller.

### Uncertainty acknowledgment

The claim on record was wrong, and I did not find that by reading — the static
reading ("`**kwargs` is unvalidated") is a perfectly natural one, and it is
what I would have written too. It survived until a probe called the tool and
watched every call fail before `execute`. **UNKNOWN:** whether other refuted
claims in this inventory hide different defects in the same lines. D48 is one
data point, not a rate.


---

## The verifier that ran the command it was verifying

### D8 — the one shell-execution site, and what it did `[VERIFIED-EXECUTED]`

The recorded claim was narrow: *"raw `create_subprocess_shell` outside the
bash-guard path."* True, and an understatement.

The recorded location no longer existed — the file had moved from
`weebot/application/services/` to `weebot/infrastructure/security/` — but line
501 still matched. It was the **only** shell-execution site in `weebot/` or
`cli/`:

```
create_subprocess_shell : 1
shell=True              : 0
os.system               : 0
```

`verify_command_execution` took an agent's *claim* that it had run a command
and, for anything it judged critical, **re-ran that command** and compared
return codes. Measured on the unmodified code:

```
marker exists before verification: True
marker exists AFTER verification:  False
verification status: CONTRADICTED
```

Given a claim about `rm -f <marker>`, the verifier deleted `<marker>`, then
reported the claim CONTRADICTED — because the second run's return code
differed from the first. Both halves wrong: it caused the effect, then called
the agent a liar for it.

Three further defects sat in the same branch.

**Classification was substring matching.** `op in command_lower`, over a set
containing `rm`:

| command | critical? | BashGuard |
|---|---|---|
| `npm run format` | **True** — `rm` ⊂ `format` | safe |
| `echo confirm` | **True** — `rm` ⊂ `confirm` | safe |
| `terraform apply` | **True** — `rm` ⊂ `terraform` | safe |
| `ls -la` | False | safe |
| `rm -rf /` | True | **blocked** |
| `curl -X POST .../charge` | True | safe |

Every `True` in that column was re-executed. `rm -rf /` is the exact command
BashGuard exists to stop, and this path never consulted BashGuard —
CLAUDE.md rule 3 had no enforcement anywhere in the repository.

**And the handler failed open.** When re-execution raised, it logged a warning
and fell through to `VERIFIED` at `confidence_score=0.9`. The verifier that
could not verify reported success at 90% confidence.

**Reach is DEAD.** `StateVerifier` has no importer in `weebot/`, `cli/`,
`tests/` or `scripts/`; `get_state_verifier()` is never called. None of this
ran. Severity is capped accordingly — but the module is named for security,
and a future caller would have inherited all four defects at once.

### The fix, and the approach that was rejected

The obvious fix is to route the command through `BashGuard` before re-running
it. **That is not sufficient**, and the table above says why: `curl -X POST
.../charge` is guard-SAFE and would still be replayed, as would `terraform
apply`. Guarding a re-execution makes it survivable, not correct.

The unsoundness is prior to the guard: **re-executing a command does not
observe the earlier run.** It performs a second one, and for anything that
mutates state that second run *is* the harm the check exists to catch. There
is no version of "run it again" that verifies a past side effect.

So the branch does not re-execute. A critical claim now returns
`UNVERIFIABLE` at confidence `0.0` — a status the enum already had — with the
reason stated in `discrepancies`. `_execute_verify_command` is deleted, which
takes the codebase's shell-execution surface to zero and lets the new gate sit
at a ceiling of zero rather than a ratchet.

### Red before green `[VERIFIED-EXECUTED]`

```
tests/unit/infrastructure/security/test_verification_does_not_re_execute.py
  pre-fix   6 failed, 7 passed      (the 7 are the genuinely-critical
                                     classifications, correctly unaffected)
  post-fix  13 passed

test_architecture_fitness.py -k shell
  pre-fix   1 failed
            E  weebot/infrastructure/security/state_verifier.py:501: create_subprocess_shell
  post-fix  1 passed
```

The gate was also proven against all three forms it claims to catch, and
proven *not* to flag the safe one:

```
E  weebot/_gate_probe_tmp.py:2: create_subprocess_shell
E  weebot/_gate_probe_tmp.py:3: os.system
E  weebot/_gate_probe_tmp.py:4: run(shell=True)
   subprocess.run(["echo", "hi"])   — not flagged
```

### RAR self-review

| vector | probe | result |
|---|---|---|
| Boundary | claim about a command with no critical verb | unchanged path, still VERIFIED. HOLD |
| Invalid input | `echo 2 > f && chmod 600 f` (non-idempotent) | file unchanged at "1". HOLD |
| State | marker file present before and after | present. HOLD |
| State | status/confidence on a declined claim | UNVERIFIABLE / 0.0 / `is_trusted` False. HOLD |
| Regression | `rm -rf /`, `git rm`, `chmod 777`, `kill 123` | all still classified critical. HOLD |
| Regression | `terraform apply`, `echo confirm`, `ls -la`, `cat notes.txt` | all now non-critical. HOLD |
| Concurrency | n/a — no shared state introduced; a method was removed | not applicable |
| New defect | ruff `F401` on the module after deleting the helper | clean; `asyncio` still used by `_read_file_async`. HOLD |

Six vectors, no BREAKS.

### Coverage & residual risk

- **`format` is still classified critical**, because it is literally in
  `_CRITICAL_OPERATIONS` — word boundaries cannot fix a list containing a word
  that is also a common build target. The cost of that false positive dropped
  from *re-executing a command* to *reporting UNVERIFIABLE*, which is why it is
  left alone rather than guessed at.
- **The module is still dead.** Nothing imports it. These tests are its only
  caller, and they are the only thing keeping it honest.
- **The gate covers `weebot/` and `cli/` only** — not `scripts/`, not `tests/`,
  where a shell call may be legitimate tooling.
- **`create_subprocess_exec` is not gated.** It takes an argument list and
  spawns no shell, so it does not carry the metacharacter risk; it is a
  different question from this one and was not folded in.

### Uncertainty acknowledgment

The claim was recorded in W1 and deferred twice, through W7 and again in this
run, on the reading that a lone `create_subprocess_shell` in dead code was low
value. That reading was right about the reach and wrong about everything else:
the interesting defect was not the missing guard but what the guarded call
*did*. **UNKNOWN:** whether the other narrow claims still deferred are
similarly under-described. Reach was the reason for deferring each of them,
and reach turned out to be the least informative thing about this one.


---

## Two gates that asked a question and ignored the answer

### D12, D67 — the resume path never read the reply `[VERIFIED-EXECUTED]`

The recorded claim was that the inbound-mail approval flag is cleared before
the pause. **Refuted, and the clearing is required**: `FlowRouter` flips
WAITING → RUNNING and re-enters `execute()` against the same step, so an
uncleared flag re-fires the gate forever. The constraint gate below it carries
a comment saying exactly that.

W1 marked the *resume* path `[UNK]` and never triggered it. That is where the
defect was.

`resolve_initial_state` routed on three things. `_product_gate_pending`
forwarded the prompt to `ProductGateState(resume_with=prompt)`.
`plan_pending_approval` tested it against `_APPROVE_TOKENS`. Everything else
reached:

```python
if last_plan is not None and not last_plan.is_complete():
    return ExecutingState(), session
```

which never reads `prompt`. Neither gate set a routing flag, so both landed
there. Both prompts say *"type 'proceed' to continue, or describe how you'd
like to handle it"* — and **neither half was honoured**. The description was
discarded, and no answer declined. Typing `"that email is a phishing attempt,
ignore it"` resumed execution on the untrusted content identically to typing
`proceed`, which is the one thing ADR 006 exists to prevent. The constraint
gate had the same hole, so a user answering "no, do not do that" got the step
executed anyway (**D67** — not previously recorded; found in the code
immediately below D12).

### Why the flag could not simply be the one already there

`set_fact` writes to `context.facts`. `SessionContext.get` reads declared
fields and then `context.extra`, and **never** `context.facts`. So the gates'
own pending flags were invisible to the router by construction. A test pins
this in both directions, because it is the reason the fix needs a second flag
rather than reusing the first.

### The semantic choice, which was the user's

What a non-approval should *do* is a product decision, not a defect, so it was
escalated rather than guessed. Green-lit, it follows the codebase's own
precedent for the identical situation: the plan-approval path re-plans with
the response as a modification request. Both gates now do that.

**One deliberate divergence.** The plan-approval path treats an empty response
as approval (`if response in _APPROVE_TOKENS or not response`). These gates do
not. They guard untrusted input and stated constraints, and silence is not
consent.

### A short-circuit written and then removed

The first version returned `ExecutingState` directly on approval. A test
caught it doing so for a session with **no plan to execute** — a state the
router could not previously produce, because every path to `ExecutingState`
checks `last_plan is not None and not last_plan.is_complete()` first.
Approval now clears the flag and *falls through* to those branches. Approval
means "carry on as before", and the code below already knows what "as before"
is.

### Red before green `[VERIFIED-EXECUTED]`

`tests/unit/application/flows/test_user_gate_answer_is_honoured.py`, 33 tests,
every case parametrised over both gates:

```
router reverted:  30 failed, 3 passed
with the fix:              33 passed
```

The 3 that pass either way are the two flag-visibility tests and the
no-gate-pending regression — correctly unaffected by a routing change.

### RAR self-review

| vector | probe | result |
|---|---|---|
| Boundary | `""`, `"   "`, `"\n"` | not approval; re-plans. HOLD |
| Boundary | `"  PROCEED  "` | approval; case and whitespace tolerated. HOLD |
| Invalid input | `"no"`, `"stop"`, a free-text instruction | re-plans, instruction carried. HOLD |
| State | flag consumed after either answer | `_user_gate_pending` is None. HOLD |
| State | second resume after an answered gate | does not re-route; no livelock. HOLD |
| Regression | WAITING + incomplete plan, no gate flag | still `ExecutingState`, still RUNNING, no modification request. HOLD |
| Regression | `set_fact` vs `extra` visibility | pinned both ways. HOLD |
| Concurrency | n/a — routing is synchronous, per-resume, on an immutable Session | not applicable |
| New defect | approval with no plan attached | falls through instead of short-circuiting. Found by test, fixed. HOLD |

Nine probes, one BREAK (the short-circuit), revised once, re-run: all HOLD.

### Coverage & residual risk

- **A non-approval always re-plans.** For the constraint gate that is a
  heavier response than "skip this step and continue", which may be what a
  user means. Re-planning is the codebase's existing answer to "user did not
  approve"; a lighter one would be a new behaviour, not a defect fix.
- **`_APPROVE_TOKENS` is a fixed word list.** "yes please" is not in it and
  re-plans. Erring toward re-planning is the safe direction at a gate, but it
  will occasionally re-plan when the user meant to approve.
- **The constraint gate's per-step ack survives a decline.** If re-planning
  produces a step with the same id, its gate will not re-fire. Narrow, and not
  exercised here.
- **Not covered end to end.** These tests drive `resolve_initial_state`
  directly. A full pause-then-resume through `PlanActFlow` against a live
  inbox is not exercised, and the atomic_mail path needs
  `WEEBOT_ENABLE_ATOMIC_MAIL=1`.

### Uncertainty acknowledgment

W1 recorded the wrong claim and marked the right area unknown. The claim it
did record — that clearing the flag is a bug — is not merely unproven, it is
backwards: removing the clear would livelock the gate. The defect was one
layer further out, in a function the claim never names. **UNKNOWN:** how many
of the remaining `[UNK]` markers sit next to a refuted claim in the same way.
Two of the last three defects closed had a refuted claim attached (D48, D12),
which is a pattern worth more than the two data points establish.


---

## The pause that never reached the database

### D69 — a shipped fix that did not run `[VERIFIED-EXECUTED]`

The previous entry reduced this rather than chasing it: the routing flag and
the WAITING status are set on the same immutable session one line apart, so
whatever persists one persists the other, and the flag's durability is
therefore the gates' pre-existing durability. That reasoning was sound and
its premise was false. **Nothing persisted.**

Measured against a real `SQLiteStateRepository`:

```
IN-MEMORY   status=waiting  gate='inbound_mail'  mail_pending=False
IN DB       status=pending  gate=None            mail_pending=True
DB event types: ['plan']          <- the WaitForUserEvent never landed
```

Every path traced: `event_publisher._persist_session` is reachable only from
`emit()`, and the gates `yield`; `PlanActFlow.run()` has no `save_session`
anywhere; `AgentRunner`'s post-loop save never runs, because
`cli/commands/flow.py` breaks the `async for` on the `WaitForUserEvent` and
post-loop code in a generator is skipped; the gateways call `save_session`
zero times. Only `TaskRunner._run_flow` persisted.

Three consequences, all measured:

1. `weebot flow run` raised `ValueError: Session ... is not waiting` on the
   user's answer.
2. Both gates re-fired on every resume, **unboundedly** — each turn builds a
   fresh flow, so `max_iterations` cannot bound it.
3. The D12/D67 Priority-2 branch was unreachable on any DB-mediated resume.
   **ADR 006 did not hold in production**, for the four hours it was merged.

### Why 41 green tests missed it

Every test for these gates drives `ExecutingState` or
`resolve_initial_state` in memory and asserts on `ctx._session`. None crossed
the seam the feature depends on. The unit test was green and the feature was
dead; that is the whole finding, and the fix is worth less than the test that
now guards it.

### The test was wrong first, in the same way

The first draft of `test_gate_pause_survives_the_seam.py` built its context
from a `SimpleNamespace`. It took the in-memory fallback and proved nothing —
reproducing, inside the test written to catch the defect, the exact mistake
that hid it. The warning fired and gave it away:

```
WARNING Flow SimpleNamespace has no _pause_for_user; pausing in memory only.
```

It now drives a real `PlanActFlow`, and its `_context` helper says in a
docstring why it must never go back to a stub.

### The fix, and the gate that shaped it

`collaborators/user_pause.py` holds both halves of the contract:
`pause_flow_for_user` sets WAITING, emits **once** (`EventPublisher.emit`
already calls `add_event`, so `PlanReviewState` adding *and* emitting writes
the pause twice), then persists authoritatively and lets a failed write raise
rather than downgrade to a warning — a pause that cannot be saved will not
survive, and that is the failure this exists to prevent. `pause_for_user` is
the gate-side shim; a context without the contract still pauses in memory and
says so at WARNING.

Both halves live in one module so a future gate cannot implement one and
forget the other — which is precisely how this arose. The two gates copied a
pause that set WAITING and yielded, from a state (`PlanReviewState`) that also
persisted, and whose comment explains exactly why it has to.

**`test_god_modules_under_800_lines` fired on the first attempt** —
`plan_act_flow.py` at 1023/1000 and `executing.py` at 820/800. The ceiling was
not raised. That gate is the reason the logic is a collaborator rather than
two inlined methods, and the result is better than what it rejected.

### Red before green `[VERIFIED-EXECUTED]`

```
pre-fix source:   5 failed, 1 passed
with the fix:              6 passed
```

The one that passes either way is the no-repository case, which is correct:
a sub-agent flow with `_state_repo=None` must still pause, just not durably.

### RAR self-review

| vector | probe | result |
|---|---|---|
| Boundary | `_state_repo=None` | still pauses, WARNING names the loss. HOLD |
| State | reload status after the mail gate | WAITING in the DB. HOLD |
| State | reload `_user_gate_pending` | `'inbound_mail'`. HOLD |
| State | reload the cleared `atomic_mail_inbound_pending` | falsy. HOLD |
| State | reload after the constraint gate | WAITING, `'constraint'`, ack present. HOLD |
| Invalid input | pause event count in the transcript | exactly 1, not 2. HOLD |
| Regression | the 41 existing gate/router tests | all pass unchanged. HOLD |
| Regression | `test_god_modules_under_800_lines` | fired, then satisfied by extraction. HOLD |
| Concurrency | n/a — one pause per state entry, on an immutable session | not applicable |

### Coverage & residual risk

- **`PlanReviewState` still double-adds.** It was the model for the fix and
  keeps its own defect; folding it onto `pause_flow_for_user` is a separate,
  safe change not made here.
- **The fallback is still a fallback.** A production flow type that fails to
  implement `_pause_for_user` pauses non-durably and only warns. The seam test
  covers the real path; nothing forces a *new* flow type through it.
- **The HITL branch at `executing.py:510-525` was not converted.** It sets
  WAITING and returns without yielding a `WaitForUserEvent`, so it is a
  different shape; it has the same durability gap and is not fixed here.
- **Only the CLI path is proven.** The gateways still call `save_session` zero
  times; whether they resume correctly is untested.

### Uncertainty acknowledgment

I reduced this defect away once, with an argument I still think was well
formed, and shipped a fix that did not run. The premise I did not test —
"the pre-existing persistence works" — was the whole question. **UNKNOWN:**
how many other conclusions in this audit rest on an untested premise about a
neighbouring mechanism. The rate at which recorded claims have proven wrong
in this backlog (nine of sixteen) suggests the answer is not zero.


---

## The region that was named and never opened

### R6 — secret classification and event sanitisation `[VERIFIED-EXECUTED]`

W1 recorded two candidates, D9 and D10, against "region R6" and never wrote
down a claim for either. They sat `open` through eight waves because there was
nothing to confirm. Opening the region found the most severe unshipped
defects in this backlog.

### R6-C5 — sanitisation covered the one field the human types

All **three** emit pipelines carried the same gate:

```python
isinstance(event, MessageEvent) and event.role == "user"
```

So a credential was scrubbed only when the *human* typed it. Everything the
agent produced went out raw — above all `ToolEvent.result`, which is tool
stdout, and therefore the output of `cat .env`, `env` or `git remote -v`. That
reached the event bus, the WebSocket broadcast to the web UI, and SQLite,
while `EventPublisher`'s own docstring listed credential sanitisation as an
unconditional pipeline stage.

Also uncovered: `ErrorEvent.error`, `StepEvent.description`,
`WaitForUserEvent.question`, and an **assistant** `MessageEvent` — the model
echoing back a key it had just been shown.

Three copies of the gate now collapse to one `sanitize_event()` in core that
knows which fields of each event type carry free text.

### R6-C3 — one rule, two copies, and the copies drifted

Measured, both forks on the same input:

```
core.sanitize      : auth failed for ***REDACTED-API-KEY***
adapter._sanitize  : auth failed for sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAAAA
```

`resilient_adapter`'s character class is `sk-[a-zA-Z0-9]{20,}` — no `-`, no
`_` — so it fails at the third character of every Anthropic key, while
`weebot/core`'s `sk-[a-zA-Z0-9_-]{20,}` catches it. Neither copy is tested
against the other's inputs, which is what makes R2 invisible. The fork is
deleted; the adapter calls core.

### R6-C4 — the live sanitiser was thinner than the dead one

Each of these passed through `sanitize()` unchanged:

```
LEAK   GitHub PAT      ghp_16C7e42F292c6912E7710c838347Ae178B4a
LEAK   Google API key  AIzaSyD-1234567890abcdefghijklmnopqrstu
LEAK   Slack bot       xoxb-...-...-...   (truncated: push protection)
LEAK   Basic auth      Authorization: Basic dXNlcjpwYXNzd29yZA==
```

The **dead** `SecretRedactor` has a Bearer rule. The live one did not.

**And a defect found only by writing the test.** The JWT pattern required 20+
characters after `eyJ` in the header segment, so whether a JWT was redacted
depended on its header's *length*:

```
header {"alg":"HS256"}                  -> 17 chars after eyJ   LEAK
header {"alg":"HS256","typ":"JWT"}      -> 33 chars after eyJ   REDACTED
```

Both are ordinary headers. My first test case happened to use the short one
and failed; the correct response was to fix the pattern, not the test. The
`eyJ` prefix plus three base64url segments was always the specificity — the
length was never doing that work.

### R6-C2 — a sanitiser that cannot reach a computed message

`_sanitize_error` rewrites `exc.args[0]`, which does nothing for an exception
whose `__str__` is computed from stored state — i.e. every httpx/openai
wrapper:

```
after sanitise: GET failed https://api.x/v1?api_key=sk-abcdefghij0123456789XY
```

The exception type cannot be swapped, because `ErrorClassifier` keys retry
decisions off it. `sanitized_message(exc)` is the honest escape hatch: callers
that log the text rather than the object are safe whatever the shape.

### Red before green `[VERIFIED-EXECUTED]`

```
pre-fix:  ImportError: cannot import name 'sanitize_event'
          plus, behaviourally: LEAK GitHub / Google / Slack / JWT(short hdr)
post-fix: 22 passed
```

### Deliberately not fixed, and the order that forces it

`SecretRedactor` is 184 lines with **zero callers**, while `settings.py`
declares `secret_redaction_enabled: bool = True`, described as redacting
secrets "in tool output and logs". The configuration reports a control that
has never run.

It is not wired in here, because it is broken in two ways that only matter
once it runs: `redact()` collapses every newline and tab and redacts any 3–4
digit integer as a CVV (`port 8080` → `port [CVV_REDACTED]`), and
`redact_dict` skips non-`str` scalars, dict keys, and anything below one list
level while presenting the result as sanitised. **Wiring C1 before fixing
C7/C8 would ship a log-corruption bug on the same commit.** Order: C5 →
C3/C4 → C7/C8 → C1.

`R6-C6` is also deferred, for a different reason: the `*_URL` / `*_HOST`
allowlist is a deny-by-shape heuristic used as an allow rule, and
`tests/unit/test_secret_accessor.py:98` currently *asserts it is correct*.
Changing it means overruling a test that encodes the defect as the contract —
a judgement about intent, not a repair. Mitigated meanwhile: C4's new
URL-credential pattern redacts `scheme://user:pass@host` even though the
classifier still calls the key non-secret.

### Coverage & residual risk

- **Sanitisation is field-driven.** A new event type with a free-text field
  gets no coverage until it is added to `_SANITISED_EVENT_FIELDS`. Nothing
  enforces that; a fitness test asserting every `str` field of every event
  type is either listed or explicitly exempted would.
- **`function_args` is not sanitised.** A `ToolEvent` carries its arguments as
  a dict, and a credential passed *into* a tool sits there. Only `result` is
  covered.
- **Patterns are a denylist.** Everything in this region is; a token shape
  nobody anticipated still leaks. The entropy check in the dead redactor is
  the only non-denylist mechanism in the codebase, and it remains unwired.

### Uncertainty acknowledgment

D9 and D10 were the last two `open` records and the easiest to leave alone,
because a candidate with no claim cannot be refuted and therefore never looks
urgent. They were also the only two pointing at a security region no wave had
finished. **The ranking heuristic that kept them last — "unspecified means
low value" — was exactly backwards here**, and I do not know whether that is a
one-off or a property of how this inventory was ordered.


---

## Three routing tables, none of them running

### S5 and D70 — resolved by deletion `[VERIFIED-EXECUTED]`

S5 claimed two declared transition tables were dead code. There were **three**:

| table | callers |
|---|---|
| `state_graph.py::build_default_state_graph` | 0 (reached only via the dead `FlowRouter._get_graph`) |
| `flow_state_machine.py::_TRANSITION_TABLE` | 0 |
| `FlowSerializer.to_langgraph` | 0 — a hardcoded 4-node description of a 13-state machine |

Against them: **45** `context.set_state(...)` calls and one if/elif chain,
which is what actually ran. `FlowRouter._route_product_gate` and
`_route_plan_approval` existed only to feed the graph.

### Why this was not merely dead weight

D70 recorded that the graph lacked the user-gate transition and the
WAITING→RUNNING flips. A differential over 14 sessions found **six**
divergences, not two, and three of them are security-relevant:

| case | live router | the graph |
|---|---|---|
| gate + **declining** answer | `PlanningState`, refusal honoured, acks cleared, mail gate re-armed | **`ExecutingState`** — the whole ADR 006 refusal path vanishes |
| gate + **empty** answer | `PlanningState` (silence ≠ consent) | **`ExecutingState`** — silence becomes consent |
| gate + approving answer | flag cleared | **flag left set** — re-fires on every resume |
| plan-approval decline | RUNNING | **WAITING** — the run loop breaks |
| `ProductGateState(resume_with=prompt)` | expressible | **not expressible** by a name-returning factory |

The claim's "lacks the flips" was 2/3 right: the graph does have one of them.

### The script that reported success while corrupting the file

`scripts/wire_stategraph.py` existed to swap the live table for the dead one.
Run against a copy of the tree:

```
StateGraph wired into FlowRouter.resolve_initial_state()
--- EXIT CODE: 0 ---
did it wire anything?      graph.resolve occurrences: 0
duplicated the import?     1 -> 2
duplicated _get_graph?     1 -> 2
```

Its third `str.replace` no longer matches, because `resolve_initial_state`
grew the `_user_gate_pending` branch since the script was written, and
`str.replace` returns its input unchanged on no match. The script never
verifies. So it prints success, wires nothing, and duplicates two blocks — a
tool with the same failure mode as the tables it was written to install.

### The approach chosen, and the two rejected

**Wiring the graph** was rejected: highest blast radius (the resume path for
every session), the six divergences are a prerequisite work list, and
`ProductGateState(resume_with=prompt)` cannot be expressed at all. Its
`resolve` also swallows `AttributeError`/`KeyError` per transition, which
would silently downgrade a routing bug to "fresh planning" and discard a live
plan.

**A conformance test** asserting the table matches the router was rejected
too: it pins current behaviour *including* the shared `extra`-wipe bug, and a
dead table with a green test is more misleading than one without.

**Deletion** — 359 lines across three files, plus `_get_graph`,
`_state_class_map`, both `_route_*` helpers and `to_langgraph`. Removing
unreachable code cannot change behaviour, and it removes the class rather than
one instance.

### The gate `[VERIFIED-EXECUTED]`

`test_there_is_exactly_one_flow_routing_table` fails if any of the three files
returns. Proven by recreating `state_graph.py`:

```
E  weebot/application/flows/state_graph.py (declarative transition table)
1 failed
```

A second table is only safe when something proves the two agree. Nothing did,
and this gate does not ask for one — it asserts the alternatives stay deleted.

### Coverage & residual risk

- **The docs still describe a declarative machine.** ADRs and module
  docstrings elsewhere may reference a design that no longer exists; only the
  `flow_serializer` docstring example was updated.
- **45 `set_state` calls remain the routing authority**, and they are
  scattered across sixteen state classes. That is the actual architecture; it
  is not more legible for the tables being gone, only more honest.
- **Nothing prevents a *fourth* representation** in a differently-named file.
  The gate names three specific filenames, which is what makes it cheap and
  also what bounds it.

### Uncertainty acknowledgment

S5 sat `open` for five waves with the note "dead code — low value". The
reading was right about reach and wrong about risk: the live artefact was not
the tables but the script that would install them, and that script had already
drifted into corrupting the file. **UNKNOWN:** how many other "dead code, low
value" dismissals in this inventory have a live tool or script attached to
them that nobody looked for.


## The race that threw away the answer it had paid for

### D39 — orphaned probes on `FIRST_COMPLETED` `[VERIFIED-EXECUTED]`

D39 sat `deferred` for five waves as "unbounded spend" — a cost defect, ranked
Priority 3. The measurement says the money was the *smaller* half.

`CascadeExecutor.call_with_cascade` fans out Phase 1 probes and takes the first
future to complete. Cancellation of the losers lived **inside** the
`resp is not None` branch:

```python
done, pending = await asyncio.wait(tasks.keys(), return_when=asyncio.FIRST_COMPLETED)
for fut in done:
    resp = fut.result()
    if resp is not None:
        for pf in pending:
            pf.cancel()
        ...
        return resp
# ← first-completed was a failure: falls through with `pending` still running
```

So the branch where the first future to finish is a **failure** fell through to
Phase 2 with every other probe alive.

### Why that is the common path, not the rare one

Two properties of the surrounding code make the failure branch the *likely*
one, and both are in the file:

- `_cascade_try_chat` returns `None` for every failure and never raises, so a
  failure is indistinguishable from a slow success at the `asyncio.wait`
  boundary — it is just a future that completed;
- a 429 or 503 comes back in ~200ms, against seconds for a real completion.

The fastest probe to return is therefore preferentially the fastest *rejection*.
The defect does not need an unlucky day.

### What it cost, measured

Five probes, the fastest failing, two slow ones succeeding:

| | pre-fix | post-fix |
|---|---|---|
| requests sent | 5 | 5 |
| completions billed | **5** | 3 |
| cancelled | **0** | 2 |
| probes that succeeded | **2, both discarded** | 1, returned |
| result | `AllModelsTrippedError` | the successful response |

Two probes had **succeeded**. Their responses were dropped on the floor and the
cascade went on to buy the answer again on a higher tier. The spend is the part
that shows up on an invoice; the part that does not is that a cascade holding a
valid completion reported total failure.

### The drain loop under the cancel was a no-op

```python
for pf in pending:
    if not pf.cancelled():
        with contextlib.suppress(asyncio.InvalidStateError, asyncio.CancelledError):
            pf.exception()
```

`pf.cancelled()` is still `False` immediately after `cancel()` — cancellation
is delivered on the next loop iteration, not synchronously — so the guard
always passed. `pf.exception()` on a task that is not done raises
`InvalidStateError`, which the `suppress` swallowed. The loop retrieved nothing
and suppressed nothing that mattered. It read as care and did no work: the same
shape as the gates in the section above.

### The fix, and what it trades

Harvest until a probe **succeeds**; cancel the rest in a `finally` so it runs on
every exit, bounded rather than gathered:

```python
finally:
    for pf in pending:
        pf.cancel()
    if pending:
        await asyncio.wait(pending, timeout=5.0)
```

`asyncio.wait(..., timeout=5.0)` rather than `gather`: an adapter that swallows
`CancelledError` would otherwise hang the cascade forever on the cleanup path.

**The trade is real and worth stating.** Waiting for a success costs latency
in exactly the case that used to return fast — worst case the slowest probe's
90s cap instead of the fastest probe's return. That is p99 spent to avoid a
further paid call plus another round-trip, which is the better side of the
trade, but it is not free.

### Two asyncio facts the fix rests on, both `[VERIFIED-EXECUTED]` by probe

- A pending task left uncancelled **runs to completion**. It does not stop
  because nobody is awaiting it — which is why the orphans billed.
- `asyncio.shield` **defeats cancellation entirely**. The fix is sound only
  while nothing between here and the HTTP call shields it. Nothing does today;
  a future `shield` would silently restore the defect.

### The gate

`tests/unit/agents/test_cascade_does_not_bill_orphans.py`, three tests, and the
harness took three attempts to become honest — worth recording, because each
failure produced a *green* test that proved nothing:

1. The fake LLM defaulted unknown models to a fast success, so the role
   cascade's own default models won every race. The test measured them, not
   the probes.
2. `get_model_cascade_for_role` was patched on `_cascade`, but `_cascade`
   imports it *inside* the method, so it never becomes an attribute there. The
   patch bound nothing.
3. Worst: the successful model landed in `role_fallback2`, which is Phase **2**,
   outside the parallel set — so Phase 2 rescued it and the test passed against
   the unfixed code. Fixed by making the role cascade a single never-succeeding
   model, every tier constant that same model, and supplying the probes through
   the ACR list, so Phase 2's candidates are all already in `parallel` and it
   has nothing to rescue with. A success can then only come from Phase 1.

Only after (3) did red-before-green discriminate:

```
=== RED first, before believing anything ===
FAILED ...::test_a_slow_success_is_used_instead_of_escalating
1 failed, 2 passed
=== then GREEN ===
3 passed
```

The other two tests are labelled in the file as what they are: a **regression
guard** for the success path, which already cancelled its losers and passes
against the unfixed code, and a terminal-state check that also passes unfixed
(when every probe fails they all finish on their own, so there is nothing to
orphan). Test 3's first assertion filtered `asyncio.all_tasks()` by
`"chat" in repr(t)`, which never matches a task's repr — vacuous, and it would
have passed with probes still running. Replaced with `started` vs
`completed | cancelled` accounting and proven non-vacuous by injecting an
unaccounted probe.

### Coverage & residual risk

- **Cancelling does not provably zero the spend.** It aborts the request
  client-side; tokens the provider has already generated may still bill. The
  claim is *reduces*, not *eliminates*.
- **`estimate_cost()` returns `0.0` for most reachable models**, so this saving
  will not appear in the cascade's own telemetry. That is a separate open
  defect; it does not affect the fix, only the ability to *see* it in
  production. (It does not affect the proof either: the test counts requests
  and cancellations directly.)
- **Phase 2 is untouched.** It is sequential, so it has no orphan class — but
  it also has no harvest, and a Phase 2 model that fails still burns its call.
- **The 5s cleanup bound is a guess.** It is long enough for a cooperative
  adapter and short enough not to hang the cascade; nothing measured what a
  real adapter takes to honour a cancellation.

### Uncertainty acknowledgment

D39's recorded claim — "orphaned probes keep running and billing" — was true
and *understated the defect by a category*. Ranked as spend, it was really a
correctness defect: the cascade returned failure while holding a success. The
record had the mechanism right and the consequence wrong, which is exactly the
kind of entry a priority-ordered work list will keep deferring. **UNKNOWN:**
how many other `deferred` entries in this inventory are mis-categorised the
same way — a real consequence hiding under a cheaper-sounding label.

## Four retry loops, none of them aware of the others

### D44 — the claim was half wrong, and the region was much worse `[VERIFIED-EXECUTED]`

D44 read: *"No client HTTP timeout on any concrete adapter; the only timeout is
the cascade's own."* Both halves needed correcting before anything could be
fixed.

**The second half is false.** `ResilientLLMAdapter._execute_with_timeout` has
always wrapped the inner call in `asyncio.wait_for(..., timeout=self._timeout)`,
and the factory computes a per-provider budget (60/90/120/180s) and passes it
in. The cascade's is not the only timeout; it is the third of three.

**The first half is true of the code and misleading about the behaviour.** No
concrete adapter passes `timeout=` to its SDK client — but neither SDK is
timeout-free. Measured:

```
anthropic 0.117.0  Timeout(connect=5.0, read=600, write=600, pool=600)
openai    2.54.0   Timeout(connect=5.0, read=600, write=600, pool=600)
```

Ten minutes of read budget under a 60-second adapter. That is a mismatch worth
fixing, but it is not "no timeout", and a fix aimed at the claim as written
would have addressed the smaller problem.

### What is actually there

Four layers, each of which multiplies the next, and none of which knows the
others exist:

| layer | multiplier | where |
|---|---|---|
| `CascadeExecutor` Phase 1 + 2 | ~5 models | `_cascade.py` |
| `RetryWithBackoff` | **7** attempts (`len(delays) + 1`) | `ResilientLLMAdapter` |
| a model chain of the adapter's own | **10** models | `OpenAIAdapter.chat` |
| SDK `max_retries` | **3** attempts (default 2) | openai / anthropic |

Measured on one logical `chat()` against a transport answering 429 to
everything:

| model shape | pre-fix | post-fix |
|---|---|---|
| `z-ai/glm-5.2` — has a `/`, so the chain is all ten | **210** requests | 7 |
| `gpt-4o-mini` — no `/`, one-entry chain | **42** requests | 7 |

The OpenRouter-shaped row is the ordinary case, not the corner: `is_openrouter`
is `model.startswith("openrouter/") or "/" in model_name`, and every model the
cascade probes has a `/`. Multiply by the cascade's own ~5 probes and one agent
step can reach four figures of HTTP requests.

### The largest layer is also the one that should not exist

```python
except RateLimitError:
    ...
    for fallback_model in fallback_models:      # ten of them
        kwargs["model"] = fallback_model
        response = await self._client.chat.completions.create(**kwargs)
```

`OpenAIAdapter` answers a rate limit by **choosing a different model**, beneath
the `CascadeExecutor` whose entire job that is — CLAUDE.md design rule 4 names
`CascadeExecutor.call_with_cascade` as the model-cascading mechanism. So the
spend is the visible half. The invisible half is that the response the cascade
receives may come from a model it never selected, while the usage is attributed
to the model it asked for. Cost accounting and tier logic are both wrong, and
nothing in the returned `LLMResponse` says which model answered.

This is the same duplicate-rule shape as the three routing tables in the
section above: one responsibility implemented twice, the copies drifting, and
no test comparing them.

### The fix, and why it is applied in one place

`_client_policy.apply_client_policy(inner, timeout=…, sdk_max_retries=0,
model_fallback=False)`, called once in `AdapterFactory.create_adapter`.

It was tempting to thread `timeout=` and `max_retries=` through
`_create_inner_adapter`'s eight provider branches, which is the more idiomatic
spelling. It was rejected for the reason this whole audit keeps finding: **a
branch that forgets the kwarg is silent.** One call site covers every provider,
including the nested composites — the factory can return
`CachingLLMAdapter(DirectOrFallbackAdapter(DeepSeekAdapter, OpenRouterAdapter))`,
and configuring only the outermost object would leave the client that actually
makes the call on SDK defaults, with no `_client` on the outer object to reveal
it. `apply_client_policy` walks the composite and **returns the number of
clients it configured**, so "applied" is distinguishable from "found nothing to
apply it to".

Mutating an already-constructed client is deliberate, and verified rather than
assumed — both SDKs read `self.timeout` and `self.max_retries` per request:

```
default            -> {'connect': 5.0, 'read': 600, 'write': 600, 'pool': 600}
after post-hoc set -> {'connect': 5.0, 'read': 7.0,  'write': 7.0,  'pool': 7.0}
```

(the request's `extensions["timeout"]`, which is what httpcore enforces).

### The obvious spelling of this fix would have been a regression

```
AsyncOpenAI(api_key=k, timeout=90.0).timeout   ->   90.0
```

A scalar replaces the **whole** `Timeout` object — connect included. Passing
the factory's 90–180s budget as a float would have widened the connect timeout
from 5s to 90–180s, so an unreachable host would stall a cascade probe for
minutes where it now fails in five seconds. Hence
`httpx.Timeout(t, connect=min(5.0, t))`, and a test that pins it.

### The bypasses, named rather than fixed

`test_llm_clients_are_built_by_the_factory` finds every construction of an SDK
client or concrete adapter outside `infrastructure/adapters/llm/`. Two exist,
both grandfathered at their measured count so a **third** fails the build:

| site | what it bypasses |
|---|---|
| `core/tool_agent.py:62` | builds `AsyncOpenAI` directly. The module already raises `DeprecationWarning` in `__init__`; the fix is deletion, not plumbing. |
| `osworld/agent_adapter.py:262` | builds `OpenAIAdapter` directly, so there is no `ResilientLLMAdapter` above it: no circuit breaker, no retry, no sanitiser, and the SDK's 600s read is the only time bound. `_call_llm` is **synchronous**, so that bound is held on the calling thread. |

A companion test fails if a grandfathered entry disappears, so the list cannot
outlive the bypasses and become mistaken for a design decision.

### Two things worth recording about the harness

**The proxy nearly made the measurement fake.** Swapping `httpx.AsyncClient._transport`
for a `MockTransport` had no effect: httpx reads `HTTPS_PROXY`/`NO_PROXY` at
construction and installs mounted transports per URL pattern, and `_mounts` is
consulted *before* `_transport`. The first probe reported `0 requests` and an
`APIConnectionError` — it had gone out to the network for real. CI has no
proxy, so this would have been a bug that appeared only on a developer's
machine. The helper clears `_mounts` as well, with the reason written down.

**The unfixed measurement was slower than the suite's timeout.** With
`retry-after: 0` the SDK ignores the header (it honours it only for
`0 < seconds <= 60`) and falls back to its own exponential backoff — ~140
sleeps, 80s, past the 60s `pyproject.toml` limit. `retry-after-ms: 1` gets the
same request count in 3s. The count is the claim; the sleeps are not.

### Coverage & residual risk

- **The cascade layer is untouched.** ~5 probes remain, by design — that is the
  cascade doing its job. 7 × 5 = 35 requests is still the worst case for one
  agent step against a fully rate-limited provider.
- **`enable_retry` and the SDK's retry now differ in behaviour, not just
  count.** The SDK honours `Retry-After`; `RetryWithBackoff` uses a fixed
  ladder with jitter and ignores the header entirely. Collapsing to one layer
  means rate-limit responses no longer get the provider's requested delay.
  That is a real regression in politeness, traded for a 30× reduction in
  requests. **UNKNOWN:** whether any provider in use penalises the fixed ladder.
- **`_enable_model_fallback` defaults to `True`.** Adapters constructed
  directly keep today's behaviour deliberately — the two bypass sites are not
  covered by tests, and changing behaviour on an untested path to fix a spend
  defect is the wrong trade. They keep the 30× amplifier; the gate says so.
- **Only `OpenAIAdapter` has an internal model chain.** Checked: `anthropic`,
  `openrouter`, `deepseek`, `moonshot` and the caching adapters have none. But
  `OpenRouterAdapter`, `DeepSeekAdapter` and `MoonshotAdapter` all *subclass*
  `OpenAIAdapter`, so all of them inherited it.

### Uncertainty acknowledgment

D44 was ranked "Priority 3, the liveness cousin of unbounded spend" and
deferred for five waves on a claim that was wrong about where the timeout was.
The record was not merely incomplete — its second clause was false, and acting
on it as written would have produced a fix for a defect that was not there
while leaving a 30× amplifier untouched. **UNKNOWN:** how many other deferred
entries are load-bearing on a clause nobody re-checked. The two entries closed
in this session were both mis-stated in the same direction: D39 understated its
consequence, D44 misstated its mechanism. That is two for two.

## Two paths that acquired something and never gave it back

### D37 and D38 — resource lifecycle `[VERIFIED-EXECUTED]`

Both were generated in W4, deferred to W7, and W7 spent its budget on S4's
thirty-seven connection sites. They sat `deferred` for four waves. They are the
same shape, and each turned out to contain a second defect the claim did not
mention.

### D38 — the child nothing could reach

```python
async def _start_mcp_http(self) -> None:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    await asyncio.sleep(2)
```

`proc` is a **local**. Nothing else in the class references it, so `close()` —
which does reach `self._process`, the *stdio* child — could not see this one. A
`qmd mcp --http` server outlived every client that started it, holding the
port. And with no handle there was nothing to check, so a second call started a
second server.

**ruff has been reporting this the whole time.** `F841 Local variable 'proc' is
assigned to but never used`, at that exact line. CI runs
`ruff check weebot/ cli/ --select F821,E9`. The linter could see it; the gate
did not ask. That is the fail-open shape again, this time in the tooling rather
than in the code.

The zombie half of the claim, measured rather than asserted:

```
after terminate() with no wait():   Z    sleep
after wait():                       (gone)
```

`Z` is defunct — the process is dead but its entry survives, holding a PID,
until the parent reaps it. One per start/stop cycle in a process designed to
run for a long time.

**A third thing, not in the claim.** Both `Popen` calls wire
`stderr=subprocess.PIPE`, and nothing ever reads stderr. An undrained pipe
blocks the writer once its 64KB buffer fills, so a server that logs enough
stops responding — a deadlock that presents as a slow server. The HTTP one
wires `stdout=PIPE` too, and nothing reads that either.

### The fix, and why the helper is shared

`weebot/core/process_lifecycle.reap_process` — terminate, wait, escalate to
`kill` on timeout, close the pipes, never raise (teardown that throws leaves
the *rest* of the teardown undone).

It is a shared module rather than a local function for a reason worth stating
plainly: **`infrastructure/document/latex_compiler.py` had already learned
this**, and written it down —

> ``proc.kill()`` alone only terminates the direct child (e.g. latexmk);
> grandchildren (xelatex, biber, pygmentize) survive, keep the stdout/stderr
> pipes open, and the post-kill ``communicate()`` blocks forever…

— two hundred lines away from a module calling `terminate()` with no `wait()`
at all. The knowledge existed in the repository and did not travel. Adding a
*second* private reaper would have reproduced the duplicate-rule pattern this
audit has now named three times, so `_kill_process_tree` was moved into the
shared module and `latex_compiler` delegates to it. One rule, one home.

### D37 — the browser that survived its own failed start

`PlaywrightAdapter.start()` acquires four things in sequence — driver, browser,
context, page — with no `try`. A raise from `new_context` or `new_page` leaves
a **live browser process** attached to `self`, and neither caller closes a
`start()` that raised:

| caller | shape |
|---|---|
| `tools/advanced_browser.py:370` | `await self.browser.start(config)` — bare |
| `tools/browser_inspector.py:283` | `await self.browser.start(BrowserConfig(headless=True))` — bare |

So nothing else would have cleaned it up either.

**`close()` had the same defect in reverse.** It closed context, then browser,
then driver, sequentially and unguarded — so a context that failed to close
stranded the browser process *and* the Playwright driver behind it. A cleanup
path where one stuck page takes down the whole teardown is worse than no
cleanup path, because it looks like one.

### The defect found by reading, not by the claim

```python
if self._config.record_har:
    await self._context.new_page()
    # HAR recording is set up at context level in Playwright
```

The comment is correct. The code does not do it. `record_har_path` is never
placed in `context_options` — compare `record_video`, three lines above, which
does set `record_video_dir`. So `record_har=True`:

- recorded nothing at all, and
- opened a page, discarded the reference, and leaked it — one per `start()`.

A configuration flag that reports a capability it has never had is the same
fail-open class as the gates in the earlier sections; it just happened to be
sitting inside a resource leak. It is now set properly, before `new_context`,
because Playwright cannot enable HAR on a context after creation.

### The ratchet caught me

The first version of `reap_process` used `except (ProcessLookupError, OSError):
pass` in three places. The bidirectional silent-except ratchet went red:

```
silent_except_handlers: 142 exceeds the ceiling of 139 by 3.
New debt of this kind was added. Fix it -- do not raise the ceiling.
```

Three DEBUG logs later it is back at 139. Worth recording because the gate did
exactly what it was built for, against the person who has spent this session
building gates, and the temptation to raise a ceiling by three is precisely
what `quality_ceilings.py --verify-not-raised` exists to make visible.

**And the piped-exit-code trap recurred.** Reading the ratchets through
`| tail -1` showed an advice line and no failure; `rc` was `tail`'s. The counts
above were re-taken by running each gate unpiped and reading `$?`. This is the
third time in this session that a pipeline has hidden a non-zero exit.

### Coverage & residual risk

- **`_call_stdio` still does blocking I/O in an `async def`** — `write`,
  `flush` and `readline` on the child's pipes, on the event loop. It is inside
  the `blocking_io_in_async` ratchet's 29 and is not fixed here.
- **`reap_process` does not kill process trees.** `qmd` is assumed not to
  spawn grandchildren; `kill_process_tree` is the tool if that turns out to be
  false, and it requires the child to be started in its own process group,
  which `mcp_client` does not do.
- **The HAR path is `./har/<uuid>.har`, relative to the working directory**,
  mirroring `record_video`'s `./videos`. Both inherit that convention's
  weakness: an agent that changes directory writes elsewhere.
- **The Playwright tests use fakes, not a browser.** They pin the *ordering and
  cleanup contract* — that a failed acquisition closes what it acquired, that
  teardown steps are independent — not that Playwright itself behaves as
  modelled.

### Uncertainty acknowledgment

D37's recorded location did not exist:
`weebot/infrastructure/adapters/playwright/` is not a directory in this
repository. The claim was still true, of a file at a different path. That is
the fourth record in this session found wrong in some particular — D39
understated its consequence, D44 misstated its mechanism, S5 undercounted its
instances, D37 mislocated its file. **UNKNOWN:** how many `deferred` entries
point at paths that no longer exist, and would be closed as "cannot reproduce"
by anyone who trusted the location field.

## The plan that failed completely and was learned from as a success

### P3 — silent false success, and what the record got wrong `[VERIFIED-EXECUTED]`

The recorded claim (ex-D21) was that the flow reaches `CompletedState` with a
step still RUNNING. It named the wrong mechanism. Executed truth table:

| plan | `get_next_step()` | `is_complete()` |
|---|---|---|
| all COMPLETED | None | True |
| one RUNNING | s1 | False |
| COMPLETED + RUNNING | s2 | False |
| **one FAILED** | **None** | **True** |
| **COMPLETED + FAILED** | **None** | **True** |
| empty plan | None | False |

`get_next_step()` and `is_complete()` **agree** on RUNNING — both say not done,
so a RUNNING step does not slip past either. The route the record described is
not open.

The route that *is* open is the fourth row. `Step.is_done()` is:

```python
return self.status in (StepStatus.COMPLETED, StepStatus.FAILED)
```

That is correct for its main caller — `get_next_step()` needs to know what is
still **runnable**, and a failed step must not be handed back or the flow
retries it forever. It is wrong in every place that read it as **succeeded**,
and three places did.

### The sharp end is not the status, it is the score

```python
completed_steps = sum(1 for s in context._plan.steps if s.is_done())
score = round(completed_steps / total_steps, 2) if total_steps > 0 else 0.5
```

Measured:

| plan | `is_complete()` | template `success_score` |
|---|---|---|
| every step FAILED | True | **1.0** |
| 1 done, 1 failed | True | **1.0** |
| all completed | True | 1.0 |

That score is written to the plan-template cache and keyed by task hash. So a
plan in which **nothing succeeded** was stored as a perfect template and would
be preferentially retrieved for the next similar task. The failure was not
merely reported as a success; it was **learned from** as one. Three identical
scores for three materially different outcomes is the whole defect in one row.

### The fix, and the fix that was tempting and wrong

The tempting fix is to change `Step.is_done()` to mean COMPLETED only. It would
have made `get_next_step()` return failed steps forever. A regression guard
pins that:

```python
assert _plan(StepStatus.FAILED).is_complete() is True
assert _plan(StepStatus.FAILED).get_next_step() is None
```

What was actually missing was a *second* predicate, not a changed one:
`Plan.is_successful()` (every step COMPLETED) and `Plan.failed_steps()`.
`CompletedState` now scores on COMPLETED and ends the session
`SessionStatus.FAILED` when any step failed.

### The domain cannot say "failed"

```
PlanStatus members: ['created', 'updated', 'running', 'completed']
```

There is no failure member. `CompletedState` stamps `PlanStatus.COMPLETED`
unconditionally because there is nothing else to stamp — the plan object has no
vocabulary for the outcome. `SessionStatus` does
(`pending/running/waiting/completed/failed`), and both the API and the web UI
already understand it, so that is the lever used here.

**Adding `PlanStatus.FAILED` is left open, and it is the user's call**, because
it crosses stacks: `weebot-ui/src/types/events.ts:5` declares
`PlanStatus = 'created' | 'updated' | 'completed'` — which is *already* out of
sync with the backend, missing `running`. A domain enum whose TypeScript mirror
is hand-maintained and already drifted is not a change to make silently.

### The steering that was collected, acknowledged, and thrown away

Found by running `ruff --select F841`, which CI does not select:

```python
effective_prompt = prompt
if context._steering is not None:
    steering_msg = await context._steering.poll(context._session.id)
    if steering_msg:
        logger.info("Steering received for session %s: %s", ...)
        effective_prompt = f"{prompt}\n\n[STEERING — the user says: {steering_msg}. ...]"
...
    user_input=prompt,          # ← the ORIGINAL
```

`effective_prompt` is assigned twice and read nowhere. Phase 5 polls the
steering channel, **logs that it received the user's message**, formats it into
an augmented prompt, and sends the original. A user correcting an agent
mid-run got a log line saying they were heard and no change in behaviour. The
fix is one word.

### `inner_facts`, and why wiring it would have been worse

Assigned `{}` at one line, read via `.items()` at another, never written —
confirmed by AST rather than grep. The loop always ran zero times, under a
comment reading "Persist any facts extracted by the executor".

Deleted rather than wired. No command or handler in `application/cqrs/` returns
facts, so there is nothing to receive; and `set_fact` writes to
`context.facts`, while `SessionContext.get` reads declared fields and then
`context.extra` and **never** `facts`. Wiring it would have produced an
apparently working fact pipeline over a store nothing reads — a fail-open
control assembled deliberately.

### The gate for the class, not the instance

Both `proc` (D38) and `effective_prompt` were F841 findings. ruff has been
reporting them the whole time; CI runs `--select F821,E9`.

`scripts/lint_unused_locals.py`, ceiling **33**, bidirectional, wired into the
architecture workflow beside the other ratchets. Proven to bite both ways:

```
unused_locals: 34 exceeds the ceiling of 33 by 1. New debt of this kind was added.
unused_locals: 33 is BELOW the ceiling of 34. ... set unused_locals = 33
```

An unused local is not always a defect. It is always *work the author wrote and
the program does not do*, which is why it gets a ceiling rather than a ban: the
33 that remain are an inventory to triage, and no new one may join them.

**One honest fragility, written into the script rather than hidden:** this
ratchet counts a third-party tool's output and `requirements.txt` pins only
`ruff>=0.8.0`, so an upgrade can move the number with no code change. The
script prints the ruff version with every count (`ruff 0.16.6`) and its failure
message says to check it before touching the ceiling.

### Coverage & residual risk

- **`PlanStatus.COMPLETED` is still stamped on a failed plan.** The session
  says `failed`; the plan object still says `completed`. Anything reading the
  plan's status rather than the session's still sees a success.
- **Three orphaned background tasks in `CompletedState`** (`ensure_future` at
  the retention review, skill-gap processing and the dream scan) are created
  and never referenced, awaited or cancelled — the D39 class again, and each
  builds a `Container()` and live LLM adapters. Recorded as `P3-4`, **not
  fixed**: unlike D39 these are *meant* to outlive the flow, so the fix is an
  owner, not a cancel, and that is a design decision. They are what made the
  P3 test hang until suppressed explicitly.
- **The empty-plan row is untouched.** `get_next_step()` returns None and
  `is_complete()` returns False, so a plan with no steps still transitions to
  Verifying → Completed. It now ends `SessionStatus.COMPLETED` with a score of
  0.5, which is arguably the least wrong of the available answers and is not a
  considered one.
- **32 F841 findings remain**, one of which may be another `effective_prompt`.
  The ratchet stops the 34th; it does not triage the 33.

### Uncertainty acknowledgment

This is the fifth record in this session found wrong in some particular, and
the second whose *mechanism* was misstated. The record said RUNNING; the
executed truth table says FAILED, and the two predicates it accused of
disagreeing actually agree. Had the fix been written to the claim, it would
have guarded a path that is not open and left a plan-template cache learning
from total failures at a perfect score. **UNKNOWN:** how many of the remaining
`open` entries were written from reading rather than from running, and would
survive an executed truth table no better than this one did.

## The gate that fired at random, and the suite nothing ran

### D65 — the mechanism was the wall clock `[VERIFIED-EXECUTED]`

D65 recorded a stress test failing about one run in seven against its own
comment predicting one in two thousand, and left the mechanism explicitly
**UNKNOWN** — two attempts to measure it had exceeded their own time budget and
been killed.

The mechanism is arithmetic. `RetryWithBackoff`'s default ladder is
`[1, 2, 4, 8, 15, 30]`, which sums to **exactly 60.0 seconds**, and
`pyproject.toml` sets `timeout = 60`.

Twelve isolated runs:

```
  run 1: PASS  18.08s
  run 4: FAIL  63.57s  Timeout (>60.0s)
  run 7: FAIL  63.77s  Timeout (>60.0s)
  run 9: PASS  62.34s
  ...
pass=10 fail=2
```

Every failure is `Timeout (>60.0s)`. **Not once** is it the assertion,
`Only N/20 succeeded`. And the durations cluster on the ladder's prefix sums
{1, 3, 7, 15, 30, 60} — 18s, 34s, 62s — which is the ladder's fingerprint. Run
9 passed at 62.34s wall having finished its body just inside the limit, which is
what a race against a clock looks like from the winning side.

### The comment is not wrong, it is about something else

> `# With 50% fail rate and 7 attempts, P(all 7 fail) = 0.5^7 ≈ 0.8%`
> `# So ~99.2% of 20 requests should succeed — allow 2 failures`

That arithmetic is correct, and P(successes < 18) is about 1 in 2400 — which is
what the original note observed the comment predicting. It models the assertion
failing. The assertion never fails. The comment describes a real and irrelevant
failure mode, which is why the discrepancy looked like a factor of ~280 and was
actually a category error.

### The fix

The sub-second ladder the other two retry tests in the same file already use:

```python
adapter._retry = RetryWithBackoff(
    BackoffConfig(delays=[0.01, 0.02, 0.04, 0.08, 0.1, 0.2], jitter=0.1, ...)
)
```

Twenty runs after the change: **20 passed, slowest 4.0s** against a 60s limit —
a fifteen-fold margin where there had been none. The test measures the retry
policy, not `asyncio.sleep`.

### The suite that could not go red

`tests/stress/` was referenced by **no workflow**. Thirty-five tests covering
the circuit breaker, retry backoff and timeout enforcement — including the one
failing one run in seven — could not redden anything. That is why a randomly
failing gate survived: nobody was watching it fail.

It is wired into the E2E job now that the flake is gone. The whole directory
runs in **10.65s**, so the cost of knowing is negligible, and it was never the
reason it was left out.

A gate that fires at random and a gate that cannot fire are the same defect
wearing different clothes: neither carries information, and the first is worse,
because it trains everyone to ignore red.

### S2 — cleared, and the larger thing behind it

S2 claimed `parse_agent_output` never raises, so a caller cannot tell "the model
reported PARTIAL" from "we failed to parse". Literally true, and about **dead
code**: `parse_agent_output` has zero callers outside its own re-export, and
`OutputParseError` is defined, re-exported, and **never constructed anywhere**.
The distinction is also weaker than the claim suggests — the failure path
already writes `confidence=0.3` and a `"Failed to parse JSON: …"` prefix.
Hardening a parser nobody calls buys nothing.

But the reason nobody calls it is the finding. **CLAUDE.md rule 2** states:

> Agents MUST return structured JSON validated via Pydantic models in
> `weebot/models/structured_output.py`

What agents actually do:

```
weebot/application/agents/dreamer.py:120           data = json.loads(raw)
weebot/application/agents/goal_agent.py:116        return json.loads(content)
weebot/application/agents/layer_editor_agent.py:129  return json.loads(content)
weebot/application/agents/optimizer_agent.py:183    parsed = json.loads(response.content)
```

Three modules import from `structured_output` at all, and only for
`VisionReflection` and the verbalized-sampler models. The documented mandatory
protocol is not the one in use.

This is the same shape as the three routing tables and the two process
reapers: **one rule, two implementations, nothing comparing them.** It is
recorded as `P5-1` and deliberately **not fixed** — migrating every agent is
cross-cutting, and the alternative (amending the rule to match reality) is a
decision about intent rather than a repair. Both need the owner's direction on
which of the two is the real one.

### Coverage & residual risk

- **The other stress tests were never measured for flakiness.** Only the one
  D65 named was. Wiring the suite into CI is what will find the rest, which is
  a cost the first red build will pay.
- **The 60s limit is global** (`pyproject.toml`), so any other test whose
  design brushes it is in the same position and equally invisible while its
  suite is unwired.
- **`parse_agent_output` is left in place.** It is a public re-export, and
  deleting it is only worth doing as part of resolving `P5-1` in one direction
  or the other.

### Uncertainty acknowledgment

The original D65 note was careful and honest — it labelled the mechanism
UNKNOWN and said so rather than guessing, and its HYPOTHESIS (timeout plus
backoff under concurrency truncating attempts) was in the right neighbourhood
without being right. What it lacked was one cheap measurement: reading *which*
failure the failures were. Twelve runs printing the failure line answered in
ten minutes a question two abandoned deep-dives could not. **The lesson is not
that the note was wrong; it is that "measure the symptom before modelling the
cause" would have closed this four waves earlier.**

## The security control that was declared, never ran, and could not have

### R6 C7/C8/C1/C6 `[VERIFIED-EXECUTED]`

`settings.py` declares `secret_redaction_enabled: bool = True`, described as
redacting secrets "in tool output and logs". `SecretRedactor` is 184 lines with
**zero callers**. A configuration reporting a control that has never run.

The earlier phase of R6 deliberately did not wire it, on the grounds that
wiring a corrupting redactor ships a log-corruption bug on the same commit as a
security fix. That judgement was right, and the corruption was worse than
recorded.

### C7 — four ways `redact()` rewrote the log around the secret

| input | output, before |
|---|---|
| `line one\nline two\tindented` | `line one line two indented` |
| `listening on port 8080` | `listening on port [CVV_REDACTED]` |
| `HTTP 404 Not Found` | `HTTP [CVV_REDACTED] Not Found` |
| `year 2026` / `took 250 ms` | `[CVV_REDACTED]` in both |
| `file.py:123` | `[HIGH_ENTROPY_REDACTED]` |
| `passwd: abc` and `secret: abc` | `password=[REDACTED]` — **both** |

The whitespace one is `text.split()` followed by `" ".join(...)`: every
newline, tab and run of spaces becomes one space, so a multi-line log arrives
as a single line.

The CVV one is `\b\d{3,4}\b`. A CVV cannot be recognised from digits alone —
it is three or four digits, and so is every port, status code, year, line
number and millisecond count. Context is the only thing that makes the
detection possible, so context is now required.

**`file.py:123` is the one worth pausing on**, and it was not in the record.
The token is eleven characters, well under the twenty-character entropy
threshold. The CVV rule fired first and produced `file.py:[CVV_REDACTED]` —
twenty-two characters, not alphabetic — which then tripped the entropy rule and
disappeared entirely. The guard against this was `if not word.startswith("[")`,
which only catches a marker at the *start* of a token.

**Redaction output fed back into redaction input.** A source location was
destroyed because an earlier redaction had lengthened it past a threshold.

The label rewrite was not recorded either: `_PASSWORD_RE.sub` wrote the literal
`password=[REDACTED]`, so a log line saying `secret: x` came out claiming to be
a password. A sanitiser is allowed to remove the secret. It is not allowed to
rewrite the sentence around it.

### C8 — four shapes presented as sanitised and left intact

| shape | what survived |
|---|---|
| `{"sk_live_AAAA…": "…"}` | the secret was the **key**; keys were never looked at |
| `b"password=hunter2"` | **bytes**; only `str` was handled |
| `[[{"note": "pw=x"}]]` | a dict below **two** list levels; one was recursed |
| `("password=hunter2",)` | a **tuple**; only `list` was recursed |

An `int` that is a valid PAN survived too. One recursive `_redact_value` now
covers str, bytes, dict, list, tuple and set, preserving each value's type
unless a secret was actually found — so `port: 8080` stays an int and
`pan: 4111111111111111` becomes a marker.

Redacting keys introduces a hazard the fix has to answer rather than create:
two distinct secret keys redact to the *same* marker, and collapsing them would
turn a sanitiser into a data-destroying one. Collisions are disambiguated, and
a test pins that no value is dropped.

### C1 — the plan's precondition was necessary and not sufficient

The plan said: fix C7/C8, then wire. Having fixed C7/C8, wiring it still would
not have been safe, and the measurement is unambiguous. Against text this
codebase's own tools produce:

```
commit b91a29ae9713861b86bc73dbf10be8a7b4823310   -> [HIGH_ENTROPY_REDACTED]
/home/user/weebot/.../_client_policy.py           -> [HIGH_ENTROPY_REDACTED]
session a779ecbb-1b3a-5bd9-a2db-8bff1bb2fbce      -> [HIGH_ENTROPY_REDACTED]
sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b…  -> [HIGH_ENTROPY_REDACTED]
```

**Redacting file paths and commit SHAs from a coding agent's tool output would
leave it unable to work.** And this is not a threshold to tune: a forty-character
hex digest and a forty-character hex key have the same character distribution,
so no threshold separates them. The heuristic is being asked to do something
information-theoretically impossible.

So the split: the **pattern** passes are wired into
`credential_sanitizer.sanitize`, which reaches all three emit pipelines through
one call site, and the **entropy** pass is opt-in (`enable_entropy=False`),
with `_NOT_A_SECRET_SHAPES` covering paths, hex digests and UUIDs for anyone
who turns it on.

What the wiring adds is not duplication of the existing denylist:
Luhn-checked card numbers, Stripe keys and labelled CVVs, none of which it
covered.

**Writing the test found one more.** The path shape did not cover the
`:line` / `:line:col` suffix — `some/path/file.py:123` was still redacted with
the pass on, and that is the single commonest shape in a coding agent's tool
output. Third time in this programme that the test, not the reading, found the
defect.

### C6 — the deferral's stated reason was false

C6 was deferred because changing it "overrules a test that encodes the defect
as the contract" — `tests/unit/test_secret_accessor.py:98`.

That test asserts `TIMEOUT = 30` is logged plainly. It is a legitimate
non-secret. **No test in that file mentions URL at all.** Nothing defended the
defect; the deferral had no basis, and a real leak sat behind it for a phase.

`_is_non_secret` waves through any key ending in `URL`, `HOST`, `PORT`, `DIR`,
`MODE` or `TIMEOUT`, and logs its value in full at DEBUG. Measured:

```
DATABASE_URL      = 'postgres://admin:hunter2@db.internal:5432/prod'
REDIS_URL         = 'rediss://:s3cr3tpassword@cache.internal:6379/0'
SLACK_WEBHOOK_URL = 'https://hooks.slack.com/services/T00/B00/XXXXXXXX…'
```

All three *are* the credential. A Slack webhook URL has no non-secret part at
all. This is a deny-by-shape heuristic ("a name ending in URL is config") used
as an **allow** rule ("so print the whole thing") — and a name is not evidence
about a value.

The fix does not argue with the allowlist. The reason to log a `*_URL` plainly
is to see which host you are talking to, and that survives; only the credential
inside it does not.

**And it exposed a gap in my own earlier work.** The URL-credential pattern
added in the first R6 commit required a non-empty username:

```python
r"\b([a-zA-Z][a-zA-Z0-9+.\-]*://[^\s:/@]+):([^\s@]+)@"
                                     # ^ requires a user
```

Redis and AMQP put the password in with no username at all —
`rediss://:s3cr3tpassword@host` matched nothing and logged in full. `+` → `*`.

### Coverage & residual risk

- **The entropy pass is still unwired**, so the only non-denylist mechanism in
  the codebase remains unused. `settings.secret_redaction_entropy_threshold`
  now configures something that does not run by default — a smaller version of
  the defect C1 was about, and it is deliberate rather than overlooked.
- **`_NOT_A_SECRET_SHAPES` is itself a denylist inside a heuristic that existed
  to avoid denylists.** It covers paths, hex digests and UUIDs because those
  are what this codebase emits; another codebase would need its own.
- **Key redaction changes the shape of logged data.** Collisions are
  disambiguated with a `#2` suffix, which is visible but not pretty, and a
  consumer parsing those keys would see them change.
- **`ToolEvent.function_args` is still not sanitised** — a credential passed
  *into* a tool sits there untouched, as recorded in the first R6 commit.

### Three of the repo's own gates caught this, again

- **`test_ids_are_unique`** — the four records were *appended* rather than
  updated, so `R6-C1`, `C6`, `C7` and `C8` each appeared twice with different
  statuses. Two rows with the same id means one of them is invisible and which
  one a reader believes is arbitrary. Merged in place, keeping wave order.
- **`test_core_no_global_singletons_outside_di`** — the lazy `SecretRedactor`
  was a module `global`. `lru_cache(maxsize=1)` has the same one-instance
  behaviour, is clearable in a test, and cannot be reassigned from elsewhere.
- **`test_run_mcp.py` failed with "--allow-remote requires WEEBOT_MCP_API_KEY"**,
  and that one was the most instructive: `SecretAccessor.set_source` is
  process-wide, the C6 tests installed a fixture dict, and nothing reset it —
  so every later test in the run was answered from this file's dict instead of
  the environment. `tests/unit/test_secret_accessor.py` already had the
  autouse reset fixture for exactly this reason; the knowledge did not travel
  the one directory it needed to. Same shape as the two process reapers.

### Uncertainty acknowledgment

C6's deferral note asserted a test existed that did not. That is the sixth
record in this session found wrong in some particular, and the first where the
error was in the *reason for not acting* rather than in the claim itself — a
category that is harder to catch, because a deferral is not re-read the way a
fix is. **UNKNOWN:** how many other `deferred` entries rest on a stated
obstacle that would evaporate on one `grep`. This one took thirty seconds to
check and had survived a phase.

## The question that was escalated four waves ago, answered

### Phase 0 / D13–D16 — fail open or fail closed `[VERIFIED-EXECUTED]`

W2 asked one governing question of every gate:

> *If this gate's own machinery fails, does it report a violation or report clean?*

It investigated four of the thirteen modules it named, fixed three defects, and
recorded the policy question itself as **escalated, not answered** — D13's own
note says the fail-open behaviour "is UNCHANGED ... asserted by a control test
so a later edit cannot quietly decide the question."

The decision taken: **security gates fail closed; quality gates fail open with a
loud, distinguishable marker.** This section covers the security half.

The enumeration W2 left unfinished was completed first — all ten uninvestigated
modules plus the security-side guards. Six live findings, six more in modules
with no production callers.

### The one that mattered most

```python
def _get_egress_guard(self):
    if self._egress_guard_resolved:
        return self._egress_guard
    self._egress_guard_resolved = True     # ← BEFORE the try
    ...
        except Exception:
            logger.error("egress_guard: unavailable — outbound tool calls will NOT be gated")
            self._egress_guard = None
```

The latch is set before the attempt. If both the DI lookup and the direct
construction fail, `_egress_guard` stays `None`, the early return hands `None`
back on every later call, and the call site's `if guard is not None:` skips
classification **for the rest of the session**. The log line states the
consequence in plain words and then the session continues sending.

Verified by reading the source rather than trusting the survey. Fixed by
latching only a *successful* resolution — so a transient failure self-heals —
and, when the guard is still unavailable and enforcement is on, refusing tools
in a conservative outbound-name set.

That set is deliberately broader than `EgressGuard._detect_egress`: without the
guard there is no way to inspect a bash command or a browser action. It is also
deliberately not "everything" — `file_editor`, `python_execute` and
`web_search` still run, so an unrelated import error does not brick the agent.

### Three more, each a correct comment with the wrong conclusion

| gate | the comment | the consequence |
|---|---|---|
| `approval_policy.py:218` | *"fail-open: the bad rule is ignored, all other rules still apply"* | the rules include DENY entries, so a typo turns a denial into an auto-approval |
| `bash_guard.py:443` | *"Skipping is still the only safe action here (raising would make the whole guard unconstructable)"* | true, and the log went to a file while the command ran |
| `bash_tool.py` legacy check | — | both decoders failing fell through to `return True, ""`: a blob it could not read was reported **clean** |

Each was fixed without the consequence the comment feared:

- **The approval policy** records the breakage and asks a human for every
  command while any rule is broken. We cannot know what a rule that will not
  compile was meant to catch, so "ask" is the only honest verdict.
- **The bash guard** still constructs. What changes is that a guard missing a
  BLOCKED rule no longer certifies anything as safe — `evaluate` refuses. In
  practice this fires only on a caller's `custom_patterns`, because a test now
  pins that every built-in compiles.
- **The obfuscation check** refuses what it cannot decode. The payload a check
  cannot read is exactly the one worth refusing, and `_validate_security` no
  longer answers an analyzer crash by silently running a 13-regex substitute
  and reporting its verdict as the real thing.

### What was surveyed and deliberately not fixed

Six further fail-open gates, all in modules with **no production callers**:

| module | the failure |
|---|---|
| `trust_boundary_scanner` | `except Exception: return None` — and `None` *is* the contract for "clean" |
| `agent_sanitizer` | no error channel at all; `quarantine_agent` is a silent no-op when disabled, and `is_quarantined` is never called |
| `identity_verifier` | an unknown `source_type` yields `{}` policy and verifies VALID; it also has a cache branch nothing writes to |
| `state_verifier` | fails closed on exception — but its default tail stamps an *unverified* claim `VERIFIED` at 0.9 |
| `chain_of_verification` | `(response, [])` on every failure, byte-identical to a clean verification |
| `security_validators.CommandValidator` | a PowerShell indicator anywhere in the string short-circuits bash validation to `VALID` |

This programme's own rule is that a DEAD reach cannot be CRITICAL, and that is
why they are recorded rather than repaired. It is also the R6-C1 ordering trap
in a new place: **wiring any of these up without fixing its failure path first
would ship the fail-open with it.** The record now says so, so the next person
to reach for one finds the warning before the wire.

### The gate with the right verdict and no enforcement

`HarnessSafetyGate.check` gates unknown surfaces correctly —
`# Unknown surface — treat as gated (fail-safe)`. Its caller:

```python
yield WaitForUserEvent(...)                    # line 206
saved = await self._target.save(candidate)     # line 208
```

Unconditionally, on the next statement. The comment above it says so: *"This is
a NOTIFICATION, not a blocking gate ... then optimistically saves."* An edit to
a safety-critical surface is persisted whether or not anyone approves.

Not fixed here, and not because it is small: this is a gate with no enforcement
point, which needs the durable-pause treatment D69 gave the flow gates rather
than a one-line change. Recorded as `PH0-6`.

### The control tests fired, exactly as designed

Three existing tests went red, and they are the ones D13's note described:

> the fail-open policy *is UNCHANGED* ... asserted by a control test so a later
> edit cannot quietly decide the question.

| test | what it pinned |
|---|---|
| `test_invalid_regex_does_not_raise_on_evaluate` | `approved is True` after a rule was dropped |
| `test_multiple_invalid_regexes_all_skipped` | three broken rules, still auto-approved |
| `test_guard_still_functional_after_dropping_a_pattern` | `is_safe("ls -la") is True` from a guard that had just lost a BLOCKED rule |

They did their job. A control test is not a contract to preserve — it is a
tripwire on an *undecided* question, and the question is now decided, so the
assertions record the decision rather than the placeholder. Each was rewritten
with the reason written into it, not flipped silently:

- "Still functional" was itself the fail-open. `is_safe()` returning `True`
  from a degraded guard is the guard vouching for a command it can no longer
  fully check.
- `test_invalid_regex_does_not_block_valid_literal_rules` still passes, and now
  **for a different reason** — the command is refused because the policy is
  broken, not because the literal rule matched. That is noted in the test
  rather than left to look like continuity.

Distinguishing "the test caught a real regression" from "the test pinned a
decision that has since been made" is the whole difficulty here, and getting it
wrong in either direction is bad: flip a real guard and you ship the bug;
preserve a placeholder and the decision can never be implemented.

### Coverage & residual risk

- **Only the security half is done.** The quality half — `plan_critic`
  returning `confidence=0.8, verdict="approved"` on any exception, which routes
  to the *proceed* branch and is byte-identical to a clean approval; the
  evidence auditor's three silent skips returning `score=1.0`; `verifying.py`'s
  outcome and artifact gates returning `None`/`[]` — is surveyed and not yet
  changed.
- **`verification_status` is written and never read.** `verifying.py` stamps
  NOT_RUN, and `SessionStamp` has `model_config = {"extra": "forbid"}` with no
  status field, so the marker cannot reach the stamp even if something wanted
  it. A distinguishable failure nobody can distinguish.
- **The conservative egress set is a name list.** A new outbound tool that is
  not in it, and not in `EgressGuard`'s own sets, is unguarded on the failure
  path — the same shape as the stale `"browser_tool"` entry already sitting in
  `_BROWSER_EGRESS_TOOLS` beside the real `"browser_navigator"`.
- **Refusing on analyzer failure is a real availability trade.** If the
  analyzer is flaky, bash stops working rather than degrading. That is the
  decision applied honestly, not an oversight.

### Uncertainty acknowledgment

Two subagents surveyed these modules and their reports were detailed and, where
checked, accurate. **Every finding acted on here was re-verified against the
source before a line was changed**, and that is not ceremony: this programme
has now found nine records wrong in some particular, and a survey is a record
like any other. The two spot-checks confirmed both claims exactly, which raises
confidence in the rest without establishing it. **UNKNOWN:** whether the six
unfixed findings are as precisely characterised as the four verified ones —
they were not checked line by line, because nothing was built on them.
