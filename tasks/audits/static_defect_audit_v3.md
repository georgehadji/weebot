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

