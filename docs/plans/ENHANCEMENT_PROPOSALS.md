# Enhancement Proposals — Weebot v2.8

**Derived from:** Forensic Architecture Reconstruction (2026-05-28)  
**Scope:** 2515 files across 5 architectural layers, 40 flat modules  
**Risk baseline:** 3 CRITICAL · 4 HIGH · 6 MEDIUM issues

---

## Enhancement 1: Wire CQRS Handlers as Real Execution Delegates

**Severity:** CRITICAL — CQRS write path is structurally bypassed  
**Location:** `application/cqrs/handlers.py` + `application/agents/*.py`  
**Effort:** 2–3 days

### Problem

The CQRS gates in flow states only validate — they don't execute. `PlanningState`
calls `mediator.send(CreatePlanCommand)` to check that the session exists, then
immediately calls `context._planner.create_plan()` directly. The CQRS handler
returns a `CommandResult` with `"planning_gate_passed"` but never touches the
planner. Same pattern for `ExecuteStepCommand` and `UpdatePlanCommand`.

### Proposed Change

Make the three core handlers call the agents themselves, returning accumulated
events in `CommandResult.data`. Flow states consume events from the result
instead of calling agents directly.

**Handler change (`handlers.py`):**

```python
# BEFORE
class CreatePlanHandler(CommandHandler):
    async def handle(self, command: CreatePlanCommand) -> CommandResult:
        session = await self._state_repo.load_session(command.session_id)
        if session is None:
            return CommandResult.fail(...)
        return CommandResult.ok(data={"status": "planning_gate_passed"})

# AFTER
class CreatePlanHandler(CommandHandler):
    def __init__(self, state_repo, planner: PlannerAgent):
        self._state_repo = state_repo
        self._planner = planner

    async def handle(self, command: CreatePlanCommand) -> CommandResult:
        session = await self._state_repo.load_session(command.session_id)
        if session is None:
            return CommandResult.fail(...)
        events = []
        async for event in self._planner.create_plan(command.prompt):
            events.append(event.model_dump())
        return CommandResult.ok(data={"events": events, "plan": ...})
```

**Flow state change (`planning.py`):**

```python
# BEFORE
cmd_result = await context._mediator.send(CreatePlanCommand(...))
if not cmd_result.success:
    yield ErrorEvent(...)
    return
async for event in context._planner.create_plan(prompt):  # DIRECT CALL
    await context._emit(event)
    yield event

# AFTER
cmd_result = await context._mediator.send(CreatePlanCommand(...))
if not cmd_result.success:
    yield ErrorEvent(...)
    return
for event_dict in cmd_result.data["events"]:
    event = reconstruct_event(event_dict)
    await context._emit(event)
    yield event
```

### Impact

- `LoggingBehavior` logs every plan creation, step execution, and plan update
- `ValidationBehavior` checks every command automatically
- `ValidationGateBehavior` fires for skill edits without manual wiring
- Telemetry and cost tracking become automatic for all agent calls
- Closes the #1 architectural fracture identified in the audit

### Files Modified

| File | Change |
|------|--------|
| `application/cqrs/handlers.py` | Inject `LLMPort`, `PlannerAgent`, `ExecutorAgent` into CreatePlanHandler, ExecuteStepHandler, UpdatePlanHandler. Call agents in `handle()`. |
| `application/flows/states/planning.py` | Consume events from `cmd_result.data["events"]` instead of direct agent call. |
| `application/flows/states/executing.py` | Same — consume from result. |
| `application/flows/states/updating.py` | Same — consume from result. |
| `application/di.py` | Update handler constructors in `build_mediator()` to inject agent dependencies. |

---

## Enhancement 2: Unify Event Buses

**Severity:** CRITICAL — Two parallel event buses with no bridge  
**Location:** `infrastructure/event_bus.py` + `core/agent_context.py`  
**Effort:** 1–2 days

### Problem

| System | Event Type | Consumers |
|--------|-----------|-----------|
| `AsyncEventBus` | `AgentEvent` (9 variants) | CLI subscriber, WebSocket broadcaster, EventStore |
| `EventBroker` | `ContextEvent` | `complex_task_executor.py`, `core/workflow_orchestrator.py`, `core/circuit_breaker.py`, `core/agent_context.py` |

Six modules use `EventBroker`. No bridge exists between the two buses. Events
published on one are invisible to the other.

### Proposed Change

Create an `EventBrokerAdapter` that implements `EventPublisher` (from
`domain/ports.py`) and delegates to `AsyncEventBus`:

```python
# New file: infrastructure/events/broker_adapter.py
class EventBrokerAdapter:
    """Makes EventBroker-compatible code publish through AsyncEventBus."""

    def __init__(self, event_bus: EventBusPort):
        self._bus = event_bus

    async def publish(self, event_type: str, agent_id: str,
                      data: dict[str, Any] | None = None) -> bool:
        event = self._convert(event_type, agent_id, data or {})
        await self._bus.publish(event)
        return True

    @staticmethod
    def _convert(event_type: str, agent_id: str,
                 data: dict[str, Any]) -> AgentEvent:
        # Map ContextEvent types to AgentEvent types
        if event_type == "fact_discovered":
            return FactDiscovered(**data)
        return NotificationEvent(text=f"{event_type} from {agent_id}")
```

Update `AgentContext` to accept an optional `EventPublisher` (already defined in
`domain/ports.py`) and default it to the global `AsyncEventBus`:

```python
# In core/agent_context.py
class AgentContext:
    def __init__(self, ..., event_publisher: EventPublisher | None = None):
        self.event_broker = event_publisher or get_event_bus()
```

### Impact

- Single event bus for all inter-module communication
- `FactDiscovered` events from `WorkingMemory` appear in the same stream as
  `StepEvent` from the executor
- All subscribers (CLI, WebSocket, EventStore) receive all events
- EventBroker consumers don't need to change — the adapter matches their API

### Files Modified

| File | Change |
|------|--------|
| `core/agent_context.py` | Accept `EventPublisher` instead of `EventBroker`. Remove `EventBroker` class. |
| `core/agent_context_final.py` | Same — update constructor. |
| `core/agent_context_v2.py` | Same — update constructor. |
| `infrastructure/events/broker_adapter.py` | NEW — adapter implementing `EventPublisher`. |
| `application/di.py` | Register `EventBrokerAdapter` on `EventPublisher` key. |

---

## Enhancement 3: Replace Legacy StateManager References

**Severity:** CRITICAL — Two parallel persistence systems  
**Location:** 6 files importing `weebot/state_manager.py`  
**Effort:** 1 day

### Problem

`weebot/state_manager.py` is deprecated (explicit `DeprecationWarning` at
line 236) but is still imported by:

- `core/agent_context.py` — `AgentContext.state_manager`
- `core/agent_context_final.py` — same field
- `core/agent_context_v2.py` — same field
- `mcp/server.py` — project creation/deletion
- `mcp/resources.py` — resource listing
- `state_coordinator.py` — unified state coordination

Two different databases exist: `projects.db` (StateManager) and
`weebot_sessions.db` (SQLiteStateRepository). No migration path.

### Proposed Change

Replace all `StateManager` references with `StateRepositoryPort` (already
defined). For the MCP modules that use `ProjectState`/`ResumableTask`,
provide a thin compatibility adapter:

```python
# New: infrastructure/persistence/legacy_project_adapter.py
class LegacyProjectAdapter:
    """Wraps SQLiteStateRepository to provide StateManager-compatible API."""

    def __init__(self, repo: StateRepositoryPort):
        self._repo = repo

    async def create_project(self, project_id: str, description: str) -> Session:
        session = Session(
            id=project_id,
            context={"description": description, "legacy_project": True},
        )
        await self._repo.save_session(session)
        return session
```

Update `AgentContext.create_orchestrator()`:

```python
# BEFORE
context = AgentContext.create_orchestrator(state_manager=StateManager())

# AFTER
context = AgentContext.create_orchestrator(
    state_repository=container.get(StateRepositoryPort)
)
```

### Files Modified

| File | Change |
|------|--------|
| `core/agent_context.py` | Replace `StateManager` with `StateRepositoryPort`. |
| `core/agent_context_final.py` | Same. |
| `core/agent_context_v2.py` | Same. |
| `mcp/server.py` | Use `LegacyProjectAdapter` for project operations. |
| `mcp/resources.py` | Same. |
| `state_coordinator.py` | Replace `StateManager()` with `StateRepositoryPort`. |
| `infrastructure/persistence/legacy_project_adapter.py` | NEW — compatibility adapter. |

---

## Enhancement 4: Web Router Dependency Injection

**Severity:** MEDIUM — Web routes create dependencies directly  
**Location:** `interfaces/web/routers/sessions.py`, `health.py`, `models.py`  
**Effort:** 1 day

### Problem

Every route handler in `sessions.py` creates `SQLiteStateRepository()` inline:

```python
async def list_sessions(
    state_repo: StateRepositoryPort = Depends(lambda: None),  # no-op placeholder
) -> SessionListResponse:
    from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository
    repo = SQLiteStateRepository()  # directly creates adapter
    sessions = await repo.list_sessions(user_id=user_id)
```

This pattern repeats 14 times across 3 router files. The `StateRepositoryPort =
Depends(lambda: None)` parameter is a no-op placeholder with a `# TODO: proper DI` comment.

### Proposed Change

Use FastAPI's `Depends` with the application DI container:

```python
from weebot.application.di import get_container

async def get_state_repo() -> StateRepositoryPort:
    return get_container().get(StateRepositoryPort)

@router.get("")
async def list_sessions(
    state_repo: StateRepositoryPort = Depends(get_state_repo),
    ...
) -> SessionListResponse:
    sessions = await state_repo.list_sessions(user_id=user_id)
```

Register the container on app startup:

```python
# In interfaces/web/main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    container = Container()
    container.configure_defaults()
    app.state.container = container
    yield
```

### Impact

- Single `SQLiteStateRepository` instance shared across all routes
- Connection pool reused instead of creating new pools per request
- Can swap to in-memory repository for testing without changing route code
- Removes 14 `from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository`
  statements from the interfaces layer

### Files Modified

| File | Change |
|------|--------|
| `interfaces/web/routers/sessions.py` | Replace 8 inline constructor calls with `Depends(get_state_repo)`. |
| `interfaces/web/routers/health.py` | Replace 5 inline constructor calls. |
| `interfaces/web/routers/models.py` | Replace 1 inline constructor call. |
| `interfaces/web/main.py` | Add `lifespan` that creates and stores `Container`. |

---

## Enhancement 5: Real ScoringPort Adapter

**Severity:** MEDIUM — No ScoringPort implementation exists  
**Location:** `application/ports/scoring_port.py` · `application/services/trajectory_builder.py`  
**Effort:** 2 days

### Problem

`di.py._create_default_scorer()` returns a no-op function that scores 0.0 for
errors, 0.5 for non-COMPLETED sessions, 1.0 for completed sessions. Every
trajectory in the SkillOpt pipeline gets a meaningless heuristic score. The
optimizer cannot learn from score deltas because all scores are binary/ternary.

### Proposed Change

Implement three concrete `ScoringPort` adapters:

1. **`ExactMatchScorer`** — for QA benchmarks (SearchQA, DocVQA). Compares the
   agent's final answer against `expected_answer` with normalized string comparison
   (lowercase, strip, remove punctuation). Returns 1.0 for match, 0.0 for mismatch.

2. **`ExecutionResultScorer`** — for spreadsheet/code benchmarks (SpreadsheetBench,
   OfficeQA). Checks if the agent's final output matches expected values (e.g.,
   `openpyxl` cell values match reference workbook).

3. **`VerifierScorer`** — generic fallback. Calls a verifier LLM with the agent's
   answer and expected answer, returns 0.0–1.0 with reasoning. Uses a summary
   model (e.g., GPT-4o-mini) for ~$0.001 per verification.

Wire through DI:

```python
# In application/di.py
from weebot.infrastructure.scoring.exact_match_scorer import ExactMatchScorer
from weebot.infrastructure.scoring.execution_scorer import ExecutionResultScorer
from weebot.infrastructure.scoring.verifier_scorer import VerifierScorer

def _create_scorer(self, harness: str) -> ScoringPort:
    if harness == "exact_match":
        return ExactMatchScorer()
    if harness == "execution":
        return ExecutionResultScorer()
    return VerifierScorer(llm=self.get(LLMPort))
```

### Impact

- SkillOpt can train on real score deltas — `TrajectoryScored.score` becomes
  meaningful (e.g., 0.73 vs 0.91)
- Optimizer can distinguish "almost correct" from "completely wrong"
- Validation gate decisions are based on genuine scores, not binary pass/fail
- Paper-equivalent evaluation becomes possible (same scoring pipeline as the benchmarks)

### Files Created

| File | Purpose |
|------|---------|
| `infrastructure/scoring/__init__.py` | Package init |
| `infrastructure/scoring/exact_match_scorer.py` | Normalized string comparison scorer |
| `infrastructure/scoring/execution_scorer.py` | Output artifact comparison scorer |
| `infrastructure/scoring/verifier_scorer.py` | LLM-based verifier scorer |

### Files Modified

| File | Change |
|------|--------|
| `application/di.py` | Replace `_create_default_scorer()` with `_create_scorer(harness)`. |

---

## Enhancement 6: SkillOpt Component Tests

**Severity:** HIGH — Zero test coverage for Phases 1–5  
**Location:** New test files under `tests/unit/`  
**Effort:** 3–4 days

### Problem

`tests/unit/` has 64 test files but none for the SkillOpt pipeline components
added in Phases 1–5: trajectory builder, validation runner, optimizer agent,
flow, LR scheduler, skill store, trajectory repo, CQRS handlers, validation gate.

### Proposed Test Suite

| Test File | Covers | Tests |
|-----------|--------|-------|
| `tests/unit/domain/test_skill_edit.py` | `SkillEdit.apply_to()` — all 4 ops, protected section guard, missing target error | 12 |
| `tests/unit/domain/test_skill_optimization.py` | `Skill.apply_edits()`, `accept_current()`, `reject_current()`, `apply_slow_update()`, `export_best()`, budget enforcement | 15 |
| `tests/unit/application/test_lr_scheduler.py` | Cosine, constant, linear, inverse schedules; floor enforcement; edge cases | 10 |
| `tests/unit/application/test_validation_runner.py` | Acceptance (improvement), rejection (tie, regression), empty tasks, parallel fan-out | 8 |
| `tests/unit/application/test_trajectory_builder.py` | Mock LLM returns known JSON, fallback on LLM failure, event digestion | 6 |
| `tests/unit/application/test_optimizer_agent.py` | Mock LLM returns known edit lists, minibatch partitioning, merge dedup, ranking, fallback | 10 |
| `tests/unit/application/test_cqrs_skill_handlers.py` | `ApplySkillEditsHandler`, `ValidateSkillHandler`, `ScoreTrajectoryHandler` with mocked dependencies | 9 |
| `tests/integration/test_skill_opt_pipeline.py` | Full `SkillOptFlow` with mock LLM, in-memory SQLite, 1 epoch 2 steps | 3 |
| `tests/unit/test_architecture_fitness.py` | Domain imports, infra imports, CQRS wiring, DI composition root | 5 |

**Total:** ~78 tests. Use `AsyncMock` for LLM, `:memory:` SQLite for stores, mock `TaskRunner` for
validation runner.

### Example test:

```python
# tests/unit/domain/test_skill_edit.py
from weebot.domain.models.skill_edit import SkillEdit, SLOW_UPDATE_START, SLOW_UPDATE_END

def test_append_adds_content():
    skill = "# My Skill\n\nExisting content."
    edit = SkillEdit(op="append", content="## New Section\n\nNew content.")
    result = edit.apply_to(skill)
    assert result.endswith("New content.")
    assert "New Section" in result

def test_protected_section_is_rejected():
    skill = f"# Skill\n\n{SLOW_UPDATE_START}\nguidance\n{SLOW_UPDATE_END}\n\nMore."
    with pytest.raises(ValueError, match="protected slow-update"):
        SkillEdit(op="replace", target="guidance", content="new").apply_to(skill)
```

### Files Created

| File | Tests |
|------|-------|
| `tests/unit/domain/test_skill_edit.py` | 12 |
| `tests/unit/domain/test_skill_optimization.py` | 15 |
| `tests/unit/application/test_lr_scheduler.py` | 10 |
| `tests/unit/application/test_validation_runner.py` | 8 |
| `tests/unit/application/test_trajectory_builder.py` | 6 |
| `tests/unit/application/test_optimizer_agent.py` | 10 |
| `tests/unit/application/test_cqrs_skill_handlers.py` | 9 |
| `tests/integration/test_skill_opt_pipeline.py` | 3 |
| `tests/unit/test_architecture_fitness.py` | 5 |

---

## Enhancement 7: Standardize Commands to Pydantic

**Severity:** LOW — Commands use dataclasses, domain models use Pydantic  
**Location:** `application/cqrs/commands.py` + all `commands/*.py`  
**Effort:** 1 day

### Problem

All 14 commands use `@dataclass(frozen=True)` with hand-written `validate()`
methods while domain models use `BaseModel` with automatic validation, JSON
Schema generation, and serialization:

```python
@dataclass(frozen=True)
class CreatePlanCommand(Command):
    session_id: str
    prompt: str
    model: str = "gpt-4"
    def validate(self) -> None:
        if not self.session_id:
            raise ValueError("session_id is required")
```

### Proposed Change

Migrate to Pydantic `BaseModel`:

```python
class CreatePlanCommand(Command, BaseModel):
    session_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    model: str = Field(default="gpt-4")
    context: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(frozen=True)
```

### Benefits

- Automatic JSON Schema (for web API docs / OpenAPI)
- Field-level validation baked into the model
- Consistent `model_dump()` serialization with domain events
- `ValidationBehavior` in the mediator already calls `command.validate()` — works
  identically with Pydantic validators
- Removes ~80 lines of hand-written `validate()` methods

### Files Modified

| File | Change |
|------|--------|
| `application/cqrs/base.py` | Make `Command` and `Query` also inherit `BaseModel`. |
| `application/cqrs/commands.py` | Convert 8 command classes to Pydantic. |
| `application/cqrs/commands/trajectory_commands.py` | Convert 2 commands. |
| `application/cqrs/commands/skill_edit_commands.py` | Convert 1 command. |
| `application/cqrs/commands/validation_commands.py` | Convert 1 command. |
| `application/cqrs/queries.py` | Convert 8 queries (for consistency). |

---

## Enhancement 8: Cross-Model Transfer Implementation

**Severity:** Feature gap — Plan §8, not yet implemented  
**Location:** New files  
**Effort:** 1–2 days

### Problem

Phases 1–5 are complete (trajectory pipeline, validation gate, edit operations,
optimizer, epoch loop) but Phase 6 (Cross-Model / Cross-Harness Transfer) from
`docs/plans/SKILLOPT_IMPLEMENTATION_PLAN.md` was deferred.

### Proposed Change

1. **`ValidateTransferCommand`** — runs a skill optimized for one (model, harness)
   pair on a different pair and measures the score delta.

2. **`ValidateTransferHandler`** — swaps the LLM adapter and scoring harness, runs
   validation tasks, compares against the target's no-skill baseline.

3. **Transfer metadata on `Skill`** — add field to store transfer results:

```python
class Skill(BaseModel):
    # ... existing fields ...
    transfer_scores: dict[str, float] = Field(
        default_factory=dict,
        description="Transfer scores keyed by 'model_id:harness'"
    )
```

4. **CLI command:**

```bash
python -m cli.main skill transfer spreadsheet_skill \
    --target-model gpt-5.4-mini \
    --target-harness claude_code
```

Output:
```
Skill: spreadsheet_skill v3
Transfer to gpt-5.4-mini @ claude_code:
  No-skill baseline: 22.1
  Transferred score: 82.8
  Δ: +60.7 points ✅

Stored in skill.transfer_scores["gpt-5.4-mini:claude_code"]
```

### Files Created

| File | Purpose |
|------|---------|
| `application/cqrs/commands/transfer_commands.py` | `ValidateTransferCommand` |
| `application/cqrs/handlers/transfer_handler.py` | `ValidateTransferHandler` |

### Files Modified

| File | Change |
|------|--------|
| `domain/models/skill.py` | Add `transfer_scores: dict[str, float]` field. |
| `cli/main.py` | Add `skill transfer` subcommand. |
| `interfaces/factories.py` | Add `create_transfer_runner()`. |

---

## Enhancement 9: Flat Module Classification + Deprecation Schedule

**Severity:** HIGH — 40 files (~700 KB) outside any layer  
**Location:** `weebot/*.py`  
**Effort:** 3 days (analysis + refactoring)

### Problem

40 files sit directly in the `weebot/` package with no layer assignment. Some
are deprecated, some actively referenced, some dead code. The audit flagged this
as a HIGH risk.

### Proposed Classification

#### Bucket A: DELETE — dead code, fully superseded

To identify: static analysis for files with zero imports from other weebot
modules AND zero import references from outside.

#### Bucket B: DEPRECATE — functional but superseded, keep import shim

| File | Replacement | Shim |
|------|-------------|------|
| `ai_router.py` | `ModelSelectionService` | `class ModelRouter = ModelSelectionService` with DeprecationWarning |
| `ai_providers.py` | `AdapterFactory.create_adapter()` | Re-export from adapter_factory |
| `agent_core_v2.py` | `AgentRunner` | Already has DeprecationWarning — keep |
| `state_manager.py` | `SQLiteStateRepository` | Already has DeprecationWarning — keep, add LegacyProjectAdapter |

#### Bucket C: PROMOTE — move into correct layer

| File | Destination | Reason |
|------|-------------|--------|
| `activity_stream.py` | `core/` | Already referenced by `core/agent_context.py` |
| `nlp_understanding.py` | `application/services/` | NLP is an application service |
| `security_validators.py` | `infrastructure/security/` | Security validation is infrastructure |
| `structured_logger.py` | `core/` | Shared utility, 15K of structured logging |
| `workflow_planner.py` | `application/flows/` | Flow planning is application logic |
| `information_synthesis.py` | `application/services/` | Research synthesis is a use case |
| `multi_source_research.py` | `application/services/` | Same |
| `error_system_base.py` | `core/` | Error base classes |
| `error_system_handler.py` | `core/` | Error handling |
| `error_system_user_messages.py` | `core/` | User-facing error messages |
| `notifications.py` | `infrastructure/notifications/` | Already has adapters there |
| `external_service_integration.py` | `infrastructure/` | External service integration |
| `complex_task_executor.py` | `application/services/` | Task execution is application logic |

#### Bucket D: FREEZE — too tightly coupled, document only

Add header to each frozen file:

```python
"""
⚠️ LEGACY MODULE (Bucket D — Freeze)
This module is part of the pre-Clean-Architecture legacy track.
It will not receive new features. File issues against weebot.application.*
for equivalent functionality.

Last maintainer audit: 2026-05-28
"""
```

### Files Created

None — this is a classification exercise with deprecation warnings and shim
imports on existing files.

---

## Enhancement 10: Architecture Fitness Tests (CI Gate)

**Severity:** All — prevents regression of architectural rules  
**Location:** `tests/unit/test_architecture_fitness.py`  
**Effort:** 0.5 days

### Proposed Tests

```python
import ast
from pathlib import Path

WEBBOT_ROOT = Path(__file__).parent.parent.parent.parent / "weebot"

class TestArchitectureFitness:

    def test_domain_has_no_outer_imports(self):
        """Domain imports nothing from core, infrastructure, interfaces, application."""
        for path in (WEBBOT_ROOT / "domain").rglob("*.py"):
            if '__pycache__' in str(path):
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if any(x in node.module for x in
                           ['core', 'infrastructure', 'interfaces', 'application']):
                        pytest.fail(
                            f"{path.relative_to(WEBBOT_ROOT)}: "
                            f"imports {node.module} (violation: domain → outer layer)"
                        )

    def test_application_has_no_module_level_infra_imports(self):
        """Application infrastructure imports only inside TYPE_CHECKING or functions."""
        ...

    def test_every_command_has_handler(self):
        """All Command subclasses have registered handlers."""
        ...

    def test_di_is_single_composition_root(self):
        """Only application/di.py creates infrastructure adapter instances."""
        ...

    def test_no_direct_agent_calls_in_flow_states(self):
        """Flow states must use mediator.send(), not direct PlannerAgent/ExecutorAgent calls."""
        ...
```

### Impact

Any future refactoring that breaks the dependency rules is caught at commit time.
The fitness tests act as an enforced checklist of the architectural decisions
documented in the full reconstruction and this enhancement plan.

---

## Priority Matrix

| # | Enhancement | Severity | Effort (days) | Value (1-10) | Priority |
|---|-------------|----------|---------------|--------------|----------|
| 1 | Wire CQRS as real execution delegates | CRITICAL | 3 | 10 | 1 |
| 2 | Unify event buses | CRITICAL | 2 | 9 | 2 |
| 3 | Replace legacy StateManager | CRITICAL | 1 | 8 | 3 |
| 4 | Web router DI | MEDIUM | 1 | 8 | 4 |
| 5 | Real ScoringPort | MEDIUM | 2 | 7 | 5 |
| 6 | SkillOpt tests | HIGH | 4 | 9 | 6 |
| 7 | Pydantic commands | LOW | 1 | 5 | 7 |
| 8 | Cross-model transfer | — | 2 | 6 | 8 |
| 9 | Architecture fitness tests | ALL | 0.5 | 7 | 9 |
| 10 | Flat module classification | HIGH | 3 | 6 | 10 |

---

## Sprint Schedule

```
Week 1   │ #3 StateManager (1d)  │ #4 Web DI (1d)         │ 2 CRITICAL + 1 MEDIUM resolved
         │                       │                         │
Week 2   │ #2 Event bus (2d)                              │ 1 CRITICAL resolved
         │                       │                         │
Week 3   │ #1 CQRS execution (3d)                         │ KEY transformation
         │                       │                         │
Week 4   │ #5 Real ScoringPort   │ #9 Fitness tests (0.5d) │ Unlocks SkillOpt quality
         │ (2d)                  │                         │
Week 5   │ #6 SkillOpt tests (4d)│ #8 Transfer (2d)       │ Parallel: tests + feature
         │                       │                         │
Week 6   │ #7 Pydantic (1d)      │ #10 Classification (3d) │ Cleanups
```

**Total:** 6 weeks · ~19 person-days

---

## References

- Architecture audit commit: `fd12e8a` (CQRS remediation)
- SkillOpt implementation plan: `docs/plans/SKILLOPT_IMPLEMENTATION_PLAN.md`
- Phases 1–5 implementation commits: trajectory pipeline, validation gate, edit
  operations, optimizer agent, epoch loop
- Paper: Yang et al., _SkillOpt: Executive Strategy for Self-Evolving Agent
  Skills_ (arXiv:2605.23904v2, May 2026)
