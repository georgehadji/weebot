# ADR-012: Session-Scoped Side Constraints and the Executor Delivery Seam

**Date:** 2026-08-20
**Status:** Approved
**Owner:** weebot maintainers
**Supersedes:** N/A

---

## Context

A **side constraint** (SC) is a user-issued directive that governs *how* the
agent works rather than *what* it works on — "never delete anything under
`data/`", "show me the draft before sending", "reply in bullet points". It
applies for the rest of the session and is not task progress.

Wang et al., *Lost in Compaction* (arXiv:2608.11242), measures what happens to
such constraints when a long conversation is compacted. Two findings drive
this ADR:

- A constraint placed **immediately before the model's turn** (`K_ub`) gets
  **>98% compliance** for every downstream model tested. The same constraint
  left to survive compaction inside the transcript lands at **31.8–58.5%**.
- Position dominates. Top-of-context injection is the worst placement
  measured; bottom is the best.

**weebot's failure mode was worse than the paper's, and different in kind.**
An audit of the live execution path found that `ExecuteStepHandler` built
`ExecutorAgent(llm, tools, event_bus, model)` — 4 of the agent's 22
constructor parameters — and called `execute_step(plan, step)` positionally.
The user's own prompt never entered the acting model's message list at all.
That is not a low retention rate; it is the paper's `K_ub` condition *absent*.

The same audit found the surrounding machinery equally inert:
`BehavioralLearner`, `CorrectionTracker`, and `FSPermissionChecker` each had a
port, an implementation, and consumers, but **zero constructors anywhere in
`weebot/`**. The binding constraint was unwired code, not missing capability.

---

## Decision

### 1. Repair the executor seam before adding anything to it

`ExecuteStepHandler` takes an injected `ExecutorFactory`
(`Callable[..., ExecutorAgent]`) supplied by the composition root, rather than
constructing the agent itself.

**Rejected:** widening `ExecuteStepCommand` with the 18 missing parameters. A
command is a DTO describing *intent*; threading service references through it
turns it into a service locator, and `Command` is `frozen=True,
extra="forbid"` precisely to prevent that. Only `user_input` was added — it is
genuinely part of the intent and was reaching nothing.

This alone revived per-step context scoping, skill retrieval, harness blocks,
personality, user-profile injection, and middleware on the live path — none of
which is about constraints.

### 2. Constraints live outside the transcript

A `SessionConstraintRegistry` of immutable `SessionConstraint` value objects,
persisted in a `session_constraints` table and rebuilt per session.

**Rejected:** `Session.set_fact`. `SessionContext._cap_facts_dict` evicts in
insertion order at 100 facts, and re-assigning a key preserves its position —
so a registry created on turn 1 would be the **first** thing evicted, failing
in exactly the long sessions this work targets.

Storage that is not the transcript is the only design robust to compaction
*by construction*: a compactor cannot drop what it never held.

### 3. Delivery at the `K_ub` position

The rendered block is appended to the executor's local `messages` list as
`messages[-1]`, rebuilt fresh on every loop iteration.

It is **never** written to `_conversation_buffer`: that is a bounded deque
which `_maybe_compress` rewrites wholesale, so anything placed there is both
evictable and compactable — the failure this ADR exists to prevent. (The
buffer's size was separately found to be smaller than one step's tool budget,
which evicted the step description mid-step and split assistant/tool pairs
into provider-rejected orphans; it is now derived from that budget.)

Re-rendered once per model turn, not once per tool result. The paper's
Appendix E shows repetition saturating below 40% while one well-placed
statement reaches 49%; unbounded repetition buys nothing and costs tokens on
every iteration.

### 4. Extraction reads user turns only — a trust boundary

Constraints are extracted from `MessageEvent(role="user")` text and from
steering/resume text. **Never** from tool results or assistant turns.

This is not a quality preference. `atomic_mail` and MCP tools are classified
as untrusted output; without this rule, inbound email content could promote
itself into a block the model is told is a strict, session-long, user-issued
rule. The same hole was found and closed in `MemoryCompactor`, where tool
output was reaching the constraint extractor via `str(event)`.

Extraction is tiered — a free regex lexicon with an optional cheap-LLM tier —
mirroring `CorrectionTracker`. LLM absence *is* the tier signal.

### 5. Constraints carry a direction, and `loosen` never enforces

Every constraint is `TIGHTEN` (narrows what the agent may do) or `LOOSEN`
(widens it). Only `TIGHTEN` compiles into an enforcement gate.

The paper's SC#1 is *"Don't ask me to confirm before running commands, just do
them."* Losing that constraint is fail-safe. **Persisting** it as enforceable
means weebot carries a durable instruction against its own
`ExecApprovalPolicy` — and weebot's pre-existing constraint gate did exactly
that, pausing to ask for confirmation in order to "enforce" a constraint
against asking for confirmation.

`LOOSEN` constraints are rendered to the model, in a separate section framed
explicitly as latitude that never overrides a safety gate or approval
requirement. The common assumption that SC loss is monotonically
risk-increasing is wrong, and the direction field is where that is encoded.

### 6. The registry is not append-only

`revoke()` and `supersede()` are first-class, and the LLM tier may emit
removals.

Neither the paper nor the original design handled this. An append-only
registry still holds *"never delete without asking"* after the user says *"go
ahead, delete them"* — and because the block renders last and framed as
strict, the stale constraint **outranks the live user turn**. That converts a
recoverable omission into a persistent refusal, which is a worse failure than
the one the registry prevents.

### 7. Failure directions are opposite by layer

- **Extraction and hydration fail open.** A broken registry must never block
  the agentic loop.
- **Enforcement fails closed.** Unknown → require approval. Matches
  `WorkspaceDrift.is_clean` returning `False` when the check could not run,
  and `EgressGuard`'s `recipient is None → FIRST_TIME_RECIPIENT`.

### 8. No new port yet

The services take `state_repo: Any` and duck-type, following the
`CorrectionTracker` precedent. Adding a `ConstraintRegistryPort` beside an
already-dead `behavioral_learner_port.py` would repeat the failure this work
exists to fix. Revisit when a second adapter appears.

---

## Consequences

**Positive.** Constraints reach the acting model at the empirically-best
position and survive compaction by construction. Permission-widening
constraints can no longer reach a safety gate. Revocation works. The executor
seam repair revived six unrelated features on the live path. Three previously
dead services are wired, with their persistence and hydration bugs fixed.

**Negative.** One extra message per model turn. The heuristic extraction tier
has no measured precision, and a false positive becomes a *permanent*
session-scoped instruction — mitigated by the evidence-span field, revocation,
and the harness's negative cases, not eliminated.

**Since implemented.** `FSPermissionChecker` is now enforceable: its path
invariant accepts Windows and workspace-relative patterns, matching is
canonicalised so a rule cannot be evaded with `./`, `//` or `..`, rules load
from an optional `weebot/config/fs_permissions.yaml` (absent by default, so no
behaviour change), and the file tool acts on the verdict — failing closed on
`interrupt`, which has no approval channel at that layer.

**Deferred.** A human-in-the-loop path for `interrupt`-mode filesystem rules,
so a gated operation can be approved rather than merely refused. Automatic
promotion of a recurring session constraint into a durable behavioral rule
remains speculative and unimplemented.

---

## Limits of the evidence

Recorded so nobody over-trusts the source paper:

- **17% is not a general retention rate.** Every cell is measured at *top*
  injection, the worst position; the same compactors reach 38–100% at bottom
  injection. It is an unweighted mean over 8 hand-picked compactor configs
  including two that are 0% by construction.
- **`K_ub` is an oracle-adjacency ceiling.** The constraint sits immediately
  before the probe — the exact variable the paper elsewhere identifies as the
  dominant driver. It bounds what delivery can achieve; it is not evidence
  that a registry works at realistic distance.
- **"Compaction is worse than no compaction" holds for one prober.** Two of
  the three other downstream models tested invert it.
- **The extractor's 93.7% is recall on a planted string**, judged by the same
  LLM judge, on a document whose only content is constraints. No precision or
  false-positive rate is reported.
- **"Architectural separation, not better prompts" is the paper's thesis, not
  a controlled result.** Its extractor changes four things at once and ablates
  none. An SC-targeted compaction *prompt* is the largest prompt-level gain it
  reports (+23.5 / +34.3 pp) — which is why that shipped first, in two lines.

---

## Related

- Plan: `tasks/specs/side_constraint_integrity_plan.md`
- Domain model: `weebot/domain/models/session_constraint.py`
- Persistence: `weebot/infrastructure/persistence/_session_constraint_repo.py`
- Extraction: `weebot/application/services/session_constraint_extractor.py`
- Accumulation: `weebot/application/flows/collaborators/session_constraint_accumulator.py`
- Delivery: `weebot/application/agents/executor/_base.py`
- Executor seam: `weebot/application/cqrs/handlers/execute_step_handler.py`
- Enforcement: `weebot/application/services/constraint_compilers.py`,
  `weebot/application/flows/states/executing.py`
- Regression harness: `weebot/config/harness/side_constraints.yaml`,
  `tests/unit/test_side_constraint_harness.py`
- ADR-007 — the closest precedent for trust-boundary and write-gating work
