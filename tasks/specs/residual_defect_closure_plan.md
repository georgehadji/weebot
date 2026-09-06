# Residual defect closure plan

Closes the 16 candidates still not closed in `tasks/audits/candidates.yml`
(72 records: 48 fixed, 8 cleared, 12 deferred, 4 open).

The plan is organised by **architectural seam**, not by defect id. Fixing the
16 one at a time repeats the same investigation four or five times, and two
of the seams contain defects that are the *same defect* wearing different
numbers.

Status labels follow the audit convention: **VERIFIED** (executed),
**VERIFIED-STATIC** (read and traced, not executed), **INFERENCE**,
**HYPOTHESIS**, **UNKNOWN**.

---

## 1. The two classes behind the sixteen

Almost every remaining item is an instance of one of two patterns. Naming
them matters, because closing the class is cheaper than closing the
instances and it is the only thing that stops the next instance appearing.

### Class C2 — a control whose failure mode is "report clean"

The modal defect of this codebase. Every fix in PR #60 was one. What remains:
D69 (a gate that may not persist what it recorded), D21 (a failure handler
that returns to the failing step), D39 (a spend control that leaks the
budget it bounds), D44 (a timeout that does not exist), S2 (a parser that
cannot say it failed).

### Class R2 — two representations of one rule, one of them dead

Newly visible, and the more expensive of the two because it is invisible to
tests. Instances: **S5 + D70** (two routing tables, the declared one dead),
**D34** (a truncation rule implemented twice, one copy resetting the FTS
watermark), and — outside this backlog but the same shape — the six model
registries that disagree in ≥14 places.

R2 is what makes D70 dangerous. `scripts/wire_stategraph.py` is a committed
script whose purpose is to swap the live representation for the dead one.
Running it would silently revert both security gates while every test kept
passing, because the tests address the live copy directly.

---

## 2. Architectural constraints this plan respects

From `CLAUDE.md` and `.importlinter` (7 contracts, currently 7 kept / 0 broken):

- **Dependency direction** `Interfaces → Infrastructure → Application → Domain`.
  Domain stays pure. No phase below adds an outward edge.
- **Ports and adapters.** Where a fix must apply to *every* adapter of a kind
  (D44), it belongs at the port or the composition root, not copied into each
  adapter — copying it is how R2 starts.
- **Structured output protocol.** S2's fix must express failure inside the
  Pydantic contract in `weebot/models/structured_output.py`, not by raising
  across a layer boundary.
- **Bash safety.** Now enforced at a ceiling of zero by
  `test_no_shell_execution_outside_the_bash_guard`. D38 must not reintroduce
  a shell.
- **Ratchets stay put.** `139 / 29 / 143 / 73 / 68`. A fix that needs a
  ceiling raised is the wrong fix; that rule has already caught me once.
- **V3 promotion gate.** No fix at HYPOTHESIS. Every phase below begins by
  promoting its candidates to VERIFIED, and **9 of the 16 are currently
  HYPOTHESIS** — generated and read, never triggered.

---

## 3. Phase 0 — the decision that is not mine

**Blocking for nothing; ignoring it is itself a choice.**

`D13`/`D16` are fixed in the sense that three verification paths now fail
open *visibly* rather than silently. **Whether they should fail open at all
is undecided and is a product decision.** A control test currently pins the
existing answer, so the codebase has committed to "fail open" by default
without anyone deciding it.

Two questions, both cheap to answer, both expensive to guess:

1. When a step evaluator is unreachable, should the step proceed (current) or
   halt?
2. When the trajectory analyst fails, should the optimizer consume a record
   marked `analysis_unavailable` (current) or discard it?

If the answer is "halt", Phase 2 gets a third item and the flow work should
absorb it while that code is already open.

---

## 4. Phase 1 — prove the seam (D69)

**Do this first.** It decides whether the D12/D67 fix on PR #61 works at all,
and Phases 2 onward touch the same code.

| | |
|---|---|
| Defect | D69 — neither gate calls `save_session` before pausing |
| Status | VERIFIED-STATIC that `PlanReviewState` saves and the gates do not; **UNKNOWN** whether it matters |
| Layer | Application (`flows/states/executing.py`) ↔ Infrastructure (state repo) |

**What is already established.** `PlanReviewState` calls
`await context._state_repo.save_session(...)` before it pauses. Neither gate
in `executing.py` has any save. `agent_runner.resume_session` loads from the
repository and rejects unless the loaded status is `WAITING`.

**Why it is not simply a bug.** The routing flag and the `WAITING` status are
set on the *same immutable session, one line apart*. Whatever persists one
persists the other. So the flag's durability is exactly the gates'
pre-existing `WAITING` durability — which the gates have depended on since
long before this work. If that is broken, the gates were always broken and
resume always raised "is not waiting".

**The work is a measurement, not a fix.** One end-to-end test: drive
`ExecutingState` to a gate against a real `SqliteStateRepo`, reload the
session from the repository, and assert both the status and the flag
survived. That test is the deliverable whichever way it comes out.

- If it survives → D69 closes as `cleared`, and D12/D67 are proven at the seam.
- If it does not → the gates have never worked, which is a **higher-severity
  finding than anything in this backlog**, and the fix (save before yielding,
  as `PlanReviewState` does) is three lines.

**Exit gate:** a committed test that exercises pause → persist → reload →
resume through the real repository, not `resolve_initial_state` directly.

---

## 5. Phase 2 — one routing table (S5, D70, D20, D21)

The flow state machine, taken as one piece of work because these four
overlap in the same ~200 lines.

### 5a. The R2 instance: two transition tables

**VERIFIED:** `FlowRouter._get_graph()` has **zero callers** in `weebot/`,
`cli/` or `tests/`. `build_default_state_graph()` still registers
`resume_incomplete_plan` at priority 2 and has no user-gate transition, so it
now contradicts the live router. `scripts/wire_stategraph.py` exists to swap
one for the other.

Three materially different resolutions:

| | Approach | Cost | Risk | What it buys |
|---|---|---|---|---|
| **A** | **Delete** `state_graph.py`, `wire_stategraph.py`, and the `_route_*` helpers that exist only to feed them | Lowest | Lowest — removing dead code cannot change behaviour | Divergence becomes impossible; the loaded gun is unloaded |
| **B** | **Wire** the graph: `resolve_initial_state` delegates to `graph.resolve()`, with the missing transitions added | Highest | **Highest** — rewrites the resume path for every session, and the graph lacks the `WAITING → RUNNING` flips the router has | Realises the documented data-driven design |
| **C** | **Derive one from the other**: keep the router as the implementation, add a test that asserts the table matches it | Medium | Low | Keeps the option open; drift becomes a test failure |

**Recommendation: A.** The abstraction has no consumer, is missing two
behaviours the router has, and its only concrete effect today is the risk
that someone runs the wiring script. Deleting it is the change that makes the
architecture *more* honest, not less: the docstring currently describes a
machine that does not execute, which is the defect S5 actually names.

**If the user wants data-driven routing kept as a goal**, take C now and B
later behind Phase 1's end-to-end test — never B without it.

### 5b. D20 and D21 — the two flow defects proper

Both are **HYPOTHESIS**: generated and read in W3, never triggered. Promote
first.

- **D20** — terminate-with-next-step returns without `set_state`, so
  `prompt_consumed` is never reset. Trigger: drive a flow to that branch and
  assert the flag's value on the next iteration.
- **D21** — `UpdatePlanCommand` failure returns `ExecutingState` to the same
  failing step. **If confirmed this is a livelock**, and the most severe item
  in the backlog after D69. Trigger: make `UpdatePlanCommand` fail
  deterministically and bound the iteration count.

D21's fix is a design choice, not a repair: a failing plan update needs an
escape — a bounded retry, a transition to a failed terminal state, or a pause
for the user. Given this session's precedent (the gates re-plan on a
non-approval), a **bounded retry then a user pause** is the option most
consistent with the rest of the machine, but it should be chosen with the
Phase 0 answer in hand, since it is the same question in a different place.

**Exit gate:** `make lint-unawaited`, `lint-imports` 7/0, the architecture
suite, plus a bounded-iteration test that fails on the pre-fix code.

---

## 6. Phase 3 — persistence integrity (D32, D34, D36)

All three **HYPOTHESIS**. All three in Infrastructure, so no layer boundary
moves.

- **D32** — `save_session` spans three write transactions; a crash between
  them leaves partial state. Options: (A) one transaction across all three
  writes; (B) idempotent replay on load; (C) accept partial and repair at
  read time. **A** if the schema allows a single connection — it is the only
  one that makes the invariant true rather than papering over it. B and C
  both add a second representation of "what a complete session is", i.e. a
  fresh R2.
- **D34** — a truncation rule implemented twice, only one copy resetting the
  FTS watermark. This is R2 again. The fix is *one* implementation with the
  other calling it; adding a test that both agree would preserve the
  duplication that is the defect.
- **D36** — `close()` drains only the idle queue; a checked-out read
  connection leaks its worker thread. Trigger with a checked-out connection
  at close time and assert on thread count.

**Sequencing note:** Phase 1's end-to-end test needs a real state repository,
so it will exercise this code first. Run Phase 1 before Phase 3 and its
failures may hand you D32 for free.

---

## 7. Phase 4 — resource lifecycle and spend (D37, D38, D39, D44)

Grouped because all four are "something acquired is not released", and two of
them cost money.

- **D39** — orphaned probes on the `FIRST_COMPLETED` path
  (`_cascade.py:452`) keep running and billing. **Highest-value item in this
  phase**: it is a spend control that leaks the spend it bounds (C2), and the
  fix is the standard one — cancel `pending` and await the cancellations.
- **D44** — no client HTTP timeout on any concrete adapter. There are ~7
  concrete adapters under `infrastructure/adapters/llm/`. **Do not copy a
  timeout into each** — that is how R2 is born, and the six disagreeing model
  registries are the same mistake at scale. Put it at the composition root
  (`adapter_factory`) or in the port contract so a new adapter cannot be
  added without one. A test that constructs every adapter via the factory and
  asserts a timeout is set is the gate.
- **D37** — Playwright `start()` has no cleanup if `new_context`/`new_page`
  raises after `launch()`. Standard `try/finally` around the acquisition
  sequence.
- **D38** — `subprocess.Popen` assigned to a local and never waited;
  `terminate()` without `wait()` leaves a zombie. Must not reintroduce a
  shell: the shell-execution gate is at a ceiling of zero.

---

## 8. Phase 5 — the residue (S2, D65)

- **S2** — `parse_agent_output` never raises, so a caller cannot distinguish
  "the model reported PARTIAL" from "we failed to parse". Reach is DEAD and
  its failures already write a distinguishing `reasoning` and
  `confidence=0.3`, so this is **low value**; the honest options are to fix
  it inside the Pydantic contract or to re-classify it `cleared` with that
  reasoning recorded. Do not leave it `open`.
- **D65** — the stress test fails ~1 run in 7 against its own comment
  predicting 1 in 2000. **Mechanism UNKNOWN**; two direct measurements
  exceeded their own time budget. Note that `tests/stress/` is referenced by
  **no workflow**, so it can never turn CI red and has zero regression
  protection. Two defensible actions: instrument the retry path to find the
  mechanism, or wire `tests/stress/` into CI *first* so the flake becomes
  visible before it is diagnosed. Widening the tolerance or raising the
  timeout without the mechanism is guessing, and the audit record says so.

---

## 9. Phase 6 — the two that cannot be fixed as recorded (D9, D10)

**D9 and D10 have no recorded claim.** W1 named only a region — *R6, secret
classification and event sanitisation* — and never wrote down an individual
defect. There is nothing to fix and nothing to refute.

The honest closure is not to fix them but to **re-run region R6 under the V3
protocol** and record whatever it finds under new ids, then close D9/D10 with
a verdict note saying the region was re-audited and the original claims were
never recorded. Anything else is bookkeeping theatre.

This is also the highest-uncertainty phase: R6 is a security region that no
wave has completed, so its yield is genuinely **UNKNOWN** and could exceed
the rest of this plan.

---

## 10. Sequencing

```
Phase 0  decision (fail-open policy)  ── informs ──┐
Phase 1  D69 seam proof  ─────────────────────────┼──► Phase 2  flows
                    │                              │    (S5,D70,D20,D21)
                    └── may surface D32 ──► Phase 3 persistence (D32,D34,D36)

Phase 4  resource & spend (D37,D38,D39,D44)   ── independent, parallelisable
Phase 5  residue (S2,D65)                     ── independent
Phase 6  re-audit R6 (D9,D10)                 ── independent, open-ended
```

**Phases 4, 5 and 6 touch no code that Phases 1–3 touch** and can run in any
order or concurrently. Phases 1 → 2 → 3 are ordered by dependency: Phase 1
proves the seam the flow work rests on, and its end-to-end test exercises the
persistence code Phase 3 audits.

**Per-phase exit gate**, unchanged from the protocol used for the 48 already
closed: red-before-green pasted into the audit, a six-vector RAR table,
`ruff --select F821,E9` clean, `lint-imports` 7 kept / 0 broken,
`make lint-unawaited` clean, all five ceilings unmoved, and the candidate
inventory test green.

---

## 11. What this plan will not do

- **It will not raise a ceiling.** If a fix needs one raised, it is the wrong
  fix.
- **It will not skip, disable or quarantine a test**, D65 included.
- **It will not decide Phase 0.** Three verification paths fail open today;
  whether they should is the user's call, and this plan deliberately does not
  make it.
- **It will not wire the state graph** without Phase 1's end-to-end test in
  place, whatever the user chooses in 5a.

## 12. Honest risk register

| Risk | Likelihood | Why it matters |
|---|---|---|
| **9 of 16 are HYPOTHESIS** — generated, never triggered | High that ≥1 is refuted | Two of the last three defects closed (D48, D12) had a **refuted** claim with the real defect nearby but unnamed. Expect the same here: budget for re-scoping, not just fixing. |
| **D69 comes back "the gates never worked"** | UNKNOWN | Would be more severe than anything else listed, and would mean D12/D67 shipped without effect. |
| **D21 is a real livelock** | Medium | A livelock in the flow's failure handler is a production-severity defect that W3 read and never triggered. |
| **Phase 6 (R6) is unbounded** | High | A security region no wave has finished. Its yield could exceed this entire plan; treat its scope as a discovery, not an estimate. |
| **Phase 2 option B is chosen** | — | Rewriting the resume path for every session is the single riskiest change available in this codebase. Only behind Phase 1. |
