# Residual defect closure plan

**Supersedes the version committed in `dab78ed3`, which was drafted from the
audit record rather than from the code.** Four research passes have since
executed probes against every one of the 16 remaining candidates. Five
recorded claims turned out FALSE or mis-located, two defects are far more
severe than recorded, and one already-merged fix does not work in production.
The earlier draft's phase order was wrong as a result.

Evidence labels: **VERIFIED** (executed), **VERIFIED-STATIC** (read and
traced), **INFERENCE**, **UNKNOWN**.

---

## 0. The headline: a shipped fix is dead in production

**D69 — VERIFIED, with three probes against a real `SQLiteStateRepository`.**

Neither gate in `executing.py` persists anything before pausing. Every path
was traced:

| Path | Persists the gate pause? |
|---|---|
| `event_publisher._persist_session` | Only reachable from `emit()`. The gates `yield` (`executing.py:302,337`), never `_emit`. |
| `PlanActFlow.run()` | **No `save_session` anywhere.** Breaks on WAITING at `plan_act_flow.py:800`. |
| `AgentRunner.run_prompt` | Post-loop save at `agent_runner.py:221-234` **never runs** — `cli/commands/flow.py:91-99` breaks the `async for` on `WaitForUserEvent`, so post-loop code is skipped. |
| Gateways (telegram/slack/discord/…) | Zero `save_session` calls; rely entirely on `_emit`. |
| `TaskRunner._run_flow` | **Does** persist (`task_runner.py:240-247`) — the one path that works. |

```
IN-MEMORY   status=waiting  gate='inbound_mail'  mail_pending=False
IN DB       status=waiting  gate=None            mail_pending=True
DB event types: ['plan']          <- the WaitForUserEvent never landed
```

Three consequences, all VERIFIED:

1. **`weebot flow run` crashes on the user's answer.** The DB keeps `PENDING`;
   `agent_runner.py:258` raises `ValueError: Session ... is not waiting`.
2. **Both gates livelock across turns, unboundedly.** `atomic_mail_inbound_pending`
   and `constraint_gate_ack:{step.id}` never reach the DB, so the gate re-fires
   on every resume forever. `max_iterations` cannot bound it — each turn builds
   a fresh `PlanActFlow`.
3. **The D12/D67 fix is unreachable.** `_user_gate_pending` never reaches the
   DB, so the entire Priority-2 branch — the one that reads the user's answer,
   honours refusals, clears constraint acks and re-arms the mail gate — never
   executes on a DB-mediated resume. **ADR-006's "untrusted mail is not acted
   on without review" does not hold.**

The tests that prove D12 drive `resolve_initial_state` in-process and therefore
cannot see any of this. That is the lesson of this whole document: the unit
test was green and the feature was dead.

---

## 1. What the research changed

| ID | Recorded claim | Verdict |
|---|---|---|
| D69 | gates don't persist before pausing | **TRUE, far worse** — see §0 |
| D20 | terminate-branch missing `set_state` ⇒ prompt not reset | **FALSE** — probe shows `set_state` changes nothing; guard keys on *type* |
| D21 | update failure ⇒ unbounded livelock | **FALSE** — bounded at 3 step repetitions. Real defect nearby is worse |
| S5 | two dead transition tables | **TRUE, understated** — there are **three**, and the wiring script lies |
| D70 | graph lacks the gate + the flips | **TRUE, incomplete** — **6** divergences, not 2 |
| D32 | 3 write transactions ⇒ partial state | **TRUE, mis-prioritised** — commitments never persist *at all* |
| D34 | truncation twice, one resets the watermark | **TRUE / mechanism backwards** — the resetting copy is the dead one |
| D36 | `close()` leaks a checked-out reader's thread | **TRUE, verified with counts** — hangs the interpreter |
| D39 | orphaned probes bill on `FIRST_COMPLETED` | **MIS-LOCATED** — false on the success path, true on the *common* failure path |
| D44 | no client HTTP timeout anywhere | **FALSE as written** — SDKs default to 600s; the factory computes the right value and drops it |
| D37 | Playwright `start()` has no cleanup | **TRUE** — leak is on *retry*, one browser + pipe per attempt |
| D38 | Popen never waited | **TRUE at two sites**, neither the one recorded |
| D65 | flaky stress test, mechanism unknown | **SOLVED** — backoff ladder sums to exactly the pytest timeout |
| S2 | parser cannot signal failure | **TRUE but dead** — zero production callers |
| D9/D10 | no recorded claim | **Region mapped; 8 candidates generated, several VERIFIED leaks** |

Nine of sixteen were wrong, incomplete, or mis-located. Planning from the
record would have produced the wrong work in nine cases out of sixteen.

---

## 2. Architectural constraints

- **Dependency direction** `Interfaces → Infrastructure → Application → Domain`.
- **`.importlinter` has 7 contracts, each with an `ignore_imports` list except
  `domain-purity`, which has zero grandfathered exceptions.** No fix below may
  add to any ignore list, and the domain stays pure.
- **Ports, not copies.** Where a rule must hold for every adapter, it belongs
  at the port or the composition root. Copying it into N adapters is the R2
  defect class (below) being manufactured deliberately.
- **Ratchets stay at 139 / 29 / 143 / 73 / 68.** A fix needing one raised is
  the wrong fix.
- **Shell-execution gate is at a ceiling of zero.** D38's fix must keep the
  list-argv form.

### The two defect classes

**C2 — a control whose failure mode is "report clean."** D69, D21's silent
success, D32's swallowed exception, D39, R6-C1, `wire_stategraph.py`.

**R2 — one rule written twice, the copies drifting.** S5/D70 (three routing
tables), D34 (truncation twice), R6-C3 (two forks of one regex, one broken),
D44 (a timeout computed once and dropped), the six model registries.

Both classes are invisible to tests by construction. Every phase below closes
instances *and* adds the gate that makes the class detectable.

---

## P0 — Make the pause durable (D69)

**Everything else in the flow layer is worthless until this lands.** It is the
only item that is simultaneously a crash, a livelock and a silently-dead
security control.

Three approaches:

| | Approach | Blast radius | Risk |
|---|---|---|---|
| **A** | Mirror `plan_review.py`: `add_event` + `await _state_repo.save_session()` before each `yield` | 1 file, 2 sites | `_state_repo=None` in sub-agent flows silently keeps the bug; replicates plan_review's double-add unless you add *or* emit, not both |
| **B** | Route the pause through `await context._emit(wait_event)` | 2 sites | `_persist_session` swallows exceptions, so a failed write is a warning and the CLI still crashes; the `_event_pipeline` branch is a separate path needing confirmation |
| **C** | One `PlanActFlow._pause_for_user(question)` that sets WAITING, adds the event, persists, publishes, and returns the event for the gate to yield | `plan_act_flow.py` + 3 pausing states | Largest diff |

**Recommend C.** It is the only option that also covers the HITL branch at
`executing.py:510-525` (same gap), removes plan_review's double-add, and makes
the next gate correct by construction. A and B leave a shape that the next gate
author will copy incorrectly — which is exactly how this defect arose.

**Do not** put the save in `run()` after the state call: VERIFIED that the CLI
breaks the generator while `run()` is suspended at the `yield`, so that line is
never reached.

**Exit gate — the one that would have caught this:** an end-to-end test that
pauses at a gate, reloads from a real `SQLiteStateRepository`, and resumes.
Every existing gate test drives `resolve_initial_state` in-process; that is why
all 41 were green against a dead feature. This test is the deliverable, more
than the fix is.

---

## P1 — Region R6: secret classification and event sanitisation (D9, D10)

Promoted from last place to second. The region W1 named but never audited
contains the most severe unshipped defects found anywhere in this backlog.

**R6-C1 — the redactor does not exist (VERIFIED).** `weebot/core/secret_redaction.py`
is 184 lines of PAN/Luhn, Stripe, AWS, JWT and Bearer detection with **zero
callers**. `settings.py:419-423` declares `secret_redaction_enabled: bool = True`,
described as "Redact secrets (PANs, API keys) in tool output and logs". The
configuration reports a control that has never run. Pure C2.

**R6-C5 — tool output is never sanitised (VERIFIED).** The gate is
`isinstance(event, MessageEvent) and event.role == "user"`. `ToolEvent.result`
carries raw stdout — `cat .env`, `env`, `git remote -v` — into the event bus,
the WebSocket broadcast to the web UI, and SQLite. `EventPublisher`'s own
docstring lists credential sanitisation as an unconditional stage. **Highest-value
item in the region.**

**R6-C3 / C4 — the live sanitiser is weaker than the dead one (VERIFIED).**
`resilient_adapter.py:30`'s `sk-[a-zA-Z0-9]{20,}` cannot match `sk-ant-…`
(fails at the third character) while `credential_sanitizer.py:25`'s
`[a-zA-Z0-9_-]{20,}` can — two forks of one regex, one broken. The live set has
no Bearer, Authorization, GitHub, Google or Slack rule; verified leaks include
`ghp_…`, `AIzaSy…`, `xoxb-…` and `Authorization: Basic …`.

**R6-C2 — `_sanitize_error` no-ops on any exception whose `__str__` is computed**
rather than `args[0]`, i.e. every httpx/openai wrapper, and the caller re-raises
it as though sanitised.

**R6-C6 — the non-secret classifier allowlists `*_URL` and `*_HOST`**, so
`DATABASE_URL=postgres://user:pass@host/db` and `SLACK_WEBHOOK_URL` are logged
in plaintext. A deny-by-shape heuristic used as an allow rule. Note
`tests/unit/test_secret_accessor.py:98` currently *asserts this is correct* —
the test must change with the code.

**R6-C7 / C8 — latent, and they matter only once C1 is fixed.** `redact()`
collapses all newlines and tabs and redacts every 3-4 digit integer as a CVV
(`port 8080` → `port [CVV_REDACTED]`); `redact_dict` skips non-`str` scalars,
dict keys, and anything below one list level, returning a dict it presents as
sanitised. **Wiring C1 without fixing these ships a log-corruption bug on the
same commit.**

**Order matters here.** C5 (gate the right events) and C3/C4 (fix the live
patterns) are shippable now. C1 (wire the redactor) must land *after* C7/C8, or
it makes things worse. Recommend: C5 → C3/C4 → C7/C8 → C1.

**Architecture:** all of this is Core + Application/flows; sanitisation belongs
at the single emit choke point, not copied per event type. There must be **one**
sanitiser, not the current two-plus-one-dead.

---

## P2 — One routing table (S5, D70)

**`scripts/wire_stategraph.py` is itself a C2 defect (VERIFIED).** Run against
a copy, it exits 0 and prints `StateGraph wired into FlowRouter.resolve_initial_state()`.
Actual effect: two duplicate insertions and one **silent no-op** — its
`old_body` no longer matches, because `resolve_initial_state` has since grown
the `_user_gate_pending` branch. `str.replace` returns the input unchanged on
no match and the script never verifies. Output still compiles.

There are **three** dead tables, not two: `state_graph.py`,
`flow_state_machine.py::_TRANSITION_TABLE`, and `flow_serializer.py::to_langgraph`
(a hardcoded 4-node description of a 13-state machine). Against **45**
`context.set_state(...)` calls, which are the real authority.

The six divergences (all VERIFIED) make wiring the graph a security regression:
declining a gate returns `ExecutingState` under the graph — the entire ADR-006
refusal path vanishes — and an empty answer becomes consent.

| | Approach | Blast radius | Risk |
|---|---|---|---|
| **A** | **Delete** all three tables, the wiring script, `_get_graph`, `_state_class_map`, `_route_*`, `to_langgraph` | Lowest — unreachable code | ADRs still describe a declarative machine |
| **B** | Wire the graph | **Highest** — resume path for every session | The 6 divergences are a prerequisite list; `ProductGateState(resume_with=prompt)` is unrepresentable by a name-returning factory; `resolve` swallows `AttributeError`/`KeyError`, downgrading a routing bug to "fresh planning" and discarding a live plan |
| **C** | Conformance test asserting the table matches the router | Nil | Pins current behaviour *including* the shared `extra`-wipe bug; a dead table with a green test is more misleading, not less |

**Recommend A.** The abstraction has no consumer, is missing six behaviours,
cannot express one that is required, and its only live artefact is a script
that claims success while doing nothing.

---

## P3 — The flow defects that are actually there (ex-D20, ex-D21)

Both recorded claims are FALSE. Both have a real defect beside them.

**Silent false success (was D21) — VERIFIED.** With `UpdatePlanCommand` failing,
the flow reaches `CompletedState` with step `s1` still RUNNING and `s2` PENDING.
`Plan.is_complete()` correctly returns False; the flow reports done anyway.
Compounding it: `_snapshot_plan()` is never called on the failure path, so
`PlanStuckError` cannot fire; the `ErrorEvent` is yielded without `_emit`, so it
is never persisted or published; and `_step_execution_counts` is per-flow-instance,
so the bound resets on every CLI resume.

Fix options: (A) mark the step FAILED on the failure path — one file, but
removes three accidental free retries; (B) an explicit update-failure budget
plus stuck detection — three overlapping bounds with no single owner; (C) gate
`CompletedState` on `plan.is_complete()` — **the honest one**, no domain change
needed since `Plan.is_complete()` is already correct, but it converts today's
silent successes into loud failures and will break happy-path expectations
elsewhere.

**Prompt re-delivery (was D20) — VERIFIED.** The type-keyed guard is defeated by
any path transiting another state type: Executing→Updating→Executing re-delivers
the original prompt on all 7 entries, and on a resume that prompt is the user's
HITL answer, reaching `ExecuteStepCommand(user_input=prompt)` for every later
step. The stated invariant holds only on same-type re-entry.

**`inner_facts` is dead** — initialised at `executing.py:426`, iterated at
`:725`, never written. Executor-extracted facts are silently dropped. Delete it
or wire it; do not leave it.

---

## P4 — Money and resources (D39, D44, D37, D38)

**D39 — the failure path is the common path (VERIFIED).**

| scenario | requests | billed | cancelled |
|---|---|---|---|
| fastest probe succeeds | 5 | 1 | 4 |
| fastest probe **fails** | 6 | **6** | **0** |

*(Six-probe harness. The closing measurement in
`tasks/audits/static_defect_audit_v3.md` uses five probes and reads 5/5/0
pre-fix — the same defect, a different probe count. Cite the audit's numbers,
not these, when quoting the fix.)*

`_cascade_try_chat` returns `None` for *every* failure and never raises, and a
429/503 returns in ~200ms against seconds for a real completion — so the
first-completed future is preferentially the fastest **failure**, and that
branch falls through to Phase 2 with `pending` neither cancelled nor awaited. In
the measured run both slow probes *succeeded*, were discarded, and the cascade
escalated to a further paid call.

Fix: cancel-and-drain **outside** the success branch, bounded by
`asyncio.wait(pending, timeout=…)` so a `CancelledError`-swallowing adapter
cannot block. Optionally harvest rather than discard (better spend, worse p99).

Two facts that must be stated with the fix, both VERIFIED: pending tasks left
uncancelled **run to completion**; and `asyncio.shield` defeats cancellation
entirely, so the fix must confirm nothing shields the call. **Honest caveat:**
cancelling aborts client-side, but tokens the provider already generated may
still bill. This reduces spend; it does not provably zero it.

**Adjacent and arguably worse:** `estimate_cost()` returns `0.0` for any model
absent from `MODEL_CASCADE`, and **16 of the 20** models reachable through role
cascades are absent. The wasted spend is structurally invisible to the very
telemetry that would reveal it. Fixing D39 without fixing this leaves no way to
confirm the fix worked.

**D44 — the value is computed and dropped (VERIFIED).** SDK defaults are
`connect=5, read=600` for both anthropic 0.117.0 and openai 2.54.0.
`adapter_factory.py:158` computes the correct per-provider timeout (60–180s) and
passes it **only** to `ResilientLLMAdapter`; `_create_inner_adapter` never
receives it. So the transport sits at 600s while policy says 60–180s, and the
wrapper's `wait_for` is the only thing in between.

One real bypass exists: `weebot/osworld/agent_adapter.py:262` constructs a bare
`OpenAIAdapter` with no factory and no wrapper — a hung socket blocks the full
600s. (Streaming is *not* a gap: VERIFIED that `as_streaming()` wraps the
resilient adapter in `NonStreamingLLMAdapter`, routing back through `chat()`.)

Fix: forward the already-computed timeout into the inner adapter — one value,
one place — set above the wrapper's (e.g. `× 1.5`) so the wrapper stays
authoritative and `ErrorClassifier` keeps seeing the same exception type. Add a
fitness test that concrete LLM adapters are constructed only inside
`adapter_factory`, closing the osworld bypass. **Do not copy a literal into six
constructors.**

**D37 — the leak is on retry (VERIFIED).** Path is
`weebot/infrastructure/browser/playwright_adapter.py`. `start()` has no
`try`/`except`; a failure after `launch()` leaves `self._browser` set, so it is
recoverable — but `browser_inspector.py:278-283` re-calls `start()`, which
overwrites it, orphaning one browser process plus its driver pipe per attempt,
surviving `close()`. Fix: build into locals, publish to `self` only on full
success. Also delete the vestigial `record_har` page at `:134-136` — it creates
an orphan tab, and HAR recording never actually happens because `record_har_path`
is never set.

**D38 — two sites, neither the recorded one (VERIFIED).** Both in
`weebot/qmd_integration/mcp_client.py`: `:239` (never stored, waited or
terminated, *and* `stdout=PIPE` with no reader, so the server deadlocks at
~64KB) and `:518` (`terminate()` with no `wait()`). Every other Popen site in
the repo is handled correctly; `behavior_commands.py:138-143` is the reference
pattern to copy. Counter-intuitive and verified: *retaining* the reference
without waiting is worse than dropping it.

---

## P5 — D65, and S2

**D65 — mechanism found; the fix is now obvious.** The backoff ladder
`[1,2,4,8,15,30]` sums to **exactly 60.0s**; `pyproject.toml` sets
`timeout = 60`. The test fails the wall clock, not its assertion.

| event | probability |
|---|---|
| wall clock > 60s | **0.1441** (1 in 6.9) — matches the observed rate |
| `successes < 18` (what the comment models) | 0.00042 (1 in 2410) — matches the comment's "1 in 2000" |

Both fall out of one model over 200k trials; five timed runs cluster on the
ladder's prefix sums {1,3,7,15,30,60}. **The comment is not miscalculated — it
computes a different, irrelevant failure mode.** Fix: give the test a
sub-second ladder. It is measuring `asyncio.sleep`, not resilience. Note
`tests/stress/` is referenced by **no** workflow, so this never reddens CI —
which is also an argument for wiring it in.

**S2 — clear, do not fix.** Literally true, but `parse_agent_output` has zero
non-example callers, and the failure path already writes `confidence=0.3` and a
`"Failed to parse JSON: …"` prefix, so the distinction is fragile rather than
absent. `OutputParseError` exists and is never constructed. Recommend recording
it `cleared` as dead code, or deleting the function outright.

---

## 3. Sequencing

```
P0  D69 durable pause          ── blocks everything in the flow layer
     │
     ├── P2  delete the three dead tables      (independent once P0 lands)
     └── P3  silent false success, prompt re-delivery

P1  region R6 sanitisation     ── independent, highest severity after P0
P4  money & resources          ── independent, parallelisable
P5  D65, S2                    ── independent, cheap
```

P1 and P4 touch no code P0–P3 touch and can run concurrently. P2 must follow
P0 only because deleting the graph while the resume path is being changed makes
both diffs harder to review, not because of a technical dependency.

**Per-phase exit gate**, unchanged: red-before-green pasted into the audit, a
six-vector RAR table, `ruff --select F821,E9` clean, `lint-imports` 7 kept /
0 broken, `make lint-unawaited` clean, all five ceilings unmoved, and the
candidate inventory test green.

---

## 4. New candidates to record before work starts

The research generated 20+ defects not in the inventory. They must be recorded
before any of them is fixed, or the inventory stops being the source of truth:

- **R6-C1 … R6-C8** — the secret/sanitisation region (§P1).
- **Commitments never persist** — `CommitmentStatus` is a plain `Enum`, so
  SQLite refuses the bind; swallowed at DEBUG. Two further signature mismatches
  in the same feature, also swallowed. Table row count: **0**.
- **FTS grows quadratically** — the watermark reset re-inserts history because
  `index_event` has no dedup. Measured 21 → 43 → 66 → 90 rows for 24 events;
  search returns 4 hits for one event, plus phantom hits for content no longer
  in the persisted row. A `clear_session_events` helper exists and is never
  called, while a third inline copy of that DELETE sits at `sqlite_state_repo.py:373`.
- **`estimate_cost()` returns 0.0 for 16 of 20 reachable models.**
- **`wire_stategraph.py` reports success while doing nothing.**
- **`inner_facts` is dead**; **`plan_review.py` double-adds the wait event**;
  **`_write_lock` is not re-entrant**, so the obvious D32 fix self-deadlocks.

---

## 5. Risk register

| Risk | Assessment |
|---|---|
| **P0 is a live-behaviour change to the pause path** | Unavoidable. The current behaviour is a crash plus an unbounded livelock, so "do nothing" is not the safe option it usually is. |
| **P1 C1 before C7/C8 ships a log-corruption bug** | Order is stated above; deviating from it makes things worse, not just no better. |
| **P3 option C turns silent successes into loud failures** | That is the point, but it will break happy-path expectations elsewhere and should be budgeted as such. |
| **D39's fix cannot be confirmed without fixing `estimate_cost`** | Do them together or the fix is unfalsifiable. |
| **Nine of sixteen recorded claims were wrong** | Expect the same rate among the 20+ newly recorded candidates. Trigger before fixing; the V3 promotion gate exists for exactly this. |
| **Every gate test was green against a dead feature** | The recurring failure is unit tests that drive a function directly and never cross the seam. Each phase's exit gate must include one test that crosses the real boundary. |
