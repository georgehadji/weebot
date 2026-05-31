# SkillOpt Implementation Plan — Weebot v2.8

**Source:** Yang et al., _SkillOpt: Executive Strategy for Self-Evolving Agent Skills_ (arXiv:2605.23904v2, May 2026)  
**Target:** Weebot AI Agent Framework — Clean Architecture + CQRS + Event-Driven  
**Date:** 2026-05-28  
**Status:** Draft · Awaiting approval

---

## Table of Contents

1. [Architectural Principles](#1-architectural-principles)
2. [Domain Model Extensions](#2-domain-model-extensions)
3. [Phase 1 — Trajectory Evidence Pipeline](#3-phase-1--trajectory-evidence-pipeline)
4. [Phase 2 — Validation Gate](#4-phase-2--validation-gate)
5. [Phase 3 — Bounded Skill Edit Operations](#5-phase-3--bounded-skill-edit-operations)
6. [Phase 4 — Optimizer Model Interface](#6-phase-4--optimizer-model-interface)
7. [Phase 5 — Optimization Epoch Loop](#7-phase-5--optimization-epoch-loop)
8. [Phase 6 — Cross-Model / Cross-Harness Transfer](#8-phase-6--cross-model--cross-harness-transfer)
9. [Dependency Injection Bindings](#9-dependency-injection-bindings)
10. [Testing Strategy](#10-testing-strategy)
11. [File Manifest](#11-file-manifest)

---

## 1. Architectural Principles

Every change in this plan obeys the following rules, enforced by the architecture audit
(fd12e8a, 2026-05-28) and the CQRS wiring remediation (ba9031f):

| Rule | Enforcement |
|------|-------------|
| **Dependency direction inward** | Domain imports nothing from outer layers. Application imports only ports from infrastructure (lazy). |
| **CQRS for writes** | Every state mutation goes through `mediator.send(Command)`. Pipeline behaviours (logging, validation, telemetry) activate automatically. |
| **Port/adapter for I/O** | `LLMPort`, `EventBusPort`, `StateRepositoryPort`, `EventStorePort` (new) define boundaries. Concrete adapters live in `infrastructure/`. |
| **Domain events for cross-boundary signalling** | `FactDiscovered`, `PlanStepCompleted`, and new `SkillEditAccepted`, `SkillEditRejected`, `EpochCompleted` are published on `EventBusPort`. |
| **Pydantic for domain models** | All domain objects are immutable `BaseModel` subclasses with `model_copy(update=…)`. |
| **DI container for wiring** | `application/di.py` provides the single composition root. No ad-hoc `new Foo()` in constructors. |

---

## 2. Domain Model Extensions

### 2.1 New domain events (`weebot/domain/models/event.py`)

```python
class TrajectoryScored(DomainEvent):
    """Emitted when a task execution completes with a benchmark score."""
    type: str = "trajectory_scored"
    session_id: str
    task_id: str
    score: float                    # 0.0–1.0
    failure_modes: list[str]        # e.g. ["wrong_tool_choice", "format_error"]
    success_patterns: list[str]     # e.g. ["verified_output", "correct_ordering"]
    trajectory_summary: str         # Compact natural-language summary for optimizer
    harness: str                    # "direct_chat" | "codex" | "claude_code"

class SkillEditProposed(DomainEvent):
    """Emitted when the optimizer proposes an edit to a skill."""
    type: str = "skill_edit_proposed"
    skill_name: str
    skill_version: int
    edit: "SkillEdit"               # The proposed edit (see §5)
    support_count: int
    source_type: str                # "failure" | "success"

class SkillEditAccepted(DomainEvent):
    """Emitted when a proposed edit passes the validation gate."""
    type: str = "skill_edit_accepted"
    skill_name: str
    old_version: int
    new_version: int
    validation_score_delta: float   # Positive = improvement
    edit: "SkillEdit"

class SkillEditRejected(DomainEvent):
    """Emitted when a proposed edit fails the validation gate."""
    type: str = "skill_edit_rejected"
    skill_name: str
    skill_version: int
    score_drop: float               # How much worse the candidate was
    edit: "SkillEdit"
    failure_analysis: str           # Why the optimizer thinks it failed

class EpochCompleted(DomainEvent):
    """Emitted at the end of an optimization epoch."""
    type: str = "epoch_completed"
    skill_name: str
    epoch: int
    best_validation_score: float
    edits_accepted: int
    edits_rejected: int
    slow_update_applied: bool
```

### 2.2 Skill model extensions (`weebot/domain/models/skill.py`)

Extend the existing `Skill` model with optimization state:

```python
class SkillVersion(BaseModel):
    """Immutable snapshot of a skill at a point in time."""
    version: int
    content: str
    validation_score: Optional[float] = None
    accepted_at: Optional[datetime] = None
    edit_history: list["SkillEditRecord"] = Field(default_factory=list)

class SkillEditRecord(BaseModel):
    """Audit trail entry for one atomic edit."""
    op: Literal["append", "insert_after", "replace", "delete"]
    target: Optional[str] = None
    content: str
    support_count: int
    source_type: Literal["failure", "success"]
    accepted: bool
    score_delta: Optional[float] = None
    applied_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Skill(BaseModel):  # extended from existing
    # ... existing fields (name, description, content, metadata, source_path) ...

    # NEW — optimization state
    versions: list[SkillVersion] = Field(default_factory=list)
    current_version: int = 0
    best_version: int = 0           # Index into versions[]
    slow_update_content: str = ""   # Protected section (SLOW_UPDATE_START/END)
    rejected_edit_buffer: list[SkillEditRecord] = Field(
        default_factory=list, max_length=32
    )
    meta_skill: str = ""            # Optimizer-side coaching (not deployed)

    @property
    def current(self) -> SkillVersion:
        return self.versions[self.current_version]

    @property
    def best(self) -> SkillVersion:
        return self.versions[self.best_version]

    def apply_edits(self, edits: list[SkillEdit], budget: int) -> "Skill":
        """Apply bounded edits, return new Skill with incremented version."""
        ...

    def accept_candidate(self, version_idx: int) -> "Skill":
        """Accept a candidate version as current. Update best if score improved."""
        ...

    def export_best(self) -> str:
        """Export best_skill.md as a deployable markdown string."""
        ...
```

### 2.3 Trajectory model (`weebot/domain/models/trajectory.py`) — NEW FILE

```python
class TrajectorySummary(BaseModel):
    """Compact representation of a single task execution for the optimizer.

    This is what the optimizer model sees — not the full event stream.
    Typical size: 500–2000 tokens per trajectory.
    """
    task_id: str
    session_id: str
    skill_name: str
    skill_version: int
    harness: str                     # "direct_chat" | "codex" | "claude_code"
    score: float                     # 0.0–1.0, benchmark-native
    passed: bool
    failure_modes: list[str]
    success_patterns: list[str]
    tool_call_count: int
    total_tokens: int
    total_cost: float
    trajectory_text: str             # Compact natural-language trace
    answer: Optional[str] = None
    expected_answer: Optional[str] = None

class OptimizationBatch(BaseModel):
    """A batch of trajectories for one optimizer step."""
    skill_name: str
    skill_version: int
    trajectories: list[TrajectorySummary]
    batch_score: float               # Average score
    failure_count: int
    success_count: int
```

---

## 3. Phase 1 — Trajectory Evidence Pipeline

**Goal:** Attach structured scores and failure analysis to every completed task
execution so the optimizer has raw material to work with.

**Duration:** Week 1–2  
**Files touched:** 5 new, 3 modified

### 3.1 New files

| File | Layer | Purpose |
|------|-------|---------|
| `domain/models/trajectory.py` | Domain | `TrajectorySummary`, `OptimizationBatch` |
| `application/ports/event_store_port.py` | Application | `EventStorePort` — abstraction over the SQLite event store |
| `infrastructure/persistence/trajectory_repo.py` | Infrastructure | `TrajectoryRepository` — stores/retrieves `TrajectorySummary` rows |
| `application/services/trajectory_builder.py` | Application | `TrajectoryBuilder` — converts `Session` → `TrajectorySummary` via LLM-assisted failure analysis |
| `application/cqrs/commands/trajectory_commands.py` | Application | `ScoreTrajectoryCommand`, `BuildOptimizationBatchCommand` |

### 3.2 Modified files

| File | Change |
|------|--------|
| `domain/models/event.py` | Add `TrajectoryScored` event |
| `application/flows/states/completed.py` | After `DoneEvent`, emit `TrajectoryScored` with benchmark score |
| `infrastructure/event_store.py` | Add `save_trajectory()` / `get_trajectories_by_skill()` methods |

### 3.3 Design decisions

**Scoring is harness-specific.** The `CompletedState` calls a `ScoreProvider` port that
each harness (direct chat, Codex, Claude Code) implements. The port is defined in
`application/ports/scoring_port.py`:

```python
class ScoringPort(ABC):
    @abstractmethod
    async def score(self, session: Session, expected_answer: Optional[str]) -> TrajectoryScored:
        ...
```

**Failure analysis uses a lightweight LLM call.** The `TrajectoryBuilder` sends the
compact trajectory text to a fast model (e.g., GPT-4o-mini) with a structured prompt
that classifies failure modes. This costs ~$0.001 per trajectory and runs after the
session completes.

**Event store gets a port.** The existing `EventStore` is accessed directly. We wrap it
behind `EventStorePort` so the trajectory pipeline can be tested with an in-memory store.

### 3.4 CQRS integration

```
CompletedState.execute()
  → yields DoneEvent
  → mediator.send(ScoreTrajectoryCommand(session_id, harness, expected_answer))
    → ScoreTrajectoryHandler
      → ScoringPort.score()
      → EventStorePort.save_trajectory()
      → EventBusPort.publish(TrajectoryScored)
```

When enough trajectories accumulate for a skill version:

```
mediator.send(BuildOptimizationBatchCommand(skill_name, skill_version, batch_size))
  → BuildOptimizationBatchHandler
    → TrajectoryRepository.get_by_skill_version()
    → returns OptimizationBatch
```

---

## 4. Phase 2 — Validation Gate

**Goal:** Every candidate skill edit must improve a held-out selection split before being
accepted. This is the paper's key differentiator — without it, plausible-but-harmful edits
accumulate and scores drop 2–5 points (Table 3).

**Duration:** Week 2–3  
**Files touched:** 4 new, 2 modified

### 4.1 New files

| File | Layer | Purpose |
|------|-------|---------|
| `application/cqrs/commands/validation_commands.py` | Application | `ValidateSkillCommand` |
| `application/cqrs/handlers/validation_handler.py` | Application | `ValidateSkillHandler` |
| `application/services/validation_runner.py` | Application | Orchestrates parallel validation task runs |
| `infrastructure/persistence/skill_store.py` | Infrastructure | `SkillStore` — persists `Skill` models with version history |

### 4.2 Modified files

| File | Change |
|------|--------|
| `domain/models/skill.py` | Add versioning fields (see §2.2) |
| `application/di.py` | Register `SkillStore`, `ValidationRunner`, validation handler |

### 4.3 Design decisions

**Validation uses the same harness as training.** If training runs on Codex, validation
also runs on Codex — but on a disjoint task split. This ensures the gate measures genuine
generalization, not overfitting to training tasks.

**Ties are rejected.** The paper's rule: score must be _strictly greater_ than the current
selection score. Ties (equal score) count as rejections. This prevents the optimizer from
churning on neutral edits.

**Parallel validation.** `ValidationRunner` fans out validation tasks across the `TaskRunner`
queue. A batch of 20 validation tasks completes in roughly the time of the single slowest
task, not 20× that time.

**Validation gate is a pipeline behaviour.** Register `ValidationGateBehavior` on the
mediator so that _any_ command that produces a candidate skill edit automatically passes
through the gate:

```python
class ValidationGateBehavior(IPipelineBehavior):
    async def handle(self, request, next_callable):
        result = await next_callable()
        if isinstance(request, ApplySkillEditsCommand):
            candidate = result.data["candidate_skill"]
            validation = await self._runner.validate(candidate, request.validation_tasks)
            if not validation.passed:
                result = CommandResult.fail(
                    error=f"Validation gate rejected: Δ={validation.score_delta:.3f}",
                    error_code="VALIDATION_GATE_REJECTED",
                    data={"rejected_edit": request.edits, "score_delta": validation.score_delta},
                )
        return result
```

### 4.4 CQRS integration

```
OptimizerAgent proposes edits
  → mediator.send(ApplySkillEditsCommand(skill_name, edits, budget, validation_tasks))
    → pipeline: LoggingBehavior → ValidationGateBehavior → ApplySkillEditsHandler
      → Skill.apply_edits()
      → ValidationRunner.validate(candidate_skill, validation_tasks)
        → for each task: TaskRunner.enqueue_session() → await results
        → compare avg scores: candidate vs current
        → return ValidationResult(passed=True/False, score_delta=…)
      → if passed: EventBusPort.publish(SkillEditAccepted)
      → if rejected: EventBusPort.publish(SkillEditRejected); update rejected_edit_buffer
```

---

## 5. Phase 3 — Bounded Skill Edit Operations

**Goal:** Model skill mutations as four atomic operations (`append`, `insert_after`,
`replace`, `delete`) with audit trails, support counts, and textual learning-rate budgets.
This replaces ad-hoc string rewriting with surgical, auditable edits.

**Duration:** Week 3–4  
**Files touched:** 3 new, 1 modified

### 5.1 New files

| File | Layer | Purpose |
|------|-------|---------|
| `application/cqrs/commands/skill_edit_commands.py` | Application | `ApplySkillEditsCommand` |
| `application/cqrs/handlers/skill_edit_handler.py` | Application | `ApplySkillEditsHandler` |
| `domain/models/skill_edit.py` | Domain | `SkillEdit` value object |

### 5.2 Modified files

| File | Change |
|------|--------|
| `domain/models/skill.py` | Add `apply_edits()` method with budget enforcement; protected section guard |

### 5.3 SkillEdit model

```python
class SkillEdit(BaseModel):
    """One atomic operation on a skill document."""
    op: Literal["append", "insert_after", "replace", "delete"]
    target: Optional[str] = None        # Section header or line anchor (for insert_after/replace/delete)
    content: str                         # Markdown content to insert/replace
    support_count: int = 1               # How many trajectory analyses support this edit
    source_type: Literal["failure", "success"]

    def apply(self, skill_content: str) -> str:
        """Apply this edit to a skill document string."""
        if self.op == "append":
            return skill_content + "\n\n" + self.content
        elif self.op == "insert_after" and self.target:
            # Insert content after the first line containing target
            ...
        elif self.op == "replace" and self.target:
            # Replace the section starting with target
            ...
        elif self.op == "delete" and self.target:
            # Remove the section starting with target
            ...
        return skill_content
```

### 5.4 Protected section mechanism

The skill document contains a delimited section that only the epoch-boundary slow-update
process can modify:

```markdown
<!-- SLOW_UPDATE_START -->
Longitudinal guidance from epoch comparison.
Step-level edits MUST NOT modify this section.
<!-- SLOW_UPDATE_END -->
```

`Skill.apply_edits()` rejects any edit whose `target` falls within these markers.
Only `Skill.apply_slow_update()` (called at epoch boundaries) can modify this section.

### 5.5 Textual learning rate (edit budget)

`ApplySkillEditsCommand.edit_budget` (the paper's \( L_t \)) controls how many edits
are applied per step. The handler:

1. Sorts edits by `support_count` descending
2. Takes the top `edit_budget` edits
3. Applies them sequentially
4. Returns the candidate skill

The budget follows a cosine schedule managed by the epoch loop (see §7).

---

## 6. Phase 4 — Optimizer Model Interface

**Goal:** A separate frontier model (the "optimizer") analyzes trajectory evidence
and proposes structured edits. It never touches the target model — it only sees
`TrajectorySummary` objects and the current skill document.

**Duration:** Week 5–6  
**Files touched:** 5 new, 1 modified

### 6.1 New files

| File | Layer | Purpose |
|------|-------|---------|
| `application/agents/optimizer_agent.py` | Application | `OptimizerAgent` — the reflection/merge/rank engine |
| `application/ports/optimizer_port.py` | Application | `OptimizerPort` — abstract interface for the optimizer |
| `application/services/reflection_engine.py` | Application | `ReflectionEngine` — minibatch reflection orchestration |
| `application/services/merge_engine.py` | Application | `MergeEngine` — hierarchical merge of failure + success edits |
| `application/services/ranking_engine.py` | Application | `RankingEngine` — rank edits by expected utility under budget |

### 6.2 Modified files

| File | Change |
|------|--------|
| `application/di.py` | Register `OptimizerAgent` with a separate `LLMPort` binding (stronger model, higher reasoning effort) |

### 6.3 OptimizerAgent design

```python
class OptimizerAgent:
    """Frontier model that proposes skill edits from trajectory evidence.

    This agent is NEVER deployed with the target model. It runs offline
    during optimization epochs and produces structured edit proposals.
    """

    def __init__(
        self,
        optimizer_llm: LLMPort,         # Stronger model (e.g., Claude Opus 4.6)
        event_bus: EventBusPort,
    ):
        ...

    async def reflect_on_failures(
        self, batch: OptimizationBatch, current_skill: Skill
    ) -> list[SkillEdit]:
        """Minibatch reflection over failure trajectories.

        Uses prompt: reflection_failure.md (from SkillOpt Appendix C.2.1)
        Partitions failures into minibatches of size Bm, runs parallel
        analyst workers, returns corrective edits.
        """
        ...

    async def reflect_on_successes(
        self, batch: OptimizationBatch, current_skill: Skill
    ) -> list[SkillEdit]:
        """Minibatch reflection over success trajectories.

        Uses prompt: reflection_success.md (Appendix C.2.2)
        Preserves patterns that already work.
        """
        ...

    async def merge_edits(
        self, failure_edits: list[SkillEdit], success_edits: list[SkillEdit]
    ) -> list[SkillEdit]:
        """Hierarchical merge: failure edits first, deduplicate, resolve conflicts.

        Three-stage merge:
        1. merge_failure.md — consolidate failure proposals
        2. merge_success.md — consolidate success proposals
        3. merge_final.md — combine with failure priority
        """
        ...

    async def rank_edits(
        self, edits: list[SkillEdit], budget: int, current_skill: Skill
    ) -> list[SkillEdit]:
        """Rank edits by: systematic impact > complementarity > generality > actionability.

        Uses prompt: ranking.md (Appendix C.2.6)
        Returns top 'budget' edits in priority order.
        """
        ...

    async def slow_update(
        self,
        prev_skill: Skill,
        curr_skill: Skill,
        longitudinal_data: list[tuple[TrajectorySummary, TrajectorySummary]],
    ) -> str:
        """Epoch-boundary slow update: longitudinal comparison of adjacent epochs.

        Uses prompt: slow_update.md (Appendix C.2.7)
        Returns guidance text for the protected SLOW_UPDATE section.
        """
        ...

    async def meta_skill(
        self,
        prev_skill: Skill,
        curr_skill: Skill,
        longitudinal_data: list[tuple[TrajectorySummary, TrajectorySummary]],
    ) -> str:
        """Optimizer-side meta-coaching (not deployed).

        Uses prompt: meta_skill.md (Appendix C.2.8)
        Returns guidance for future optimizer calls.
        """
        ...
```

### 6.4 Prompt management

All optimizer prompts are stored as `.md` files in `weebot/application/skills/builtin/optimizer/`,
loaded by the `SkillRegistry`, and injected as system prompts:

```
weebot/application/skills/builtin/optimizer/
├── reflection_failure.md      # Appendix C.2.1
├── reflection_success.md      # Appendix C.2.2
├── merge_failure.md           # Appendix C.2.3
├── merge_success.md           # Appendix C.2.4
├── merge_final.md             # Appendix C.2.5
├── ranking.md                 # Appendix C.2.6
├── slow_update.md             # Appendix C.2.7
└── meta_skill.md              # Appendix C.2.8
```

This makes prompts version-controllable, auditable, and independently testable — the
paper's prompts can be copied verbatim as starting points, then refined per domain.

### 6.5 Model separation

The optimizer model is configured separately from the target model:

```python
# In application/di.py
container.register(
    "optimizer_llm",
    lambda: create_adapter("anthropic", model="claude-sonnet-4.6"),  # Strong reasoning
)
container.register(
    "target_llm",
    lambda: create_adapter("openrouter", model=os.getenv("DEFAULT_MODEL", "openrouter/auto")),
)
```

The paper uses a frontier model for the optimizer and tests target models from GPT-5.5
down to Qwen-3.5-4B. The optimizer being stronger than the target is intentional —
stronger reasoning about edits produces better skills for weaker target models.

---

## 7. Phase 5 — Optimization Epoch Loop

**Goal:** Orchestrate the full training loop from Figure 2 of the paper: rollout →
reflection → merge → rank → apply → validate → accept/reject → slow_update.

**Duration:** Week 7–8  
**Files touched:** 4 new, 2 modified

### 7.1 New files

| File | Layer | Purpose |
|------|-------|---------|
| `application/flows/skill_opt_flow.py` | Application | `SkillOptFlow(BaseFlow)` — the epoch loop |
| `application/flows/states/rollout.py` | Application | `RolloutState` — runs training batch |
| `application/flows/states/reflect.py` | Application | `ReflectState` — calls OptimizerAgent |
| `application/flows/states/validate.py` | Application | `ValidateState` — runs validation gate |

### 7.2 Modified files

| File | Change |
|------|--------|
| `application/di.py` | Register `SkillOptFlow`, learning-rate scheduler |
| `interfaces/cli/agent_runner.py` | Add `run_optimization_epoch()` entry point |

### 7.3 Learning rate scheduler

The paper's cosine schedule with floor:

```python
class LearningRateScheduler:
    """Textual learning rate (edit budget) scheduler."""
    
    def __init__(self, initial: int = 8, floor: int = 2, schedule: str = "cosine"):
        self.initial = initial
        self.floor = floor
        self.schedule = schedule
    
    def budget_for_step(self, step: int, total_steps: int) -> int:
        if self.schedule == "constant":
            return self.initial
        elif self.schedule == "cosine":
            progress = step / max(total_steps, 1)
            lr = self.floor + 0.5 * (self.initial - self.floor) * (1 + math.cos(math.pi * progress))
            return max(self.floor, int(round(lr)))
        # ... linear, autonomous variants
```

### 7.4 SkillOptFlow pseudocode

```python
class SkillOptFlow(BaseFlow):
    """Paper Figure 2 — optimization epoch loop."""

    async def run(self, prompt: str) -> AsyncGenerator[AgentEvent, None]:
        skill = await self._skill_store.load(self._skill_name)
        scheduler = LearningRateScheduler(initial=8, floor=2, schedule="cosine")

        for epoch in range(self._epochs):
            # 1. ROLLOUT — run target model on training batch
            batch = await self._rollout_state.execute(skill, self._training_tasks)

            # 2. REFLECT — optimizer proposes edits
            failure_edits = await self._optimizer.reflect_on_failures(batch, skill)
            success_edits = await self._optimizer.reflect_on_successes(batch, skill)

            # 3. MERGE — hierarchical merge
            merged = await self._optimizer.merge_edits(failure_edits, success_edits)

            # 4. RANK — clip to budget
            budget = scheduler.budget_for_step(epoch * steps_per_epoch, total_steps)
            ranked = await self._optimizer.rank_edits(merged, budget, skill)

            # 5. APPLY + VALIDATE — through CQRS mediator (gate auto-fires)
            result = await self._mediator.send(
                ApplySkillEditsCommand(
                    skill_name=skill.name,
                    edits=ranked,
                    budget=budget,
                    validation_tasks=self._validation_tasks,
                )
            )

            if result.success:
                skill = result.data["updated_skill"]
                yield SkillEditAccepted(...)
            else:
                # Gate rejected — edit goes to rejected-edit buffer
                yield SkillEditRejected(...)

            # 6. EPOCH BOUNDARY — slow update + meta skill
            if epoch > 0:
                longitudinal = await self._collect_longitudinal(prev_skill, skill)
                slow = await self._optimizer.slow_update(prev_skill, skill, longitudinal)
                meta = await self._optimizer.meta_skill(prev_skill, skill, longitudinal)
                skill = skill.apply_slow_update(slow)
                skill = skill.model_copy(update={"meta_skill": meta})
                await self._skill_store.save(skill)

            prev_skill = skill
            yield EpochCompleted(...)

        # Export
        best = skill.export_best()
        await self._skill_store.export_best_md(skill.name, best)
        yield DoneEvent()
```

### 7.5 Parallel rollout

The paper uses 16 analyst workers for reflection. Weebot's `TaskRunner` already supports
concurrent session execution via `asyncio.create_task`. The `RolloutState` enqueues all
training tasks simultaneously:

```python
class RolloutState(FlowState):
    async def execute(self, context, prompt):
        tasks = [
            context._task_runner.enqueue_session(
                Session(id=f"rollout-{i}", ...),
                flow_factory=context._flow_factory,
            )
            for i, task in enumerate(context._training_tasks)
        ]
        results = await asyncio.gather(*tasks)
        return OptimizationBatch(trajectories=[...])
```

---

## 8. Phase 6 — Cross-Model / Cross-Harness Transfer

**Goal:** Skills optimized on one (model, harness) pair transfer to others with
positive gains — the paper's deployment story (Table 4).

**Duration:** Week 9  
**Files touched:** 2 new, 1 modified

### 8.1 New files

| File | Layer | Purpose |
|------|-------|---------|
| `application/cqrs/commands/transfer_commands.py` | Application | `ValidateTransferCommand` |
| `application/cqrs/handlers/transfer_handler.py` | Application | `ValidateTransferHandler` |

### 8.2 Modified files

| File | Change |
|------|--------|
| `domain/models/skill.py` | Add `transfer_scores: dict[str, float]` — keyed by `"model:harness"` |

### 8.3 Design

**Transfer validation uses the same validation gate.** Run the skill on a target
(model, harness) pair with the validation task split. Compare against the target's
no-skill baseline. The paper reports positive transfer on all tested pairs.

**No retraining needed.** The `best_skill.md` file is deployed as-is. The only
change is which `LLMPort` implementation and which `ScoringPort` harness adapter
are used during evaluation.

**Transfer scores are metadata.** Stored in `Skill.transfer_scores` for audit.
If a transfer degrades (rare in the paper), the skill can be re-optimized on the
target model/harness using the same `SkillOptFlow`.

---

## 9. Dependency Injection Bindings

Updated `application/di.py` after all phases:

```python
class Container:
    def configure_skillopt(
        self,
        *,
        db_path: str = "./weebot_sessions.db",
        optimizer_model: str = "anthropic/claude-sonnet-4.6",
        target_model: str = "openrouter/auto",
        harness: str = "direct_chat",
    ) -> None:
        # Base bindings (from remediation)
        self.configure_defaults(db_path=db_path, default_model=target_model)

        # Optimizer LLM — separate, stronger model
        self.register(
            "optimizer_llm",
            lambda: create_adapter(
                "anthropic" if "claude" in optimizer_model else "openrouter",
                model=optimizer_model,
            ),
        )

        # Scoring port — harness-specific
        self.register(ScoringPort, lambda: self._create_scorer(harness))

        # Event store port
        self.register(EventStorePort, self._create_event_store)

        # Skill store
        self.register(SkillStore, self._create_skill_store)

        # Trajectory repository
        self.register(TrajectoryRepository, self._create_trajectory_repo)

        # Optimizer agent
        self.register(OptimizerAgent, self._create_optimizer_agent)

        # Validation runner
        self.register(ValidationRunner, self._create_validation_runner)

        # SkillOpt flow
        self.register(SkillOptFlow, self._create_skill_opt_flow)

    def build_skill_opt_flow(self, skill_name: str) -> SkillOptFlow:
        return SkillOptFlow(
            skill_name=skill_name,
            target_llm=self.get(LLMPort),
            optimizer=self.get(OptimizerAgent),
            skill_store=self.get(SkillStore),
            trajectory_repo=self.get(TrajectoryRepository),
            task_runner=self.get(TaskRunner),
            event_bus=self.get(EventBusPort),
            mediator=self.get(Mediator),
            epochs=4,
            steps_per_epoch=5,
            batch_size=40,
            minibatch_size=8,
        )
```

---

## 10. Testing Strategy

### 10.1 Unit tests (domain layer)

- `Skill.apply_edits()` — budget enforcement, protected section guard, version increment
- `SkillEdit.apply()` — all four operations on fixture markdown
- `LearningRateScheduler` — cosine, constant, linear schedules; floor enforcement
- `TrajectorySummary` — serialization round-trip
- Event model validation — all new events parse from JSON

### 10.2 Integration tests (application layer)

- `ValidateSkillHandler` — accepts improvement, rejects tie, rejects regression
- `ApplySkillEditsHandler` — applies edits, returns candidate, does NOT persist accepted
- `OptimizerAgent.reflect_on_failures()` — mock LLM returns known JSON, verify edit list
- `ReflectionEngine` — minibatch partitioning, parallel worker fan-out
- `MergeEngine` — deduplication, failure priority, conflict resolution
- `RankingEngine` — sorts by support_count, clips to budget

### 10.3 E2E tests (full pipeline)

- `SkillOptFlow` with mock LLM — verify epoch loop produces at least one accepted edit
- Validation gate rejection — inject a deliberately harmful edit, verify it's caught
- Cross-harness transfer — run Codex-optimized skill on direct chat, verify no regression

### 10.4 Architecture fitness tests

- Domain layer imports zero outer-layer modules
- Application layer imports infrastructure only via lazy (method-level) imports
- All CQRS commands go through mediator (no direct agent calls in flow states)
- `di.py` is the only composition root

---

## 11. File Manifest

Total new files: **26**  
Total modified files: **12**

### New files by layer

```
weebot/
├── domain/
│   └── models/
│       ├── trajectory.py          ★ Phase 1
│       └── skill_edit.py          ★ Phase 3
├── application/
│   ├── agents/
│   │   └── optimizer_agent.py     ★ Phase 4
│   ├── cqrs/
│   │   ├── commands/
│   │   │   ├── trajectory_commands.py   ★ Phase 1
│   │   │   ├── validation_commands.py   ★ Phase 2
│   │   │   ├── skill_edit_commands.py   ★ Phase 3
│   │   │   └── transfer_commands.py     ★ Phase 6
│   │   └── handlers/
│   │       ├── trajectory_handler.py    ★ Phase 1
│   │       ├── validation_handler.py    ★ Phase 2
│   │       ├── skill_edit_handler.py    ★ Phase 3
│   │       └── transfer_handler.py      ★ Phase 6
│   ├── flows/
│   │   ├── skill_opt_flow.py            ★ Phase 5
│   │   └── states/
│   │       ├── rollout.py               ★ Phase 5
│   │       ├── reflect.py               ★ Phase 5
│   │       └── validate.py              ★ Phase 5
│   ├── ports/
│   │   ├── event_store_port.py          ★ Phase 1
│   │   ├── scoring_port.py              ★ Phase 1
│   │   └── optimizer_port.py            ★ Phase 4
│   ├── services/
│   │   ├── trajectory_builder.py        ★ Phase 1
│   │   ├── validation_runner.py         ★ Phase 2
│   │   ├── reflection_engine.py         ★ Phase 4
│   │   ├── merge_engine.py              ★ Phase 4
│   │   └── ranking_engine.py            ★ Phase 4
│   └── skills/
│       └── builtin/
│           └── optimizer/
│               ├── reflection_failure.md   ★ Phase 4
│               ├── reflection_success.md   ★ Phase 4
│               ├── merge_failure.md        ★ Phase 4
│               ├── merge_success.md        ★ Phase 4
│               ├── merge_final.md          ★ Phase 4
│               ├── ranking.md              ★ Phase 4
│               ├── slow_update.md          ★ Phase 4
│               └── meta_skill.md           ★ Phase 4
├── infrastructure/
│   └── persistence/
│       ├── trajectory_repo.py         ★ Phase 1
│       └── skill_store.py             ★ Phase 2
```

### Modified files

```
weebot/
├── domain/
│   ├── models/
│   │   ├── event.py            + TrajectoryScored, SkillEdit{Proposed,Accepted,Rejected}, EpochCompleted
│   │   └── skill.py            + versioning, apply_edits(), export_best()
│   └── ports.py                + EventPublisher protocol (already done)
├── application/
│   ├── di.py                   + configure_skillopt(), optimizer bindings
│   ├── cqrs/
│   │   └── __init__.py         + new command/handler exports
│   └── flows/
│       └── states/
│           └── completed.py    + emit TrajectoryScored after DoneEvent
├── infrastructure/
│   ├── event_store.py          + save_trajectory(), get_trajectories_by_skill()
│   └── persistence/
│       └── sqlite_state_repo.py  (no changes needed — sessions already stored)
└── interfaces/
    ├── factories.py            + create_skill_opt_flow()
    └── cli/
        └── agent_runner.py     + run_optimization_epoch()
```

---

## Appendix A: Phase Dependencies

```
Phase 1 ──────┐
              ├──→ Phase 2 ──┐
              │              ├──→ Phase 4 ──→ Phase 5 ──→ Phase 6
Phase 3 ──────┘              │
                             └── (independent, but needs Phase 1 for test data)
```

Phases 1 and 3 can be developed in parallel. Phase 2 depends on Phase 1 (needs trajectory
storage for validation tasks). Phase 4 depends on Phases 2 + 3 (needs edit model and
validation gate). Phase 5 depends on Phase 4. Phase 6 depends on Phase 5.

## Appendix B: Cost Estimates

Based on the paper's reported costs and Weebot's OpenRouter pricing:

| Component | Cost per epoch (GPT-5.5 target, Claude Opus 4.6 optimizer) |
|-----------|------------------------------------------------------------|
| Rollout (40 tasks × target model) | ~$0.80 |
| Reflection (16 workers × optimizer model) | ~$2.40 |
| Merge + Rank (optimizer model) | ~$0.60 |
| Validation (20 tasks × target model) | ~$0.40 |
| Slow update (optimizer model) | ~$0.30 |
| **Total per epoch** | **~$4.50** |
| **Total for 4-epoch optimization** | **~$18.00** |

The paper achieves 1–4 accepted edits per skill. After optimization, deployment costs
are identical to the no-skill baseline — the skill is just a prepended text block.
