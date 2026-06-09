# Auto-think / Auto-build: 5 Enhancements Implementation Plan

## Context

Weebot has a strong Auto-build loop (planning, bounded execution, safety guardrails, critique,
verification) but lacks the Auto-think front end that turns ambient signals into approved work.
This plan implements 5 enhancements inspired by the Hermes buildroom pattern:

1. **Complete ReviewingState wiring** — already implemented, needs DI container registration + tests
2. **DreamerAgent** — active ideation from research/failure signals → `IdeaContract` objects
3. **IdeaContract gate chain** — `IntentReview` + `MainReview` gate before `PlanActFlow` starts
4. **VerificationDelta + TrustReport** — two-source evidence comparison → clean/watch/investigate
5. **RetentionReview** — keep/improve/park/prune recommendation after session completes

All enhancements follow weebot's established patterns:
- Port (ABC in `application/ports/`) → Service/Agent (in `application/services/` or `application/agents/`)
- Domain models in `domain/models/`, pure (no outer imports)
- Opt-in via `Optional[Any] = None` fields in `PlanActFlowConfig`
- Stored on `PlanActFlow` as `self._<name>` from `cfg.<name>`
- Registered in `application/di/_factories.py` → `application/di/__init__.py`
- Fail-open: every LLM call returns a safe default on any exception
- Immutable mutations: always via `model_copy(update=...)`, never in-place assignment

---

## Pre-flight Fixes

These are bugs and missing infrastructure that all 5 enhancements depend on.
Fix these first, in a single commit before any enhancement work begins.

### Fix 1 — Add model roles to ROLE_MODEL_CONFIG

**File:** `weebot/core/model_cascade_config.py`

Add two new roles at the end of `ROLE_MODEL_CONFIG`:

```python
# Independent code review: cross-lab from executor's Qwen Coder
"reviewer": [
    "openai/gpt-oss-120b:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "x-ai/grok-build-0.1",
],
# Idea synthesis: Kimi for multi-signal reasoning
"dreamer": [
    "moonshotai/kimi-k2.6:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "deepseek/deepseek-v4-flash",
],
```

### Fix 2 — Add `query_recent_events` to EventStorePort

**File:** `weebot/application/ports/event_store_port.py`

Add abstract method:
```python
@abstractmethod
async def query_recent_events(
    self,
    event_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Query recent events across all sessions, optionally filtered by type."""
    ...
```

**File:** `weebot/infrastructure/event_store.py`

Implement as async wrapper around the existing `query_events()` sync method:
```python
async def query_recent_events(
    self,
    event_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    events = self.query_events(event_type=event_type, limit=limit)
    return [e.to_dict() if hasattr(e, "to_dict") else vars(e) for e in events]
```

### Fix 3 — Add `code_review_result` to ThoughtEvent

**File:** `weebot/domain/models/event.py`

Add one optional field to `ThoughtEvent` so `TrustReportService` can read structured
verdicts instead of parsing formatted strings:

```python
class ThoughtEvent(BaseEvent):
    type: Literal["thought"] = "thought"
    step_id: str = Field(default="")
    thought: str = Field(default="")
    code_review_result: Optional[dict] = Field(
        default=None,
        description="Structured CodeReviewResult dict, set by ReviewingState when verdict is present",
    )
```

### Fix 4 — Fix OpportunityEngine mutation bug

**File:** `weebot/application/services/opportunity_engine.py`

In `mark_presented()` and `accept()`, replace in-place mutation with `model_copy`:

```python
# Before (BUG):
p.presented = True

# After:
self._store[i] = p.model_copy(update={"presented": True})
```

Apply the same pattern to `accept()`. If `state_repo` exposes an `update_opportunity` method,
call it here to persist the change; otherwise the fix at minimum prevents silent corruption
of Pydantic model state.

---

## Enhancement 1 — Complete ReviewingState Wiring

**Status:** All production code exists. Three tasks remain.

### Task 1a — Wire into DI container

**File:** `weebot/application/di/_factories.py`

Add factory (follow `_create_plan_critic` as template):
```python
@staticmethod
def _create_code_reviewer() -> "CodeReviewerService":
    from weebot.application.services.code_reviewer_service import CodeReviewerService
    from weebot.core.model_cascade_config import ROLE_MODEL_CONFIG
    from weebot.application.di._factories import FactoriesMixin
    llm = FactoriesMixin._create_llm_for_role("reviewer")
    return CodeReviewerService(llm=llm, timeout_seconds=8.0)
```

**File:** `weebot/application/di/__init__.py`

Register in `configure_defaults()`:
```python
self.register("code_reviewer", self._create_code_reviewer)
```

**File:** `weebot/interfaces/factories.py`

In `create_flow()`, pass reviewer to `PlanActFlow` (follow `plan_critic` pattern):
```python
code_reviewer=container.get("code_reviewer") if container else None,
```

**File:** `weebot/application/di/_skillopt.py`

In `_create_target_flow_factory`, add to `PlanActFlowConfig`:
```python
code_reviewer=self._maybe_get_str("code_reviewer"),
```

### Task 1b — Populate `code_review_result` in ReviewingState ThoughtEvent

**File:** `weebot/application/flows/states/reviewing.py`

In `_format_thought()` call site (the `yield ThoughtEvent(...)` block), populate the new field:
```python
yield ThoughtEvent(
    step_id=self._step.id,
    thought=self._format_thought(result),
    code_review_result={
        "verdict": result.verdict,
        "confidence": result.confidence,
        "severity": result.severity,
        "issues": result.issues,
    },
)
```

### Task 1c — Unit tests

**New files:**
- `tests/unit/test_code_reviewer_service.py` — 9 tests (approved/revise/reject verdicts, timeout, JSON
  parse failure, markdown fence stripping, confidence clamping, tool events in prompt, null step result)
- `tests/unit/test_reviewing_state.py` — 8 tests (no reviewer passthrough, approved/revise/reject
  routing, retry cap, ThoughtEvent yield, no plan fallthrough, hint injection)

Pattern: `AsyncMock(spec=LLMPort)` returning mock `LLMResponse` with `.content`.

---

## Enhancement 2 — DreamerAgent

### New Files

| File | Layer | Purpose |
|------|-------|---------|
| `weebot/domain/models/idea_contract.py` | Domain | `IdeaContract`, `IdeaSource` enum |
| `weebot/application/ports/dreamer_port.py` | Application | `DreamerPort` ABC |
| `weebot/application/agents/dreamer.py` | Application | `DreamerAgent` implementation |
| `tests/unit/test_dreamer_agent.py` | Tests | Unit tests |

### `IdeaContract` Domain Model

```python
class IdeaSource(str, Enum):
    OPPORTUNITY_PROPOSAL = "opportunity_proposal"
    FAILED_STEP          = "failed_step"
    AUDIT_VIOLATION      = "audit_violation"
    KG_PATTERN           = "kg_pattern"

class IdeaContract(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str = Field(default="")
    prompt: str = Field(default="", description="Full task prompt for PlannerAgent if accepted")
    source: IdeaSource = Field(default=IdeaSource.OPPORTUNITY_PROPOSAL)
    source_ref: str = Field(default="", description="ID of originating signal")
    evidence: list[str] = Field(default_factory=list)
    heat_score: float = Field(default=0.0, ge=0.0, le=1.0, description="urgency × novelty × confidence")
    estimated_effort: str = Field(default="medium", description="'low' | 'medium' | 'high'")
    dreamer_session_id: str = Field(default="")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    intent_verdict: Optional[str] = Field(default=None)   # set by IntentReviewService
    main_verdict: Optional[str] = Field(default=None)     # set by MainReviewService
```

### `DreamerPort` ABC

```python
class DreamerPort(ABC):
    @abstractmethod
    async def dream(
        self,
        opportunity_proposals: list,       # list[OpportunityProposal]
        failed_step_events: list[dict],    # from EventStorePort.query_recent_events
        audit_violations: list,            # list[Violation] from recent AuditReports
        session_id: str = "",
    ) -> list[IdeaContract]:
        """Synthesize signals into IdeaContracts. Fail-open: return [] on any error."""
        ...
```

### `DreamerAgent` Implementation Shape

```python
class DreamerAgent(DreamerPort):
    def __init__(
        self,
        llm: LLMPort,                                        # "dreamer" role model
        event_store: Optional[EventStorePort] = None,
        max_contracts: int = 5,
    ) -> None: ...

    async def dream(self, ...) -> list[IdeaContract]:
        signals = self._compile_signals(proposals, failed_events, violations)
        if not signals:
            return []
        try:
            response = await asyncio.wait_for(
                self._llm.chat(
                    messages=[
                        {"role": "system", "content": _DREAMER_SYSTEM},
                        {"role": "user", "content": self._build_prompt(signals)},
                    ],
                    temperature=0.3, max_tokens=800,
                ),
                timeout=15.0,
            )
            contracts = self._parse_contracts(response.content, session_id)
        except Exception:
            return []                                         # always fail-open
        contracts.sort(key=lambda c: c.heat_score, reverse=True)
        return contracts[:self._max_contracts]
```

**System prompt constraint:** Must include `"DO NOT approve or reject ideas — only surface them.
A separate review layer gates them."` — enforces the Dreamer-cannot-self-approve guardrail.

### Integration Point

`DreamerAgent` is NOT wired into `PlanActFlow`. It extends the existing opportunity scan cycle.

**File:** `weebot/application/di/_capabilities.py`

In the `opportunity_scan` callable, add a post-scan dreamer pass:
```python
async def opportunity_scan():
    proposals = await opp.scan()
    logger.info("Opportunity scan: %d proposals", len(proposals))
    # Dreamer pass (if configured):
    dreamer = container._maybe_get_str("dreamer_agent")
    if dreamer is not None:
        failed_events = await event_store.query_recent_events(event_type="error", limit=50)
        contracts = await dreamer.dream(proposals, failed_events, [], session_id="scan")
        logger.info("Dreamer produced %d idea contracts", len(contracts))
        # Store contracts for IdeaGate consumption (see Enhancement 3)
```

**PlanActFlowConfig change** (observability only):
```python
# weebot/application/models/plan_act_flow_config.py
idea_contract: Optional[Any] = None   # IdeaContract — approved context passed to PlannerAgent
```

**PlanActFlow change:**
```python
self._idea_contract = cfg.idea_contract
```

When `_idea_contract` is set, `PlanningState` prepends `idea_contract.evidence` to the task
prompt as `meta_notes` (the `PlannerAgent.create_plan()` parameter already accepts this).

### DI Registration

**File:** `weebot/application/di/_factories.py`
```python
@staticmethod
def _create_dreamer_agent() -> "DreamerAgent":
    from weebot.application.agents.dreamer import DreamerAgent
    llm = FactoriesMixin._create_llm_for_role("dreamer")
    return DreamerAgent(llm=llm, max_contracts=5)
```

**File:** `weebot/application/di/__init__.py`
```python
self.register("dreamer_agent", self._create_dreamer_agent)
```

### Tests

`tests/unit/test_dreamer_agent.py`: empty signals returns `[]`, LLM timeout returns `[]`,
parse error returns `[]`, contracts sorted by heat_score, capped at max_contracts,
system prompt contains self-approve guardrail text.

---

## Enhancement 3 — IdeaContract + IntentReview + MainReview Chain

### New Files

| File | Layer | Purpose |
|------|-------|---------|
| `weebot/domain/models/intent_review.py` | Domain | `IntentReview`, `IntentVerdict` enum |
| `weebot/domain/models/main_review.py` | Domain | `MainReview`, `MainVerdict`, `RiskBand` enums |
| `weebot/application/ports/intent_review_port.py` | Application | `IntentReviewPort` ABC |
| `weebot/application/ports/main_review_port.py` | Application | `MainReviewPort` ABC |
| `weebot/application/services/intent_review_service.py` | Application | LLM-backed, `"critic"` role |
| `weebot/application/services/main_review_service.py` | Application | LLM-backed, `"verifier"` role |
| `weebot/application/services/idea_gate.py` | Application | Pure orchestrator (no LLM) |
| `cli/commands/dream.py` | Interface | `dream scan`, `dream list`, `dream build` commands |
| `tests/unit/test_idea_gate.py` | Tests | Unit tests |
| `tests/unit/test_intent_review_service.py` | Tests | Unit tests |
| `tests/unit/test_main_review_service.py` | Tests | Unit tests |

### Domain Models

**`IntentReview`:**
```python
class IntentVerdict(str, Enum):
    READY     = "ready"       # coherent and actionable
    NOT_READY = "not_ready"   # needs clarification
    BLOCKED   = "blocked"     # unsafe or out of scope

class IntentReview(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    idea_contract_id: str = Field(default="")
    verdict: IntentVerdict = Field(default=IntentVerdict.NOT_READY)
    reasoning: str = Field(default="")
    clarification_needed: list[str] = Field(default_factory=list)
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

**`MainReview`:**
```python
class MainVerdict(str, Enum):
    APPROVED_FOR_CODER = "approved_for_coder"
    DEFERRED           = "deferred"
    REJECTED           = "rejected"

class RiskBand(str, Enum):
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"

class MainReview(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    idea_contract_id: str = Field(default="")
    intent_review_id: str = Field(default="")
    verdict: MainVerdict = Field(default=MainVerdict.DEFERRED)
    risk_band: RiskBand = Field(default=RiskBand.MEDIUM)
    risk_score: float = Field(default=0.5, ge=0.0, le=1.0)
    risk_factors: list[str] = Field(default_factory=list)
    rationale: str = Field(default="")
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

### Port Interfaces

Both follow `PlanCriticPort` exactly:

```python
# IntentReviewPort
class IntentReviewPort(ABC):
    @abstractmethod
    async def review(self, contract: IdeaContract) -> IntentReview:
        """Fail-open: return NOT_READY on any error."""
        ...

# MainReviewPort
class MainReviewPort(ABC):
    @abstractmethod
    async def review(self, contract: IdeaContract, intent: IntentReview) -> MainReview:
        """Fail-open: return DEFERRED on any error."""
        ...
```

### Service Implementation Shape

Both follow `PlanCriticService` exactly — single LLM call, structured JSON response,
`asyncio.wait_for` with timeout, fail-open exception handler.

**`IntentReviewService`:** uses `"critic"` role (`openai/gpt-oss-120b:free`), timeout 5s, max_tokens 300.
System prompt: assess whether idea prompt is coherent, actionable, and safe.
JSON response: `{"verdict": "...", "reasoning": "...", "clarification_needed": [...]}`.

**`MainReviewService`:** uses `"verifier"` role (`nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`),
timeout 8s, max_tokens 400.
System prompt: risk-score the idea; consider resource usage, scope, reversibility.
JSON response: `{"verdict": "...", "risk_band": "...", "risk_score": 0.0-1.0, "risk_factors": [...], "rationale": "..."}`.

Cap `intent.reasoning` at 500 chars when building MainReview prompt to prevent token overflow.

### `IdeaGate` Orchestrator

Pure service — no LLM calls, orchestrates the chain:

```python
class IdeaGate:
    def __init__(
        self,
        intent_reviewer: IntentReviewPort,
        main_reviewer: MainReviewPort,
    ) -> None: ...

    async def process(self, contracts: list[IdeaContract]) -> list[IdeaContract]:
        """Returns only APPROVED_FOR_CODER contracts with intent/main verdicts set."""
        approved = []
        for contract in contracts:
            intent = await self._intent_reviewer.review(contract)
            if intent.verdict == IntentVerdict.BLOCKED:
                logger.warning("IdeaGate BLOCKED %s: %s", contract.id, intent.reasoning)
                continue
            if intent.verdict == IntentVerdict.NOT_READY:
                logger.info("IdeaGate NOT_READY %s: %s", contract.id, intent.reasoning[:120])
                continue   # Re-queue logic is future work
            main = await self._main_reviewer.review(contract, intent)
            contract = contract.model_copy(update={
                "intent_verdict": intent.verdict,
                "main_verdict": main.verdict,
            })
            if main.verdict == MainVerdict.APPROVED_FOR_CODER:
                approved.append(contract)
        return approved
```

### CLI Commands (`cli/commands/dream.py`)

```
python -m cli.main dream scan          # Run one DreamerAgent + IdeaGate cycle; print approved contracts
python -m cli.main dream list          # List pending IdeaContracts (presented=False)
python -m cli.main dream build <id>    # Load approved IdeaContract and run PlanActFlow on its prompt
```

`dream build <id>` resolves the contract from in-memory store (or future persistence), sets
`PlanActFlowConfig.idea_contract = contract`, then calls the same `AgentRunner` used by `flow run`.

**File:** `cli/main.py` — register the `dream` command group alongside existing `flow` group.

### DI Registration

**File:** `weebot/application/di/_factories.py` — factories for `IntentReviewService`,
`MainReviewService`, `IdeaGate` following the same `_create_plan_critic` pattern.

**File:** `weebot/application/di/__init__.py` — register all three.

---

## Enhancement 4 — VerificationDelta + TrustReport

### New Files

| File | Layer | Purpose |
|------|-------|---------|
| `weebot/domain/models/trust_report.py` | Domain | `VerificationDelta`, `TrustReport`, `TrustBand`, `DeltaVerdict` |
| `weebot/application/ports/trust_report_port.py` | Application | `TrustReportPort` ABC |
| `weebot/application/services/trust_report_service.py` | Application | **Pure computation — zero LLM calls** |
| `tests/unit/test_trust_report_service.py` | Tests | Unit tests |

### Evidence Sources

- **Code review evidence** (per step): `ThoughtEvent.code_review_result` dict on events where
  `code_review_result is not None`. Added in Pre-flight Fix 3 and Task 1b.
- **CoVe evidence** (session-level): `VerificationEvent.consistent` bool per question.
  `VerifyingState` yields these via `step_id="verify"` — they are session-level, not per-step.
  Aggregated as: `cove_passed = all(e.consistent for e in verification_events)`.

This means `VerificationDelta` operates at two granularities:
- **Per-step deltas** (from code review ThoughtEvents)
- **Session-level consistency** (from CoVe VerificationEvents)

The `TrustReport` combines both.

### Domain Models

```python
class DeltaVerdict(str, Enum):
    CONFIRMED        = "confirmed"         # approved by code review
    DRIFT            = "drift"             # approved but CoVe found inconsistency
    REGRESSION       = "regression"        # rejected/revised by code review
    MISSING_EVIDENCE = "missing_evidence"  # no code review signal for this step

class VerificationDelta(BaseModel):
    step_id: str = Field(default="")
    code_review_verdict: Optional[str] = Field(default=None)  # approved/revise/reject
    delta_verdict: DeltaVerdict = Field(default=DeltaVerdict.MISSING_EVIDENCE)
    contributing_issues: list[str] = Field(default_factory=list)

class TrustBand(str, Enum):
    CLEAN       = "clean"        # all confirmed or missing_evidence
    WATCH       = "watch"        # drift detected (CoVe inconsistency)
    INVESTIGATE = "investigate"  # regression present (code review rejection)

class TrustReport(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str = Field(default="")
    trust_band: TrustBand = Field(default=TrustBand.CLEAN)
    deltas: list[VerificationDelta] = Field(default_factory=list)
    cove_passed: Optional[bool] = Field(default=None)
    confirmed_count: int = Field(default=0)
    drift_count: int = Field(default=0)
    regression_count: int = Field(default=0)
    missing_count: int = Field(default=0)
    contributing_factors: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

**Trust band logic:**
- `regression_count > 0` → `INVESTIGATE`
- `drift_count > 0` OR `cove_passed is False` → `WATCH`
- else → `CLEAN`

### Port Interface

```python
class TrustReportPort(ABC):
    @abstractmethod
    async def compute(
        self,
        session_id: str,
        plan_steps: list,           # list[Step]
        session_events: list,       # list[AgentEvent]
    ) -> TrustReport:
        """Deterministic computation. Fail-open: return TrustReport(trust_band=CLEAN)."""
        ...
```

### `TrustReportService` Implementation Shape

No LLM — pure event indexing:
1. Index `ThoughtEvent` where `code_review_result is not None` → `dict[step_id, dict]`
2. Collect all `VerificationEvent` → `cove_passed = all(e.consistent for e in ve_list)`
3. For each `COMPLETED` step in `plan_steps`: build `VerificationDelta` from indexed data
4. Aggregate counts and compute `trust_band`
5. Wrap in `TrustReport`; return safely on any exception

### Integration in CompletedState

**File:** `weebot/application/flows/states/completed.py`

Add after the `SessionStamp` block (before the `post_complete` hook):

```python
# ── TrustReport ─────────────────────────────────────────────────────
if getattr(context, "_trust_report_service", None) is not None:
    try:
        trust_report = await context._trust_report_service.compute(
            session_id=context._session.id,
            plan_steps=context._plan.steps if context._plan else [],
            session_events=context._session.events,
        )
        extra["trust_report"] = trust_report.model_dump()
        context._session = context._session.model_copy(
            update={"context": context._session.context.model_copy(
                update={"extra": extra}
            )}
        )
    except Exception:
        logger.debug("TrustReport failed — non-blocking", exc_info=True)
```

**PlanActFlowConfig and PlanActFlow:**
```python
# plan_act_flow_config.py
trust_report_service: Optional[Any] = None   # TrustReportPort

# plan_act_flow.py __init__
self._trust_report_service = cfg.trust_report_service
```

### DI Registration

**File:** `weebot/application/di/_factories.py`
```python
@staticmethod
def _create_trust_report_service() -> "TrustReportService":
    from weebot.application.services.trust_report_service import TrustReportService
    return TrustReportService()   # no LLM dependency
```

**File:** `weebot/application/di/__init__.py`
```python
self.register("trust_report_service", self._create_trust_report_service)
```

Pass `trust_report_service=container.get("trust_report_service")` in both
`weebot/interfaces/factories.py` and `weebot/application/di/_skillopt.py`.

### Tests

`tests/unit/test_trust_report_service.py`: empty session returns CLEAN, single rejected step
returns INVESTIGATE, failed CoVe returns WATCH, confirmed steps return CLEAN,
mixed regression+drift returns INVESTIGATE (regression wins), exception returns safe default.

---

## Enhancement 5 — RetentionReview

### New Files

| File | Layer | Purpose |
|------|-------|---------|
| `weebot/domain/models/retention_review.py` | Domain | `RetentionReview`, `RetentionVerdict` |
| `weebot/application/ports/retention_agent_port.py` | Application | `RetentionAgentPort` ABC |
| `weebot/application/agents/retention_agent.py` | Application | `RetentionAgent`, `"subagent"` model |
| `tests/unit/test_retention_agent.py` | Tests | Unit tests |

### Domain Model

```python
class RetentionVerdict(str, Enum):
    KEEP    = "keep"     # durable value, keep as reference
    IMPROVE = "improve"  # value exists but quality gaps — surface to user
    PARK    = "park"     # completed, low reuse — archive
    PRUNE   = "prune"    # failed/stale — recommend deletion

class RetentionReview(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str = Field(default="")
    verdict: RetentionVerdict = Field(default=RetentionVerdict.PARK)
    reasoning: str = Field(default="")
    improvement_notes: list[str] = Field(default_factory=list)
    trust_band_at_review: Optional[str] = Field(default=None)
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

### Port Interface

```python
class RetentionAgentPort(ABC):
    @abstractmethod
    async def review(
        self,
        session_id: str,
        session_summary: str,           # plan title + first 5 step descriptions
        trust_report: Optional[dict],   # serialised TrustReport or None
        error_count: int,
        tool_count: int,
    ) -> RetentionReview:
        """Fail-open: return PARK on any error."""
        ...
```

### `RetentionAgent` Implementation Shape

```python
class RetentionAgent(RetentionAgentPort):
    def __init__(self, llm: LLMPort, timeout_seconds: float = 6.0): ...

    async def review(self, session_id, session_summary, trust_report, error_count, tool_count) -> RetentionReview:
        try:
            response = await asyncio.wait_for(
                self._llm.chat(
                    messages=[
                        {"role": "system", "content": _RETENTION_SYSTEM},
                        {"role": "user", "content": self._build_prompt(...)},
                    ],
                    temperature=0.1, max_tokens=300,
                ),
                timeout=self._timeout_seconds,
            )
            data = json.loads(_strip_fences(response.content))
            return RetentionReview(
                session_id=session_id,
                verdict=data["verdict"],
                reasoning=data.get("reasoning", ""),
                improvement_notes=data.get("improvement_notes", []),
                trust_band_at_review=trust_report.get("trust_band") if trust_report else None,
            )
        except Exception:
            return RetentionReview(session_id=session_id, verdict=RetentionVerdict.PARK)
```

Uses `"subagent"` role (`openai/gpt-oss-20b:free`) — lightweight, fast.
**`PRUNE` verdict must never trigger any deletion.** It is a recommendation only.

### Integration in CompletedState

**File:** `weebot/application/flows/states/completed.py`

Add at the very end of `execute()`, after the `post_complete` hook fires. Use
`asyncio.create_task()` so RetentionAgent never delays `DoneEvent`:

```python
# ── RetentionReview (background, non-blocking) ──────────────────────
if getattr(context, "_retention_agent", None) is not None:
    _trust = extra.get("trust_report")
    _plan  = context._plan
    _session_summary = (
        f"{_plan.title}: {', '.join(s.description for s in _plan.steps[:5])}"
        if _plan else "unknown"
    )
    asyncio.create_task(_run_retention_review(
        agent=context._retention_agent,
        session_id=context._session.id,
        session_summary=_session_summary,
        trust_report=_trust,
        error_count=_error_count,
        tool_count=_tool_count,
    ))
```

Add module-level async helper:
```python
async def _run_retention_review(agent, session_id, session_summary, trust_report, error_count, tool_count):
    review = await agent.review(session_id, session_summary, trust_report, error_count, tool_count)
    logger.info("RetentionReview %s: %s — %s", session_id, review.verdict, review.reasoning[:120])
```

The `_error_count` and `_tool_count` variables are already computed earlier in `CompletedState`
by the `post_complete` hook block — reuse them.

**PlanActFlowConfig and PlanActFlow:**
```python
# plan_act_flow_config.py
retention_agent: Optional[Any] = None   # RetentionAgentPort

# plan_act_flow.py __init__
self._retention_agent = cfg.retention_agent
```

### DI Registration

**File:** `weebot/application/di/_factories.py`
```python
@staticmethod
def _create_retention_agent() -> "RetentionAgent":
    from weebot.application.agents.retention_agent import RetentionAgent
    llm = FactoriesMixin._create_llm_for_role("subagent")
    return RetentionAgent(llm=llm, timeout_seconds=6.0)
```

**File:** `weebot/application/di/__init__.py`
```python
self.register("retention_agent", self._create_retention_agent)
```

Pass `retention_agent=container.get("retention_agent")` in `weebot/interfaces/factories.py`.

### Tests

`tests/unit/test_retention_agent.py`: successful KEEP/IMPROVE/PARK/PRUNE routing,
timeout returns PARK, JSON parse error returns PARK, trust_band_at_review populated from
trust_report dict, PRUNE verdict does not trigger deletion.

---

## Build Sequence

Execute phases in order. Each phase can be committed independently.

```
Phase 0 — Pre-flight fixes (single commit)
  weebot/core/model_cascade_config.py             add reviewer + dreamer roles
  weebot/application/ports/event_store_port.py    add query_recent_events abstract method
  weebot/infrastructure/event_store.py            implement query_recent_events
  weebot/domain/models/event.py                   add ThoughtEvent.code_review_result
  weebot/application/services/opportunity_engine.py  fix mutation bug

Phase 1 — Enhancement 1 completion
  weebot/application/flows/states/reviewing.py    populate code_review_result on ThoughtEvent
  weebot/application/di/_factories.py             _create_code_reviewer
  weebot/application/di/__init__.py               register code_reviewer
  weebot/interfaces/factories.py                  pass code_reviewer
  weebot/application/di/_skillopt.py              pass code_reviewer
  tests/unit/test_code_reviewer_service.py        9 tests
  tests/unit/test_reviewing_state.py              8 tests

Phase 2 — Domain models (all parallel, no deps on each other)
  weebot/domain/models/idea_contract.py
  weebot/domain/models/intent_review.py
  weebot/domain/models/main_review.py
  weebot/domain/models/trust_report.py
  weebot/domain/models/retention_review.py

Phase 3 — Ports (all parallel, depend on Phase 2 models)
  weebot/application/ports/dreamer_port.py
  weebot/application/ports/intent_review_port.py
  weebot/application/ports/main_review_port.py
  weebot/application/ports/trust_report_port.py
  weebot/application/ports/retention_agent_port.py

Phase 4 — TrustReportService (no LLM, implement + test first)
  weebot/application/services/trust_report_service.py
  tests/unit/test_trust_report_service.py

Phase 5 — LLM services and agents (all parallel)
  weebot/application/services/intent_review_service.py
  weebot/application/services/main_review_service.py
  weebot/application/services/idea_gate.py
  weebot/application/agents/dreamer.py
  weebot/application/agents/retention_agent.py

Phase 6 — Flow integration
  weebot/application/models/plan_act_flow_config.py  add 4 new fields
  weebot/application/flows/plan_act_flow.py           store 4 new services from config
  weebot/application/flows/states/completed.py        TrustReport block + RetentionReview task

Phase 7 — DI wiring
  weebot/application/di/_factories.py    factories for all 4 new services/agents
  weebot/application/di/__init__.py      register all 4
  weebot/interfaces/factories.py         pass all 4 to create_flow()
  weebot/application/di/_skillopt.py     pass trust_report_service
  weebot/application/di/_capabilities.py extend opportunity_scan with dreamer pass

Phase 8 — CLI
  cli/commands/dream.py      dream scan / dream list / dream build commands
  cli/main.py                register dream command group

Phase 9 — Remaining tests
  tests/unit/test_dreamer_agent.py
  tests/unit/test_idea_gate.py
  tests/unit/test_intent_review_service.py
  tests/unit/test_main_review_service.py
  tests/unit/test_retention_agent.py
```

---

## Architecture Invariants (must hold after all phases)

1. **Dependency direction**: no domain model imports from application or infrastructure.
   `IdeaContract`, `IntentReview`, `MainReview`, `TrustReport`, `RetentionReview` are all pure
   Pydantic models with no outer imports.

2. **Fail-open**: every LLM-backed service/agent returns a safe default on any exception.
   `DreamerAgent` → `[]`, `IntentReviewService` → `NOT_READY`, `MainReviewService` → `DEFERRED`,
   `RetentionAgent` → `PARK`. `TrustReportService` → `TrustReport(trust_band=CLEAN)`.

3. **No self-approval**: `DreamerAgent` produces `IdeaContract` objects with no verdict fields
   set. `IdeaGate` sets `intent_verdict` and `main_verdict` via `model_copy()` on the contracts.
   `DreamerAgent` class has no `approve()` method.

4. **PRUNE is recommendation-only**: `RetentionAgent.review()` never calls any delete,
   archive, or mutation method. It only returns a `RetentionReview` object.

5. **Backward compatibility**: all 4 new `PlanActFlowConfig` fields default to `None`.
   Existing flows without these services run identically to before.

6. **Immutability**: all domain model mutations use `model_copy(update=...)`. The pre-existing
   `ctx.extra[key] = value` pattern in `VerifyingState` and `CompletedState` is preserved as-is
   to avoid scope creep, but new writes in E4/E5 use `model_copy`.

7. **Cross-lab diversity**: `"reviewer"` (OpenAI OSS) is different lab from executor
   (`"executor"` → Qwen Coder). `"dreamer"` (Kimi) and `"verifier"` (NVIDIA) are separate
   from each other and from `"critic"` (OpenAI). `"subagent"` for retention shares no lab
   lock with any other role.

---

## Verification

### After Phase 0 (pre-flight)
```bash
python -m pytest tests/ -v -k "opportunity"           # existing OE tests still pass
python -m cli.main health                              # system health check
```

### After Phase 1 (E1 complete)
```bash
python -m pytest tests/unit/test_code_reviewer_service.py tests/unit/test_reviewing_state.py -v
python -m cli.main flow run "write a hello world python script"
# Expect: REVIEWING status appears in CLI output between step completion events
```

### After Phase 4 (TrustReport)
```bash
python -m pytest tests/unit/test_trust_report_service.py -v
python -m cli.main flow run "write a sorting function in python"
# Expect: CompletedState logs "TrustReport session=<id> band=clean"
```

### After Phase 5 (all agents)
```bash
python -m pytest tests/unit/test_dreamer_agent.py tests/unit/test_idea_gate.py -v
python -m pytest tests/unit/test_retention_agent.py -v
```

### After Phase 8 (CLI)
```bash
python -m cli.main dream scan
# Expect: "Dreamer produced N idea contracts", lists approved ones with heat scores
python -m cli.main dream list
# Expect: table of pending contracts
python -m cli.main dream build <contract_id>
# Expect: PlanActFlow runs on the contract's prompt, with idea_contract context in plan
```

### Full regression
```bash
python -m pytest tests/ -v --cov=weebot --cov-report=term-missing
# Target: existing tests all pass, new tests bring coverage up
```
