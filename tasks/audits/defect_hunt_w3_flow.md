# Wave 3 — Flow State Machine & Concurrency

Execution record for W3 of [`tasks/specs/defect_hunt_v7_execution_plan.md`](../specs/defect_hunt_v7_execution_plan.md).
Threats **T5** (state corruption) and **T6** (liveness); classes **C6**, **C7**, **C5**.

The plan predicted this wave would carry a high `[UNK]` residual, because concurrency
interleavings are the canonical thing that cannot be decided statically. It does.

---

## Phase 0-WAVE

| | |
|---|---|
| **Baseline** | `43f1f21`, working tree clean, all 8 CI checks green. |
| **Budget** | ≤20 generated · ≤12 investigated · ≤8 fixed |
| **Actually spent** | 11 generated · 5 investigated · 3 fixed |

---

## Phase 3/4 — triaged inventory

| ID | Claim | Trigger (3a) | Innocence (3b) | Verdict |
|---|---|---|---|---|
| **D25** | `subscribe_by_type` appends a closure, so `unsubscribe(handler)` can never remove it | **FIRED** — 100 cycles retained 100 handlers, and the unsubscribed handler kept receiving events | **No defence** — `broker_adapter.py:60` documents this exact call as the way to unsubscribe | ✅ **VERIFIED DEFECT** |
| **D27** | `recent()` indexes a `defaultdict`, inserting a permanent empty deque per unknown project | **FIRED** — 50 reads → 50 permanent entries | **Partial**: the only caller passes `orchestrator_id`, so the set is bounded in practice | ✅ **VERIFIED DEFECT** — low reachability |
| **D19** | `status = None` on a field typed `AgentStatus`; `getattr` default does not rescue it | **FIRED** — `MetaAnalysisState.status is None`, resolves to `None` | **Partial**: no consumer reaches for `.value` today; the only reader is `self.status == AgentStatus.IDLE`, which is merely `False` | ✅ **VERIFIED** — latent consequence |
| **D22** | `else: # "reject"` silently marks any unrecognised verdict FAILED | not run | **Defended, conclusively** — `CodeReviewResult.verdict` is `Literal["approved", "revise", "reject"]`, Pydantic-validated, so the `else` is exhaustive by construction | ⚪ **FALSE** |
| **D24** | `subscribe`/`unsubscribe` mutate `_handlers` without `self._lock` | **N=200 same-loop + N=200 cross-thread: 0 failures** | Sync mutators contain no `await`, so they cannot interleave with the coroutine snapshot; under CPython `list.append`/`remove`/`list()` are individually atomic | 🔵 **STATISTICAL — no failure observed.** `[HYP]`, **not** proven innocent |

### D25 is the serious one, and it is not just a leak

`subscribe_by_type` wraps the caller's handler in a `filtered_handler` closure and appends *that*.
`unsubscribe(handler)` tests `if handler in self._handlers` — the closure is not the handler, so
nothing matches and the call **silently does nothing**. The consequence is not only unbounded
growth; the handler the caller believes it removed **keeps receiving every event**.

`infrastructure/events/broker_adapter.py:60-61`, the EventBroker→AsyncEventBus migration shim,
tells callers:

> *"To unsubscribe, call unsubscribe() with the **same handler reference**."*

That is precisely the operation that could not work. The adapter documents a contract its
implementation cannot honour.

### D27 and D19 are real but latent — recorded honestly

Neither has a live exploit path. `recent()`'s only caller passes a bounded `orchestrator_id`,
and nothing reads `flow.status.value`. Both were fixed anyway: a read that allocates and a field
that violates its own declared type are defects whose cost is paid by the next caller, and both
fixes are one line.

### D22 is the wave's best news

A missing default case that **cannot be reached**, because the type closes it. This is the
correct way to eliminate the defect class, and it is worth naming as the pattern the rest of the
state machine should follow.

---

## Phase 5 — fixes

| # | File | Change | Lines |
|---|---|---|---|
| 1 | `infrastructure/event_bus.py` | Tag the wrapper with `_wrapped_handler`; `unsubscribe` matches the handler *or* its wrapper | +13 incl. comment |
| 2 | `core/activity_stream.py` | `self._by_project.get(project_id, ())` instead of `[project_id]` | +4 |
| 3 | `flows/states/meta_analysis.py` | `status: AgentStatus = AgentStatus.SUMMARIZING` (+ import) | +8 incl. comment |

**A deliberate semantic choice in fix 1.** `unsubscribe` now removes *every* registration for a
handler, where it previously removed the first match only. The signature carries no event type,
so there is no coherent way to say which one to keep — and the old behaviour was already wrong
for the wrapped case. Verified not to over-remove: an unrelated subscriber survives
(`test_unsubscribing_one_handler_leaves_others_subscribed`).

**Fix 3 applies the file's own comment.** The code read
`status = None  # Intentionally None`, directly under a comment saying *"use SUMMARIZING as a
reasonable neighbor."* The comment described a fix that had never been applied.

### Architecture invariants (plan §6)

1 `lint-imports` 7/7 KEPT · 2 no new `ignore_imports` · 3 domain untouched · 6 no port signature
changed · 7 no Pydantic widening · 8 no new subprocess site · 10 fixes and proof tests in one
commit. All ✅.

---

## Phase 6 — six-vector self-review

| Vector | Finding |
|---|---|
| **Boundary** | `[VF]` `unsubscribe` on a never-subscribed handler is a no-op. `recent()` for a known project still filters correctly. |
| **Invalid input** | `[VF]` `getattr(registered, "_wrapped_handler", None)` is safe for handlers that carry no such attribute (every `subscribe()` handler). |
| **State** | `[VF]` `_by_project` no longer grows on reads; `push()` still creates entries, which is correct. |
| **Regression** | `[VF]` Type filtering still applies; unrelated subscribers survive an unsubscribe; full suite green. |
| **Concurrency** | `[VF]` The new `unsubscribe` iterates `list(self._handlers)` — a copy — so it cannot mutate during its own iteration. Re-verified by the D24 harness at N=200×2, 0 failures. |
| **New defects** | `[HYP]` Setting an attribute on a coroutine function is legal but unusual; a handler wrapped by something that copies without `__dict__` would lose the tag. No such wrapper exists in this codebase — not verified beyond it. |

---

## Phase 7 — tests

`tests/unit/test_w3_flow_state_and_subscription.py`, **11 tests, new file**: proof-of-defect for
all three, plus no-regression (type filtering, selective unsubscribe, known-project reads) and
boundary cases.

**Red before, green after, verified by reverting:** the three production files stashed →
**5 failed / 6 passed**; restored → **11 passed**.

`test_no_state_declares_a_non_status` is the generalising gate: it walks every `FlowState`
subclass in the states package and asserts each declares a real `AgentStatus`, so the next state
to be added cannot reintroduce D19. `test_the_scan_finds_states` guards the guard — an empty scan
would make the assertion vacuous.

---

## Phase 8 — coverage & residual-risk statement

### Covered

Five candidates investigated to a verdict. Three defects fixed and proven, one candidate cleared
conclusively, one bounded statistically.

### NOT covered — stated plainly

The W3 surface names `plan_act_flow.py` (965 LOC), **all 14 modules** under `flows/states/`,
`base_flow.py`, `_checkpoint_scheduler.py`, `_iteration_context.py`, `agent_session_manager.py`,
`flows/collaborators/`, `chat_flow.py` and `hyper_agent_flow.py`. **Three modules were
investigated.** Of the five declared regions, only *transition-table completeness* (via D22/D19)
and part of *shared mutable state* (D24/D25/D27) were touched at all.

Never investigated:

- **S5** — the plan's own executably-verified seed: *both* declared transition tables
  (`flow_state_machine.py:21-33`, `state_graph.py:91-154`) are dead code, with ~40 imperative
  `context.set_state(...)` calls holding the real authority, and `flow_router.py:95-168`
  duplicating the same priorities. This is the largest structural finding in the wave's scope and
  **it was not addressed**.
- **D20** (terminate-with-next-step returns without `set_state`, so `prompt_consumed` is never
  reset) — a C7 candidate on the hottest path in the flow.
- **D21** (`UpdatePlanCommand` failure → `ExecutingState` re-runs the same failing step; livelock
  bounded only by `max_iterations`).
- **D23** (`get_event_loop()` + `create_task` from the watchdog observer thread, swallowed).
- **D26** (`_ws_lock` held across a timeout-less send loop — one hung client stalls every
  subscriber). This is the wave's most plausible **T6 liveness** defect and it was not triggered.
- **D28** (`input()` inside `async def` — blocks the whole event loop).
- **D29** (`t.exception()` in a done-callback raises `CancelledError`).
- **D12/R7** (inbound-mail flag cleared before the pause it gates), cross-listed from W1 and still
  `[UNK]` on the resume path.
- Orphaned `asyncio` tasks on error paths, and checkpoint-vs-mutation ordering (TOCTOU): **neither
  region was entered.**

### Residual risks

- **R-1 — D24 is bounded, not cleared.** 400 trials without failure bounds an observable rate; it
  is not a proof of thread-safety. The mechanistic argument (no `await` in the sync mutators, GIL
  atomicity of the list operations) is the stronger evidence, and it is still reasoning, not
  measurement. If `subscribe` ever gains an `await`, the argument collapses silently.
- **R-2 — the `_wrapped_handler` tag is a convention, not a type.** Nothing enforces that a future
  wrapper sets it. A registration object holding `(original, wrapper, event_type)` would be
  structural rather than conventional, and is the better long-term shape.
- **R-3 — `unsubscribe` removing all registrations is a behaviour change.** Justified above, and
  covered by a test, but any caller that deliberately double-subscribed and expected to remove one
  registration at a time is now wrong. No such caller exists in this repository; external
  consumers of `EventBusPort` are `[UNK]`.
- **R-4 — the dead transition tables (S5) remain.** Two declared state machines that do not
  execute, next to ~40 imperative transitions that do, is a standing invitation for the
  documentation and the behaviour to drift apart. Untouched by this wave.

### Verdict

**PARTIAL**, and more partial than W1 or W2. Three verified defects fixed with a generalising
gate, one candidate cleared, one bounded statistically — but three modules of a surface naming
twenty-plus, two of five regions entered, and the wave's own headline seed (S5) never opened.
