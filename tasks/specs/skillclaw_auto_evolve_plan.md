# Auto-Evolve Back-End: 6 Enhancements (SkillClaw-Inspired)

## Context

SkillClaw (AMAP-ML/SkillClaw, 1.8k★) evolves agent skills from real session data via:
proxy-based capture → trajectory building → session scoring → aggregation by skill →
LLM evolution pipeline → pre-publish verification gate.

Weebot already has SkillOptFlow (full training loop), SkillCurator, SkillStore, ValidationRunner,
TrajectoryExporter, and BM25 retrieval — but these form an isolated benchmark-only training loop.
Real production sessions never feed skill improvement. These 6 enhancements close that gap.

**Relationship to auto_think_auto_build_plan.md**: The existing plan adds the Auto-think front-end
(DreamerAgent → IdeaGate → PlanActFlow). This plan adds the Auto-evolve back-end
(PlanActFlow → SessionCapture → SkillOptFlow). Enhancement E4 feeds `IdeaContract` objects into
the IdeaGate from the existing plan, closing the full loop.

---

## What My Original Audit Got Wrong (and Why This Plan Differs)

1. **Per-step PRM dropped.** SkillClaw's PRM fires 3 LLM calls per turn — weebot has many steps
   per session. Session-level judge (E2) gives equivalent signal at 1/N the cost.

2. **Skill injection tracking is the real prerequisite** — not trajectory formatting.
   Nothing in weebot currently records which skills were injected into a given session.
   Without E1, none of E3/E4 can work.

3. **TrajectoryExporter is not a near-miss.** It writes JSONL for fine-tuning datasets.
   The needed converter (E3) maps `Session.events` → `TrajectorySummary`, the input
   type `SkillOptFlow` already consumes.

4. **Validated publish mode deferred.** Requires multiple concurrent clients.
   Weebot is single-agent; not applicable until then.

---

## Architecture Invariants (must hold after all phases)

1. **Dependency direction**: Domain models (E1's `SkillInjectEvent`, E2's `SessionQuality`,
   E3's production trajectory) must not import from application or infrastructure.

2. **Fail-open**: E2 (SessionQualityJudge) returns `SessionQuality(overall=0.5)` on any
   exception. E4 (EvolutionBridge) logs and skips sessions it cannot convert.

3. **Backward compatibility**: All new `PlanActFlowConfig` fields default to `None`.
   Existing flows with no services configured run identically to before.

4. **No benchmark contamination**: `ProductionTrajectorySummary` is a separate subtype.
   It never overwrites `TrajectorySummary.task_id` from benchmark harnesses.

5. **Immutability**: All domain model mutations use `model_copy(update=...)`.

---

## Pre-flight Check

Before starting, verify these existing items are in place:
- `weebot/application/flows/skill_opt_flow.py` — `SkillOptFlow` (confirmed exists)
- `weebot/domain/models/trajectory.py` — `TrajectorySummary`, `OptimizationBatch` (confirmed)
- `weebot/application/skills/skill_registry.py` — `SkillRegistry` with `_parse_skill` (confirmed)
- `weebot/application/ports/scoring_port.py` — `ScoringPort` (confirmed, benchmark-only)
- `weebot/infrastructure/persistence/skill_store.py` — `SkillStore` (confirmed)

---

## Enhancement 1 — SkillInjectionTracker

**Purpose:** Record which skills are injected into every PlanActFlow session. This is the
foundational prerequisite — without it, session aggregation by skill is impossible.

### New Files

| File | Layer | Purpose |
|------|-------|---------|
| `weebot/domain/models/skill_inject_event.py` | Domain | `SkillInjectEvent` domain event |

### `SkillInjectEvent` Domain Model

```python
class SkillInjectEvent(BaseEvent):
    """Emitted when one or more skills are injected into a session."""
    type: Literal["skill_inject"] = "skill_inject"
    session_id: str = Field(default="")
    step_id: str = Field(default="")
    injected_skills: list[str] = Field(
        default_factory=list,
        description="Names of skills retrieved and prepended to this step's context",
    )
    skill_versions: dict[str, int] = Field(
        default_factory=dict,
        description="name -> version at injection time",
    )
```

Add `SkillInjectEvent` to `AgentEvent` union in `weebot/domain/models/event.py`.

### Integration Point — ExecutingState

**File:** `weebot/application/flows/states/executing.py`

When the skill retriever runs (wherever `BM25SkillRetriever.retrieve()` is called before
building the executor's system prompt), yield a `SkillInjectEvent`:

```python
if retrieved_skills:
    yield SkillInjectEvent(
        session_id=context._session.id,
        step_id=step.id,
        injected_skills=[s.name for s in retrieved_skills],
        skill_versions={s.name: s.current_version for s in retrieved_skills},
    )
```

Also persist the set to `session.context.extra["skills_referenced"]` (as a sorted list)
by merging across all steps:
```python
existing = set(context._session.context.extra.get("skills_referenced", []))
existing |= {s.name for s in retrieved_skills}
context._session = context._session.model_copy(
    update={"context": context._session.context.model_copy(
        update={"extra": {**context._session.context.extra,
                          "skills_referenced": sorted(existing)}}
    )}
)
```

### PlanActFlowConfig / PlanActFlow

No config change needed — `SkillInjectionTracker` is always active when a skill retriever
is present. The event is emitted inline in ExecutingState.

### Tests

**File:** `tests/unit/test_skill_injection_tracker.py` — 5 tests:
- retriever returns 1 skill → 1 SkillInjectEvent emitted with correct name/version
- retriever returns 0 skills → no SkillInjectEvent
- multiple steps accumulate in `skills_referenced` set (no duplicates)
- `skill_versions` dict populated from `Skill.current_version`
- EventStore captures SkillInjectEvent type

---

## Enhancement 2 — SessionQualityJudge

**Purpose:** LLM 4-dimension scoring for production sessions that don't have benchmark scores.
Creates a quality signal that feeds the SkillOptFlow evolution loop.

### New Files

| File | Layer | Purpose |
|------|-------|---------|
| `weebot/domain/models/session_quality.py` | Domain | `SessionQuality`, `QualityDimension` |
| `weebot/application/ports/session_quality_port.py` | Application | `SessionQualityPort` ABC |
| `weebot/application/services/session_quality_judge.py` | Application | LLM-backed, "critic" role |
| `tests/unit/test_session_quality_judge.py` | Tests | Unit tests |

### `SessionQuality` Domain Model

```python
class SessionQuality(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str = Field(default="")
    task_completion: float = Field(default=0.5, ge=0.0, le=1.0)
    response_quality: float = Field(default=0.5, ge=0.0, le=1.0)
    efficiency: float = Field(default=0.5, ge=0.0, le=1.0)
    tool_usage: float = Field(default=0.5, ge=0.0, le=1.0)
    overall: float = Field(default=0.5, ge=0.0, le=1.0,
                           description="Weighted: completion×0.55 + quality×0.30 + eff×0.05 + tool×0.10")
    rationale: str = Field(default="")
    source: str = Field(default="llm_judge",
                        description="'llm_judge' | 'benchmark' | 'heuristic'")
    judged_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

### `SessionQualityPort` ABC

```python
class SessionQualityPort(ABC):
    @abstractmethod
    async def judge(self, session: Session) -> SessionQuality:
        """Fail-open: return SessionQuality(overall=0.5, source='heuristic') on any error."""
        ...
```

### `SessionQualityJudge` Implementation Shape

Single LLM call pattern (follows `PlanCriticService` exactly):

```python
_JUDGE_SYSTEM = """\
You are a session-level quality evaluator for an AI coding agent.

Score the session on four dimensions (0.0–1.0):
- task_completion: Was the user's goal achieved?
- response_quality: Correct, complete, and clear final outcome?
- efficiency: Did the agent avoid unnecessary retries or detours?
- tool_usage: Were tool choices appropriate and effective?

Use these weights for overall: task_completion×0.55 + response_quality×0.30 +
efficiency×0.05 + tool_usage×0.10.

Output exactly one JSON object:
{"task_completion": 0.0-1.0, "response_quality": 0.0-1.0,
 "efficiency": 0.0-1.0, "tool_usage": 0.0-1.0, "rationale": "..."}

No markdown fences. No extra text.
"""
```

Payload includes:
- plan title + step descriptions (max 5 steps, 200 chars each)
- error event count and tool event count from `session.events`
- final `MessageEvent(role="assistant")` content (last 600 chars)
- `skills_referenced` from `session.context.extra`

Timeout: 8s. Uses "critic" role (`openai/gpt-oss-120b:free`). Fail-open → `SessionQuality(overall=0.5, source="heuristic")`.

Weighted overall computed locally (not trusted from LLM):
```python
overall = round(
    data["task_completion"] * 0.55 +
    data["response_quality"] * 0.30 +
    data["efficiency"] * 0.05 +
    data["tool_usage"] * 0.10,
    3
)
```

### Integration in CompletedState

**File:** `weebot/application/flows/states/completed.py`

Add after the TrustReport block (from auto_think plan Phase 6), before RetentionReview:

```python
# ── SessionQualityJudge (background, non-blocking) ──────────────────
if getattr(context, "_session_quality_judge", None) is not None:
    asyncio.create_task(_run_session_quality_judge(
        judge=context._session_quality_judge,
        session=context._session,
        extra=extra,
    ))
```

Module-level helper:
```python
async def _run_session_quality_judge(judge, session, extra):
    quality = await judge.judge(session)
    logger.info(
        "SessionQuality %s: overall=%.3f (completion=%.2f, quality=%.2f)",
        session.id, quality.overall, quality.task_completion, quality.response_quality,
    )
    # Write to session.context.extra is not possible post-completion — log only.
    # Future: persist to SessionQualityStore for aggregation.
```

**PlanActFlowConfig:**
```python
session_quality_judge: Optional[Any] = None   # SessionQualityPort
```

**PlanActFlow `__init__`:**
```python
self._session_quality_judge = cfg.session_quality_judge
```

### DI Registration

**`weebot/application/di/_factories.py`:**
```python
@staticmethod
def _create_session_quality_judge() -> "SessionQualityJudge":
    from weebot.application.services.session_quality_judge import SessionQualityJudge
    llm = FactoriesMixin._create_llm_for_role("critic")
    return SessionQualityJudge(llm=llm, timeout_seconds=8.0)
```

**`weebot/application/di/__init__.py`:**
```python
self.register("session_quality_judge", self._create_session_quality_judge)
```

Pass in `weebot/interfaces/factories.py` and `_skillopt.py`.

### Tests

`tests/unit/test_session_quality_judge.py` — 8 tests:
- happy path returns correct weighted overall
- LLM timeout returns heuristic SessionQuality
- JSON parse error returns heuristic fallback
- score clamping (LLM returns >1.0 or <0.0)
- session with no events returns heuristic
- weighted overall is computed locally not from LLM response
- skills_referenced included in payload
- source field is "llm_judge" on success, "heuristic" on failure

---

## Enhancement 3 — ProductionTrajectoryConverter

**Purpose:** Convert a completed `Session` + `SessionQuality` into a `TrajectorySummary` that
`SkillOptFlow` can consume. This is the missing bridge between the two flows.

### New Files

| File | Layer | Purpose |
|------|-------|---------|
| `weebot/application/services/production_trajectory_converter.py` | Application | Pure conversion, no LLM |
| `tests/unit/test_production_trajectory_converter.py` | Tests | Unit tests |

### Implementation Shape

Pure service — zero LLM calls, zero I/O:

```python
class ProductionTrajectoryConverter:
    """Converts a completed Session + SessionQuality → TrajectorySummary.

    The resulting TrajectorySummary.task_id is set to session_id with a
    "prod:" prefix so SkillOptFlow can distinguish production sessions from
    benchmark runs. The skill_name is taken from session.context.extra
    ["skills_referenced"] — the first skill found, or "" if none.

    For multi-skill sessions, call convert() once per referenced skill,
    passing the desired skill_name explicitly.
    """

    @staticmethod
    def convert(
        session: Session,
        quality: SessionQuality,
        skill_name: str = "",
    ) -> TrajectorySummary:
        events = session.events
        tool_count = sum(1 for e in events if getattr(e, "type", "") == "tool")
        error_count = sum(1 for e in events if getattr(e, "type", "") == "error")

        # Build compact trajectory_text from StepEvents
        step_lines = []
        for e in events:
            if getattr(e, "type", "") == "step":
                status = getattr(e, "status", "")
                desc = getattr(e, "description", "")[:120]
                step_lines.append(f"[{status}] {desc}")
        trajectory_text = "\n".join(step_lines[:20])  # cap at 20 steps

        # Derive failure / success patterns from tool errors and completion
        failure_modes: list[str] = []
        success_patterns: list[str] = []
        if error_count > 0:
            failure_modes.append(f"tool_errors:{error_count}")
        if quality.task_completion >= 0.8:
            success_patterns.append("task_completed")
        if quality.efficiency < 0.4:
            failure_modes.append("low_efficiency")

        return TrajectorySummary(
            task_id=f"prod:{session.id}",
            session_id=session.id,
            skill_name=skill_name or "",
            skill_version=0,
            harness="plan_act_flow",
            score=quality.overall,
            passed=quality.overall >= 0.7,
            failure_modes=failure_modes,
            success_patterns=success_patterns,
            tool_call_count=tool_count,
            trajectory_text=trajectory_text,
        )
```

### Tests

`tests/unit/test_production_trajectory_converter.py` — 6 tests:
- task_id has "prod:" prefix
- score equals quality.overall
- tool_count matches ToolEvent count
- failure_modes includes "tool_errors:N" when errors > 0
- success_patterns includes "task_completed" when task_completion >= 0.8
- multi-skill session: converter called per skill produces correct skill_name each time

---

## Enhancement 4 — ProductionSkillEvolutionBridge

**Purpose:** Drains completed production sessions, groups them by referenced skill, and feeds
each group into SkillOptFlow as an `OptimizationBatch`. Sessions with no referenced skill
feed the DreamerAgent as `IdeaSource.KG_PATTERN` (synergy with auto_think plan).

This is the central wiring that connects PlanActFlow output to the skill evolution loop.

### New Files

| File | Layer | Purpose |
|------|-------|---------|
| `weebot/application/services/production_skill_bridge.py` | Application | Bridge service |
| `tests/unit/test_production_skill_bridge.py` | Tests | Unit tests |

### `ProductionSkillBridge` Implementation Shape

```python
class ProductionSkillBridge:
    """Drains recent production sessions and routes them into SkillOptFlow.

    Called by the 6-hour opportunity scan cycle in _capabilities.py.
    """

    def __init__(
        self,
        state_repo: StateRepositoryPort,
        quality_judge: SessionQualityPort,
        skill_opt_runner: SkillOptRunner,       # new thin wrapper, see below
        dreamer_agent: Optional[Any] = None,   # DreamerAgent from auto_think plan
        lookback_hours: int = 8,
        min_sessions_per_skill: int = 1,
    ) -> None: ...

    async def run_cycle(self) -> dict[str, int]:
        """Run one bridge cycle. Returns {skill_name: sessions_processed}."""
        sessions = await self._drain_recent_sessions()
        if not sessions:
            return {}

        grouped = self._group_by_skill(sessions)
        results: dict[str, int] = {}

        # Skill-specific evolution
        for skill_name, skill_sessions in grouped.items():
            if skill_name == NO_SKILL_KEY:
                continue
            if len(skill_sessions) < self._min_sessions_per_skill:
                continue
            batch = await self._build_batch(skill_name, skill_sessions)
            await self._skill_opt_runner.evolve_from_batch(skill_name, batch)
            results[skill_name] = len(skill_sessions)

        # No-skill sessions → DreamerAgent ideation
        no_skill = grouped.get(NO_SKILL_KEY, [])
        if no_skill and self._dreamer_agent is not None:
            failed_events = [
                {"session_id": s.id, "description": s.context.extra.get("plan_title", "")}
                for s in no_skill
            ]
            contracts = await self._dreamer_agent.dream(
                opportunity_proposals=[],
                failed_step_events=failed_events,
                audit_violations=[],
                session_id="skill_bridge",
            )
            logger.info(
                "SkillBridge: %d no-skill sessions → DreamerAgent → %d IdeaContracts",
                len(no_skill), len(contracts),
            )

        return results

    def _group_by_skill(
        self, sessions: list[Session]
    ) -> dict[str, list[Session]]:
        """Group sessions by first referenced skill; unmatched → NO_SKILL_KEY."""
        groups: dict[str, list[Session]] = defaultdict(list)
        for session in sessions:
            skills = session.context.extra.get("skills_referenced", [])
            if not skills:
                groups[NO_SKILL_KEY].append(session)
            else:
                for skill_name in skills:
                    groups[skill_name].append(session)
        return dict(groups)
```

### `SkillOptRunner` — Thin Wrapper

New thin service that accepts a production `OptimizationBatch` and calls SkillOptFlow's
reflect → merge → apply steps without running rollouts (rollouts are expensive; we have
real sessions already):

```python
class SkillOptRunner:
    """Runs the reflect+merge+apply cycle of SkillOptFlow from a pre-built batch."""

    def __init__(self, optimizer: OptimizerPort, mediator, skill_store: SkillStore): ...

    async def evolve_from_batch(
        self, skill_name: str, batch: OptimizationBatch
    ) -> bool:
        """Returns True if edits were accepted."""
        skill = await self._skill_store.load(skill_name)
        if skill is None:
            return False
        failure_edits = await self._optimizer.reflect_on_failures(batch, skill)
        success_edits = await self._optimizer.reflect_on_successes(batch, skill)
        if not failure_edits and not success_edits:
            return False
        merged = await self._optimizer.merge_edits(failure_edits, success_edits)
        ranked = await self._optimizer.rank_edits(merged, budget=4, skill=skill)
        if not ranked:
            return False
        result = await self._mediator.send(
            ApplySkillEditsCommand(
                skill_name=skill_name,
                edits=[e.model_dump() for e in ranked],
                budget=4,
                validation_task_ids=[],
            )
        )
        return result.success
```

### Integration in `_capabilities.py`

**File:** `weebot/application/di/_capabilities.py`

In the `opportunity_scan` callable, add a post-scan bridge pass:

```python
async def opportunity_scan():
    # Existing opportunity scan ...
    proposals = await opp.scan()
    logger.info("Opportunity scan: %d proposals", len(proposals))

    # Dreamer pass (from auto_think plan)
    if dreamer_agent is not None:
        ...

    # Production skill evolution bridge
    bridge = container.get("production_skill_bridge")
    if bridge is not None:
        results = await bridge.run_cycle()
        for skill, count in results.items():
            logger.info("SkillBridge: evolved '%s' from %d production sessions", skill, count)
```

### DI Registration

**`_factories.py`:**
```python
@staticmethod
def _create_production_skill_bridge() -> "ProductionSkillBridge":
    from weebot.application.services.production_skill_bridge import ProductionSkillBridge
    from weebot.application.services.skill_opt_runner import SkillOptRunner
    state_repo = FactoriesMixin._create_state_repo()
    quality_judge = FactoriesMixin._create_session_quality_judge()
    optimizer = container.get("optimizer")
    mediator = container.get("mediator")
    skill_store = container.get("skill_store")
    runner = SkillOptRunner(optimizer=optimizer, mediator=mediator, skill_store=skill_store)
    return ProductionSkillBridge(
        state_repo=state_repo,
        quality_judge=quality_judge,
        skill_opt_runner=runner,
        dreamer_agent=container.get("dreamer_agent"),  # from auto_think plan
        lookback_hours=8,
    )
```

**`__init__.py`:**
```python
self.register("production_skill_bridge", self._create_production_skill_bridge)
```

### Tests

`tests/unit/test_production_skill_bridge.py` — 7 tests:
- sessions grouped by referenced skills correctly (many-to-many)
- no-skill sessions routed to dreamer (not to optimizer)
- sessions below min_sessions_per_skill threshold are skipped
- SkillOptRunner.evolve_from_batch called once per skill group
- empty session list returns empty results dict
- DreamerAgent None → no-skill sessions silently dropped
- production_skill_bridge.run_cycle returns correct count map

---

## Enhancement 5 — SkillPublishVerifier

**Purpose:** LLM pre-publish gate with 4 content-quality dimensions. Blocks skill candidates
that lose concrete environment facts or add generic padding. Runs after `ValidationGateBehavior`
in the `ApplySkillEditsCommand` handler.

### New Files

| File | Layer | Purpose |
|------|-------|---------|
| `weebot/domain/models/skill_publish_verdict.py` | Domain | `SkillPublishVerdict`, `PublishCheck` |
| `weebot/application/ports/skill_publish_verifier_port.py` | Application | `SkillPublishVerifierPort` ABC |
| `weebot/application/services/skill_publish_verifier.py` | Application | LLM-backed, "reviewer" role |
| `tests/unit/test_skill_publish_verifier.py` | Tests | Unit tests |

### `SkillPublishVerdict` Domain Model

```python
class PublishCheck(str, Enum):
    GROUNDED_IN_EVIDENCE      = "grounded_in_evidence"
    PRESERVES_EXISTING_VALUE  = "preserves_existing_value"
    SPECIFICITY_AND_REUSE     = "specificity_and_reusability"
    SAFE_TO_PUBLISH           = "safe_to_publish"

class SkillPublishVerdict(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    skill_name: str = Field(default="")
    decision: str = Field(default="reject")   # "accept" | "reject"
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    checks: dict[str, float] = Field(default_factory=dict)
    reason: str = Field(default="")
    threshold: float = Field(default=0.75)
    verified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

### `SkillPublishVerifierPort` ABC

```python
class SkillPublishVerifierPort(ABC):
    @abstractmethod
    async def verify(
        self,
        skill_name: str,
        candidate_content: str,
        current_content: str,
        session_evidence: list[str],
        action_type: str,
    ) -> SkillPublishVerdict:
        """Fail-open: return SkillPublishVerdict(decision='accept') on any error."""
        ...
```

### `SkillPublishVerifier` Implementation

System prompt (adapted directly from SkillClaw's `_VERIFY_SKILL_SYSTEM`):

```python
_VERIFY_SYSTEM = """\
You are the final publication gate for agent skill evolution.

Approve the candidate ONLY if ALL are true:
1. grounded_in_evidence: changes are backed by the session evidence provided
2. preserves_existing_value: does NOT discard useful existing API details, endpoints,
   ports, filenames, payload formats, or environment-specific facts
3. specificity_and_reusability: concrete environment-specific knowledge, not generic advice
4. safe_to_publish: coherent and ready for reuse now, not a draft

Reject if ANY check fails.

Output EXACTLY one JSON object:
{
  "decision": "accept" | "reject",
  "score": 0.0-1.0,
  "reason": "brief explanation",
  "checks": {
    "grounded_in_evidence": 0.0-1.0,
    "preserves_existing_value": 0.0-1.0,
    "specificity_and_reusability": 0.0-1.0,
    "safe_to_publish": 0.0-1.0
  }
}

No markdown fences. No extra text.
"""
```

Uses "reviewer" role (`openai/gpt-oss-120b:free`). Timeout: 8s. Max tokens: 400.
Cap `current_content` at 3000 chars, `candidate_content` at 4000 chars.
Fail-open → `SkillPublishVerdict(decision="accept", score=1.0, reason="verifier unavailable")`.

### Integration in `ApplySkillEditsCommand` Handler

**File:** `weebot/application/cqrs/handlers/skill_edit_handler.py`

After ValidationGateBehavior passes, call verifier if wired:

```python
verifier = getattr(self, "_skill_publish_verifier", None)
if verifier is not None and result.success:
    candidate = result.data.get("skill")
    current_skill_content = (await self._skill_store.load(command.skill_name))
    verdict = await verifier.verify(
        skill_name=command.skill_name,
        candidate_content=getattr(candidate, "content", ""),
        current_content=getattr(current_skill_content, "content", ""),
        session_evidence=command.session_evidence or [],  # new optional field
        action_type="improve_skill",
    )
    if verdict.decision == "reject":
        logger.warning(
            "SkillPublishVerifier REJECTED '%s' (score=%.2f): %s",
            command.skill_name, verdict.score, verdict.reason,
        )
        return CommandResult(success=False, data={"publish_verdict": verdict.model_dump()})
```

**`ApplySkillEditsCommand`** — add optional field:
```python
session_evidence: list[str] = Field(default_factory=list)
```

### DI Registration

**`_factories.py`:**
```python
@staticmethod
def _create_skill_publish_verifier() -> "SkillPublishVerifier":
    from weebot.application.services.skill_publish_verifier import SkillPublishVerifier
    llm = FactoriesMixin._create_llm_for_role("reviewer")
    return SkillPublishVerifier(llm=llm, threshold=0.75, timeout_seconds=8.0)
```

**`__init__.py`:**
```python
self.register("skill_publish_verifier", self._create_skill_publish_verifier)
```

### Tests

`tests/unit/test_skill_publish_verifier.py` — 7 tests:
- all 4 checks pass → decision "accept"
- grounded_in_evidence < threshold → decision "reject"
- preserves_existing_value check catches dropped endpoint
- score computed as mean of checks when LLM score absent
- LLM timeout → fail-open "accept" verdict
- JSON parse error → fail-open "accept" verdict
- decision forced "reject" when score < threshold even if LLM says "accept"

---

## Enhancement 6 — Skill Content SHA + Version History

**Purpose:** Track `content_sha` and bounded history in `SkillIDRegistry` to enable drift
detection, rollback, and TrustReport correlation with skill version changes.

**File:** `weebot/application/skills/skill_registry.py` (extend existing class)

### Changes to `SkillRegistry`

Add SHA tracking alongside the existing `_skills` dict:

```python
import hashlib

class SkillRegistry:
    def __init__(self, ...):
        ...
        self._version_history: dict[str, list[dict]] = {}  # name → [{version, sha, ts, action}]
        self._content_shas: dict[str, str] = {}            # name → current SHA

    def record_skill_update(
        self,
        skill_name: str,
        content: str,
        action: str = "improve_skill",
    ) -> str:
        """Record a content update. Returns new content SHA."""
        sha = hashlib.sha256(content.encode()).hexdigest()[:16]
        history = self._version_history.setdefault(skill_name, [])
        version = len(history) + 1
        history.append({
            "version": version,
            "content_sha": sha,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
        })
        # Cap at 20 entries
        if len(history) > 20:
            self._version_history[skill_name] = history[-20:]
        self._content_shas[skill_name] = sha
        return sha

    def get_content_sha(self, skill_name: str) -> str:
        return self._content_shas.get(skill_name, "")

    def has_changed(self, skill_name: str, content: str) -> bool:
        """True if content differs from last recorded SHA."""
        new_sha = hashlib.sha256(content.encode()).hexdigest()[:16]
        return new_sha != self._content_shas.get(skill_name, "")

    def get_version_history(self, skill_name: str) -> list[dict]:
        return list(self._version_history.get(skill_name, []))
```

### Integration

Call `skill_registry.record_skill_update()` in `SkillStore.save()` after every successful
write, passing the content and action type.

In `TrustReportService` (from auto_think plan, Phase 4), when building `VerificationDelta`
for a step that used a known skill, populate `delta.contributing_issues` with:
```
"skill_version_changed_during_session"
```
if the skill's SHA changed between session start and session end. This surfaces
mid-session skill drift as a contributing factor in the TrustReport.

### Tests

**File:** `tests/unit/test_skill_registry_sha.py` — 5 tests:
- first update sets SHA and version 1
- same content → has_changed returns False
- different content → has_changed returns True
- history capped at 20 entries
- action field persisted in history entries

---

## Build Sequence

Execute phases in order. Each phase can be committed independently.

```
Phase 0 — Enhancement 6 (pure, no LLM, no dependencies)
  weebot/application/skills/skill_registry.py    add SHA + version history
  tests/unit/test_skill_registry_sha.py          5 tests

Phase 1 — Enhancement 1 (SkillInjectionTracker)
  weebot/domain/models/event.py                  add SkillInjectEvent to AgentEvent union
  weebot/domain/models/skill_inject_event.py     NEW
  weebot/application/flows/states/executing.py   emit SkillInjectEvent + update extra
  tests/unit/test_skill_injection_tracker.py     5 tests

Phase 2 — Enhancement 2 (SessionQualityJudge)
  weebot/domain/models/session_quality.py        NEW
  weebot/application/ports/session_quality_port.py   NEW
  weebot/application/services/session_quality_judge.py  NEW
  weebot/application/models/plan_act_flow_config.py  add session_quality_judge field
  weebot/application/flows/plan_act_flow.py      store from cfg
  weebot/application/flows/states/completed.py   add background judge task
  weebot/application/di/_factories.py            _create_session_quality_judge
  weebot/application/di/__init__.py              register
  weebot/interfaces/factories.py                 pass to create_flow()
  tests/unit/test_session_quality_judge.py       8 tests

Phase 3 — Enhancement 3 (ProductionTrajectoryConverter, no LLM)
  weebot/application/services/production_trajectory_converter.py  NEW
  tests/unit/test_production_trajectory_converter.py              6 tests

Phase 4 — Enhancement 5 (SkillPublishVerifier)
  weebot/domain/models/skill_publish_verdict.py              NEW
  weebot/application/ports/skill_publish_verifier_port.py    NEW
  weebot/application/services/skill_publish_verifier.py      NEW
  weebot/application/cqrs/commands/skill_edit_commands.py    add session_evidence field
  weebot/application/cqrs/handlers/skill_edit_handler.py     call verifier after gate
  weebot/application/di/_factories.py                        factory
  weebot/application/di/__init__.py                          register
  tests/unit/test_skill_publish_verifier.py                  7 tests

Phase 5 — Enhancement 4 (ProductionSkillEvolutionBridge) — depends on 1,2,3
  weebot/application/services/skill_opt_runner.py            NEW
  weebot/application/services/production_skill_bridge.py     NEW
  weebot/application/di/_factories.py                        factory
  weebot/application/di/__init__.py                          register
  weebot/application/di/_capabilities.py                     extend opportunity_scan
  tests/unit/test_production_skill_bridge.py                 7 tests
```

---

## Verification

### After Phase 0
```bash
python -m pytest tests/unit/test_skill_registry_sha.py -v
```

### After Phase 1
```bash
python -m pytest tests/unit/test_skill_injection_tracker.py -v
python -m cli.main flow run "write a hello world python script"
# Expect: session.context.extra["skills_referenced"] populated in CompletedState log
```

### After Phase 2
```bash
python -m pytest tests/unit/test_session_quality_judge.py -v
python -m cli.main flow run "write a sorting function in python"
# Expect: CompletedState logs "SessionQuality <id>: overall=0.xx (completion=0.xx, quality=0.xx)"
```

### After Phase 4
```bash
python -m pytest tests/unit/test_skill_publish_verifier.py -v
# Trigger a skill evolution cycle manually to confirm verifier gate fires
```

### After Phase 5
```bash
python -m pytest tests/unit/test_production_skill_bridge.py -v
# Verify opportunity_scan logs include bridge output:
# "SkillBridge: evolved '<skill>' from N production sessions"
```

### Full regression
```bash
python -m pytest tests/ -v --cov=weebot --cov-report=term-missing
# Existing tests must all pass. New tests add coverage.
```

---

## Relation to auto_think_auto_build_plan.md

| Existing Plan | This Plan | Integration Point |
|---------------|-----------|-------------------|
| E2 DreamerAgent | E4 SkillBridge (no-skill sessions) | `dreamer_agent.dream()` called from bridge with no-skill sessions as `failed_step_events` |
| E3 IdeaGate | E4 SkillBridge | `IdeaContract` objects from bridge flow through IdeaGate before reaching PlanActFlow |
| E4 TrustReport | E6 content SHA | SHA drift appears as `contributing_issues` in `VerificationDelta` |
| E5 RetentionReview | E2 SessionQualityJudge | `session_quality.overall` available as input to `RetentionAgent.review()` |

Build this plan AFTER the auto_think plan's Phase 0-4 (domain models + ports) are complete,
since E4 of this plan depends on `DreamerAgent` being registered in the DI container.
