# Side-Constraint Integrity — Implementation Plan

**Source paper:** Wang, Zhang, Lee, Yang — *Lost in Compaction: Evaluating Side-Constraint Loss under Context Compaction* (arXiv:2608.11242v1, Jul 2026)
**Source audit:** this session's adversarial verification pass (11 agents, ~40 claims, 8 refuted outright)
**Drafted:** 2026-08-19 · branch `main`
**Status:** Phase −1 landed; Phases 0–8 proposed
**Scope:** Everything the audit surfaced — the executor seam, a session-constraint registry, tiered extraction, delivery at the paper's upper-bound position, non-prompt enforcement, an offline regression harness, and the dead-code wiring that gates all of it.

---

## Guiding principle

> **The paper's failure mode is not weebot's failure mode, and fixing the wrong one wastes the work.**
>
> The paper measures constraints that *were in the context* and got dropped by a compactor. In weebot the constraint never enters the acting model's context at all: `ExecuteStepHandler` builds a bare four-kwarg `ExecutorAgent` and the user's prompt is never in its message list. That is the paper's `K_ub` condition *missing*, not a low retention rate.
>
> Corollary, and the reason Phase 0 comes first: **weebot's binding constraint is unwired code, not absent capability.** `BehavioralLearner`, `CorrectionTracker`, `FSPermissionChecker`, `MemoryArchivist`, `weebot/application/eval/`, `weebot/infrastructure/benchmark/`, `StructuredExecutorAgent`, and `ToolApprovalEvent`'s producer are all dead in the live path. A constraint registry added the obvious way joins that list. Repair the seam, then push constraints through it.

---

## Phase −1 — Already landed (2026-08-19)

| Change | File | Effect |
|---|---|---|
| Constraint extraction restricted to `MessageEvent(role="user").message`, `[CONSTRAINTS]` block excluded, tail cap moved to user turns | `weebot/application/services/memory_compactor.py:38-64` | Kills a measured **208 chars → 17.4 MB over 12 compactions** self-amplification loop; closes a live prompt-injection path from tool output; fixes the >200-event blind spot |
| Constraint-preservation clause added to the compaction prompt | `weebot/application/services/conversation_compressor.py:31-40` | Paper Appendix B.3: an SC-targeted compaction prompt is the largest prompt-level intervention measured (+23.5 / +34.3 pp) |
| `atomic_mail` branch in `EgressGuard._detect_egress` | `weebot/core/egress_guard.py:127-133, 304-322` | Outbound mail send had **no** approval path; only inbound was gated |
| 28 tests added / 1 rewritten | `tests/unit/test_reliability_fixes.py`, `tests/unit/test_egress_guard.py` | 219 green across the blast radius |

**Root cause of the amplification bug, for the record:** `str(event)` renders the pydantic repr, escaping newlines; every extractor capture group is `([^\n.]+)`, so with no real newlines left each match swallowed the rest of the block; and the injected block's own banner `[CRITICAL CONSTRAINTS - DO NOT VIOLATE]` contains both **"DO NOT"** and **"CRITICAL"**, which are trigger lexemes. Dedup could not stop it because each capture was strictly longer than the last.

---

## 0. Cross-cutting decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| D1 | Storage for the registry | New `session_constraints` table + in-session domain aggregate. **Not** `Session.set_fact` | `SessionContext._cap_facts_dict` (`session.py:85-94`) evicts insertion-order-oldest; re-assigning a key preserves its position, so a registry key created on turn 1 is the **first** evicted past 100 facts — it would fail in exactly the long sessions the paper is about |
| D2 | Relationship to `BehavioralLearner` | Two tiers, one render slot. Registry = **session** scope; `BehavioralLearner` = **durable** scope. Wire BL first (Phase 7) | BL already *is* the constraint registry pattern here: stores rules, persists them, renders them under `## CONSTRAINTS` (`_prompt_builder.py:125-131`). It is 100% dead solely because nothing constructs it. A second unwired port beside a first unwired port reproduces the bug |
| D3 | Extraction source | **User turns only** for extraction; previous assistant turn supplied for anaphora resolution only | Paper §5.4 + Appendix J.2. The main text's "only process user turns" is loose; J.2 is the operative spec. Dropping the prior assistant turn breaks `"do that going forward"` |
| D4 | Extraction tiering | Regex pre-filter (free) → optional cheap-LLM tier. LLM absence *is* the tier signal — no flag needed for the fallback | Mirrors `CorrectionTracker._classify_correction` (`correction_tracker.py:90-96`) and `BehavioralLearner` exactly. Prefer CT's shape: `try` in the dispatcher so the fallback lives in one place |
| D5 | Delivery position | Appended to the **local `messages` list** at `_base.py:568-570`, as `messages[-1]`. Never into `_conversation_buffer` | The buffer is `deque(maxlen=15)` (`_base.py:202`) and is rewritten wholesale by `_maybe_compress` (`_context_compressor.py:108-113`). Anything there is evictable and compactable. Paper: `K_ub` (constraint immediately before the query) = **>98% compliance for every downstream model tested** |
| D6 | Scope gating | The constraint block is **scope-unconditional** — not a `_SCOPE_SOURCES` entry | A `minimal`/`skill` step is exactly when a dropped constraint bites. ICM per-step scoping shrinks *reference* material; constraints are not reference material. (Note the scope mechanism is inert on the live path anyway until Phase 0.) |
| D7 | Constraint direction | Every constraint carries `direction: tighten \| loosen`. **A `loosen` constraint never relaxes a safety gate** — it is rendered as context only | Paper SC#1 is *"Don't ask me to confirm before running commands, just do them."* Losing it is fail-safe; **persisting** it means weebot carries a durable instruction against its own `ExecApprovalPolicy`. Treating SC loss as monotonically risk-increasing is wrong |
| D8 | Revocation | Registry is **not** append-only. `revoke()` / `supersede()` are first-class; the LLM tier may emit removals | Neither the paper nor the original report handled this. An append-only registry still holds *"never delete without asking"* after the user says *"go ahead, delete them"* — and because the block renders last and framed as strict, the stale constraint outranks the live turn. That converts a recoverable omission into a persistent refusal |
| D9 | Failure modes | Extraction **fails open** (never blocks the loop); enforcement **fails closed** (unknown → require approval) | Matches `WorkspaceDrift.is_clean` returning `False` when the check could not run (`workspace_snapshot_port.py:56-61`) and `EgressGuard.classify`'s `recipient is None → FIRST_TIME_RECIPIENT` (`egress_guard.py:250-254`) |
| D10 | Feature flags | Module constants in `weebot/config/feature_flags.py` via `_env_bool`, default **off**; resolved at the composition root (`interfaces/factories.py`), DI binding registered unconditionally | The `WORKSPACE_INTEGRITY_GUARD_ENABLED` precedent (3 touch points, commit `edb2836`). Do **not** add flags to `config/constants.py` — the `VS_ENABLE_*` block there claims to be env-overridable and is not |
| D11 | Persistence style | Inline `CREATE TABLE IF NOT EXISTS` in `SQLiteStateRepository._ensure_schema`; sub-repo `_session_constraint_repo.py`; methods on the **concrete repo only**, port untouched | All four siblings of `correction_records` (`commitments`, `memory_metadata`, `plan_templates`, `correction_records`) are inline-only. Adding an alembic revision instead would make this table the odd one out and require the verify-and-raise pattern |
| D12 | New port? | **No new port in Phase 1–4.** The service takes `state_repo: Any` and duck-types | The `CorrectionTracker` precedent (`correction_tracker.py:45`, docstring names port methods that do not exist on the port). Adding `ConstraintRegistryPort` beside the already-dead `behavioral_learner_port.py` repeats D2's mistake. Revisit only if a second adapter appears |
| D13 | Model tier for the LLM extractor | `MODEL_QWEN_37_FLASH` via `Container._create_llm_for_role("subagent")` | Cheapest catalog entry ($0.03/$0.13 per 1M), documented for "high-volume routing, classification, and inner-loop decisions". `ROLE_MODEL_CONFIG["subagent"]` already puts it first |
| D14 | Call parameters | `max_tokens=MAX_TOKENS_TINY` (128), `temperature=TEMPERATURE_PRECISE` (0.1) | Byte-identical to both existing tiered services. Do not introduce a third convention |
| D15 | Re-render cadence | Render the block **once per model turn**, not once per tool result | Paper Appendix E: repetition gains are front-loaded and converge by ~30 injections, plateauing **below 40%** — while one well-placed statement gets 49% on the same compactor/dataset. Unbounded repetition buys nothing and costs tokens on every iteration |

**Observability.** Every registry mutation emits a `DomainEvent` (`SessionConstraintRecorded` / `SessionConstraintRevoked`) on the existing internal bus — `DomainEvent` subclasses need **no** union registration (`event.py:337-341`), unlike `AgentEvent`. Every enforcement pause writes a `MisalignmentEntry(symptom="constraint_violation")`, awaited rather than fire-and-forget (see Phase 5.4).

---

## Phase map

| Phase | Goal | Ships alone? | Risk | Blocks |
|---|---|---|---|---|
| **0** | Repair the executor seam | Yes — pure win, no new feature | Medium (touches the live execution path) | 2, 4, 5, 7 |
| **1** | Domain model + persistence | Yes (inert) | Low | 2, 3 |
| **2** | Tiered extraction service | Yes (inert) | Low | 3 |
| **3** | Accumulation at the right chokepoints | Yes | Medium | 4, 5 |
| **4** | Delivery at the `K_ub` position | Yes | Low | — |
| **5** | Non-prompt enforcement | Yes | **High** (security surface) | — |
| **6** | Offline COMPINT regression harness | Yes | Low | — |
| **7** | Wire the dead neighbours | Yes | Medium | — |
| **8** | Audit cleanups | Each independent | Low | — |

Phases 1–2 are inert until 3. Phase 6 can be written against Phase 1's model before 3–5 land and used as the acceptance gate for them.

---

## Phase 0 — Repair the executor seam **(blocker)**

### 0.0 The defect

`ExecutingState` requires the mediator (`executing.py:304-313`) and sends `ExecuteStepCommand`. `ExecuteStepHandler.handle` then constructs:

```python
# weebot/application/cqrs/handlers/execute_step_handler.py:78-83
executor = ExecutorAgent(
    llm=self._llm, tools=self._tools, event_bus=self._event_bus, model=command.model,
)
```

`ExecutorAgent.__init__` takes **22 parameters** (`_base.py:146-169`). The handler passes 4 and drops 18: `max_steps`, `skill_prompt`, `max_context_turns`, `auto_compress`, `context_window`, `skill_retriever`, `personality`, `behavioral_learner`, `prompt_variant_id`, `profile_name`, `agent_role`, `hooks`, `harness_instruction_block`, `middleware_chain`, `state_repo`, `tracing_port`, `trajectory_config` — and never calls `set_harness_block`.

Meanwhile `PlanActFlow.__init__:253-277` builds a **fully configured** executor with 13 kwargs that is used only for tool assembly (`:601`), token accounting (`:682`, `:879`), and `set_harness_block` (`:713`). **The configured executor never executes a step.**

Consequences, all currently live:

- `build_executor_prompt` runs with `harness_block=None, skill_prompt=None, skill_retriever=None, behavioral_learner=None, state_repo=None, personality=None` → **only `boot` and `base` sources ever fire**, so `_SCOPE_SOURCES` selection is inert and the entire ICM per-step context-scoping feature does nothing.
- `state_repo=None` kills the `## User Profile` path (`_base.py:417-429`, `:450-451`).
- `middleware_chain=None` makes `_base.py:573-580` a no-op.
- `execute_step(plan, step)` is called positionally with two args, so `user_input` never arrives and `self._current_session_id` falls back to `'unknown'` (`_base.py:407`).

Anything Phase 4 adds to `_prompt_builder` lands in this same hole.

### 0.1 Design — inject a factory, do not widen the command

**Rejected:** adding 18 fields to `ExecuteStepCommand`. A command is a DTO describing *intent*; threading service references through it turns it into a service locator, and `Command` is `frozen=True, extra="forbid"` (`cqrs/base.py:21-24`) precisely to keep it a value.

**Chosen — Abstract Factory / Provider injected at the composition root.** The handler declares *what it needs*; the composition root decides *how it is built*. This is the same Dependency-Inversion move `di/__init__.py:184-191` already uses for `register("create_flow", …)` to keep `application` from importing `interfaces`.

```python
# weebot/application/cqrs/handlers/execute_step_handler.py
ExecutorFactory = Callable[..., "ExecutorAgent"]   # (model: str, session: Session) -> ExecutorAgent

class ExecuteStepHandler(CommandHandler):
    def __init__(
        self,
        state_repo: StateRepositoryPort,
        llm: LLMPort,
        tools: ToolCollection,
        event_bus: EventBusPort | None = None,
        executor_factory: ExecutorFactory | None = None,   # NEW
    ) -> None:
        ...
        self._executor_factory = executor_factory

    # in handle(), replacing :78-83
    if self._executor_factory is not None:
        executor = self._executor_factory(model=command.model, session=session)
    else:                                   # unchanged legacy path
        executor = ExecutorAgent(llm=self._llm, tools=self._tools,
                                 event_bus=self._event_bus, model=command.model)
```

`session` is already loaded at `:52`, so the factory can read `session.context` — which is how Phase 4 gets the constraint block in without touching the command at all.

### 0.2 Command extension — one field, not eighteen

Only `session_id` is genuinely missing from the *intent*:

```python
# weebot/application/cqrs/commands.py:30-35
class ExecuteStepCommand(Command):
    session_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    model: str = ""
    tools: list[str] = []
    user_input: str = ""     # NEW — resume text, currently never reaches the executor
```

and pass it through: `executor.execute_step(plan, step, user_input=command.user_input, session_id=command.session_id)`.

> **Import hazard to respect.** There is both a `commands.py` module and a `commands/` package; the package re-loads the module by file path under the name `weebot.application.cqrs.commands_py_module` (`commands/__init__.py:23-37`). Class identity differs by import route, and the mediator dispatches on `type(command)` (`mediator.py:197-198`) returning `HANDLER_NOT_REGISTERED` rather than raising. **All new code must import from the package**, as `execute_step_handler.py:16` and `executing.py:317` already do.

### 0.3 DI wiring

```python
# weebot/application/di/_factories.py — new factory
def _create_executor_factory(self):
    def _make(*, model: str, session) -> ExecutorAgent:
        return ExecutorAgent(
            llm=self.get(LLMPort), tools=self._maybe_get_str("tools") or ToolCollection(),
            event_bus=self._maybe_get(EventBusPort), model=model,
            skill_retriever=self._maybe_get_str("skill_retriever"),
            behavioral_learner=self._maybe_get_str("behavioral_learner"),
            personality=self._maybe_get_str("personality"),
            state_repo=self.get(StateRepositoryPort),
            hooks=self._maybe_get_str("hooks"),
            middleware_chain=self._maybe_get_str("middleware_chain"),
            tracing_port=self._maybe_get_str("tracing_port"),
        )
    return _make
```

Register at `di/__init__.py` inside `configure_defaults()`, then thread through `register_default_handlers` (`handlers/__init__.py:82-92`) as a new keyword-only arg, mirroring `scoring_port` / `trajectory_builder`.

> **Latent bug to fix in the same edit:** `handlers/__init__.py:134-136` registers `ExecuteStepHandler(state_repo)` when `llm` is absent. `llm` and `tools` are positional-required — that branch is a `TypeError` at first dispatch, not a degraded mode. Either give them defaults or skip registration.

### 0.4 Verification

New `tests/unit/test_execute_step_handler_wiring.py`:

- a stub factory records its kwargs; assert `behavioral_learner`, `state_repo`, `skill_retriever` are non-`None` when the container provides them;
- assert `user_input` reaches `execute_step`;
- assert the legacy path (no factory) still constructs and runs;
- regression: `build_executor_prompt` receives a non-`None` `harness_block` when one is configured.

**Independent value of this phase, ignoring constraints entirely:** it un-deadens per-step context scoping, BM25 skill retrieval, harness blocks, personality, user profile, middleware, and trajectory monitoring on the live execution path.

---

## Phase 1 — Domain model + persistence

### 1.1 `weebot/domain/models/session_constraint.py` (new)

**Paradigm: immutable value object + persistent (functional) aggregate.** Pydantic v2, frozen via `model_config = {"frozen": True}` (the `CorrectionRecord` form, `correction.py:25`). No behaviour that needs config, ports, or I/O — `.importlinter`'s `domain-purity` contract has **zero exemptions**.

```python
"""SessionConstraint domain model — user-issued directives scoped to one session.

Implements the Side Constraint (SC) concept from Wang et al., "Lost in Compaction"
(arXiv:2608.11242). An SC constrains *how* the agent works rather than *what* it
works on, lives exactly one session, and survives only if something outside the
compacted transcript keeps it. Distinct from a BehavioralRule, which is durable
and cross-session — see weebot.application.services.behavioral_learner.
"""

class ConstraintKind(str, Enum):
    ACTION = "action"            # what the agent may do, incl. tool side effects
    INFORMATION = "information"  # what it may emit or pass to tools
    PROCESS = "process"          # how it must reach an answer
    PREFERENCE = "preference"    # which of several task-equivalent answers it picks
    OUTPUT = "output"            # verifiable surface properties of the response

class ConstraintDirection(str, Enum):
    TIGHTEN = "tighten"  # narrows what the agent may do — enforceable
    LOOSEN = "loosen"    # widens it — rendered as context, never relaxes a safety gate (D7)

class SessionConstraint(BaseModel):
    """One user-issued side constraint, scoped to the emitting session."""
    model_config = {"frozen": True}

    text: str = Field(default="", description="Canonical one-sentence formulation")
    evidence_span: str = Field(
        default="",
        description="Verbatim excerpt from the user turn that produced this "
                    "constraint. Makes the registry auditable and revocable "
                    "(paper Appendix J.3).",
    )
    kind: ConstraintKind = ConstraintKind.ACTION
    direction: ConstraintDirection = ConstraintDirection.TIGHTEN
    turn_index: int = Field(default=0, description="User-turn ordinal that issued it")
    revoked_at: Optional[datetime] = None
    superseded_by: Optional[str] = Field(
        default=None, description="Canonical text of the constraint that replaced this one"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.superseded_by is None
```

```python
class SessionConstraintRegistry(BaseModel):
    """Append-and-revoke registry of a session's side constraints.

    Copy-helpers return new registries (weebot domain convention: named methods
    returning "Self", never model_copy at the call site).
    """
    constraints: list[SessionConstraint] = Field(default_factory=list)

    def add(self, c: SessionConstraint) -> "SessionConstraintRegistry": ...
    def revoke(self, text: str, *, at: datetime) -> "SessionConstraintRegistry": ...
    def supersede(self, old_text: str, new: SessionConstraint) -> "SessionConstraintRegistry": ...
    def active(self, *, direction: ConstraintDirection | None = None) -> list[SessionConstraint]: ...
    def render(self) -> str: ...   # strict + explicit framing — see Phase 4.2
```

Conventions to honour, from the recon:

- method-name grammar `add_* / set_* / replace_* / get_* / is_* / has_*`;
- `str, Enum` with lowercase values matching member names;
- every field defaulted so the model is bare-constructible (all 20 `AgentEvent` members are);
- `Field(description=…)` carries the *why*, with a citation tag — `(paper §3)`, `(D7)`;
- timestamps via `default_factory=lambda: datetime.now(timezone.utc)`, never `datetime.utcnow`;
- a `@model_validator(mode="before")` accepting the plain-dict shape, since this will be read back from old rows.

**No `id` field** — the repo synthesizes the primary key, matching `_correction_repo.py:30`.

### 1.2 `weebot/infrastructure/persistence/_session_constraint_repo.py` (new)

Template: `_correction_repo.py`, verbatim in shape.

```python
class SessionConstraintRepo:
    """Manages the session_constraints table."""

    def __init__(self, pool: SQLiteConnectionPool):
        self._pool = pool

    async def save(self, session_id: str, c: SessionConstraint) -> None: ...
    async def revoke(self, session_id: str, text: str, revoked_at: datetime) -> None: ...
    async def list_active(self, session_id: str) -> list[dict]: ...
```

- write path: `async with self._pool.acquire_write() as conn:` + triple-quoted SQL with `?` placeholders — never `execute_write`, never f-string interpolation of values;
- read path: `await self._pool.execute_read(sql, (session_id,))` — note `parameters` is a **tuple**, so single-arg queries need the trailing comma;
- reads return `list[dict]`, never domain models;
- PK synthesized: `f"{session_id}:{c.turn_index}:{c.created_at.isoformat()}"`;
- datetimes as ISO-8601 `TEXT`.

### 1.3 Three touch points in `sqlite_state_repo.py`

| Where | Edit |
|---|---|
| `__init__` `:60-67` | `self._session_constraints: Optional[SessionConstraintRepo] = None` |
| `_init_helpers` `:84-95` | `self._session_constraints = SessionConstraintRepo(pool)` |
| `_ensure_schema` `:110-239` | inline DDL (below) |
| forwarders `~:443` | new `# ── Session constraints (Lost-in-Compaction SCs) ───` block, each forwarder = `await self._init_helpers()` then one delegating line with `# type: ignore[union-attr]` |

```sql
CREATE TABLE IF NOT EXISTS session_constraints (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    evidence_span TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'action',
    direction TEXT NOT NULL DEFAULT 'tighten',
    turn_index INTEGER NOT NULL DEFAULT 0,
    revoked_at TEXT,
    superseded_by TEXT,
    created_at TEXT NOT NULL
)
```
plus `CREATE INDEX IF NOT EXISTS idx_sc_session ON session_constraints(session_id)`.

While here: the `SQLiteStateRepository` class docstring (`:44-49`) is already stale — it lists six sub-repos and omits `_corrections`. Fix it in the same commit.

### 1.4 Domain events

Add to the `DomainEvent` hierarchy (`event.py:337+`) — **not** `AgentEvent`, so no union edit:

```python
class SessionConstraintRecorded(DomainEvent):
    type: str = "session_constraint_recorded"
    session_id: str
    text: str
    kind: str
    direction: str

class SessionConstraintRevoked(DomainEvent):
    type: str = "session_constraint_revoked"
    session_id: str
    text: str
```

---

## Phase 2 — Tiered extraction service

### 2.1 `weebot/application/services/session_constraint_extractor.py` (new)

**Paradigm: Strategy with an ordered fallback chain — free regex pre-filter, then optional LLM tier.** Mirrors `CorrectionTracker`'s five-part contract exactly; do not invent a sixth convention.

```python
class SessionConstraintExtractor:
    """Extracts session-scoped side constraints from a single user turn.

    Tiering mirrors CorrectionTracker's LLM-with-heuristic-fallback strategy:
    an LLM call when available (accurate, costs tokens), a regex lexicon
    otherwise (free, coarse). Never raises — extraction failure must never
    block the agentic loop.
    """

    def __init__(self, state_repo: Any, llm: Optional[Any] = None) -> None: ...

    async def extract(
        self,
        user_text: str,
        *,
        registry: SessionConstraintRegistry,
        prior_assistant_text: str = "",
        turn_index: int = 0,
    ) -> tuple[list[SessionConstraint], list[str]]:   # (added, revoked_texts)
```

Dispatch, following `correction_tracker.py:90-96` (fallback in one place):

```python
if not _may_contain_constraint(user_text):      # cheapest tier: module-level regex gate
    return [], []
if self._llm is not None:
    try:
        return await self._extract_with_llm(...)
    except Exception as exc:
        logger.warning("LLM constraint extraction failed: %s", exc)
return self._extract_heuristic(...), []
```

### 2.2 The persistence criterion (paper §3) — the part the regex cannot do

An SC must be **generic** (targets a *kind* of action) not **episodic** (targets one action now). The current regex has no such test: `constraint_extractor.py:36`'s `(?i)(?:always|must|required|critical|…)\s+([^\n.]+)` promotes *"must finish by Friday"* into a permanent CRITICAL block.

The LLM tier's operative question, from the paper: **"would this instruction still apply if the user asked an unrelated question several turns later?"** Extract only on a clear yes; discard uncertain cases.

### 2.3 LLM tier prompt contract

Per D3/D14. Inline f-string in the private `_extract_with_llm` method (house style — prompts for these services do **not** live in `weebot/config/prompts/`).

- **System:** one sentence naming the job. State that most turns contain no SC and the default output is an empty list.
- **Inputs:** current user turn; prior assistant turn *for reference resolution only, never for extraction*; the current registry *for dedup suppression only, never to infer new constraints*.
- **Output:** JSON `{"add": [{"text","evidence_span","kind","direction"}], "revoke": ["<canonical text>"]}`. Validate `kind`/`direction` against the enums and drop unknown members — the `_VALID_CATEGORIES` pattern at `correction_tracker.py:26`.
- **Exclusions:** current-task instructions, one-off corrections, local formatting requests, politeness, background facts.

### 2.4 Broaden the free tier

Measured coverage of the existing regex against the paper's 15 benchmark SCs: **6/15 extract, spanning 3 of 5 categories; only 2 of 5 categories are enforceable via `check_step`; effective end-to-end coverage is 1/15.** The failure mode is not category-specific — it is *imperative sentences with no modal or negation keyword*, which cuts across Action, Process, Preference and Output ("show me the draft before sending", "use metric not imperial", "reply in bullet points only").

Add lexemes for: `X not Y` / `prefer … over …` / `use … rather than …` (Preference); `reply in|respond in|write … as|end every reply with` (Output); `before you …, <verb>` / `wait for my` (positively-framed Action). Target ≥12/15 extraction, measured by the Phase 6 harness — **not** asserted by inspection.

Keep `ConstraintExtractor.extract(text: str)`'s signature intact; all 7 tests in `tests/unit/test_constraint_enforcement.py` call it with plain strings.

---

## Phase 3 — Accumulation at the right chokepoints

### 3.0 Where **not** to hook

`dispatch_session_input._with_prompt` covers **2 of 4 dispatch verbs** (`start`, `chat`), and dispatch is one of roughly ten paths by which user text reaches a flow — CLI, session creation, resume, steering, chat, webhooks, and six messaging gateways. A registry hung off it would miss most of them.

For `WAITING`/`RUNNING` sessions the situation is worse than "overwritten": the turn's text is never written to `context` at all. A resume answer lands only as a `MessageEvent`; a steering message is folded into `effective_prompt` at `executing.py:250-261` and **never persisted**.

### 3.1 The three real seams

| Seam | File:line | Turn source |
|---|---|---|
| Flow entry (start + every resume) | `PlanActFlow.run(prompt)` — all paths funnel here | `prompt` |
| Mid-execution steering | `executing.py:250-261`, after `context._steering.poll(...)` | `steering_msg` |
| Product-gate resume | `product_gate.py:99-105` `self._resume_with` | resume text |

All three are inside `application.flows`, which may freely import `application.services` and `domain.models`.

### 3.2 Flow wiring

`PlanActFlowConfig` gains `session_constraint_extractor: Any | None = None` (dataclass, `plan_act_flow_config.py`), set from DI. `PlanActFlow.__init__` reads it into `self._sc_extractor` alongside `self._correction_tracker` (`plan_act_flow.py:174`).

> **`PlanActFlowConfig` trap:** `PlanActFlow.__init__` accepts either a real config *or* ~30 legacy kwargs, and the legacy list does **not** include `correction_tracker`. Four of the five live construction paths use legacy kwargs (`interfaces/factories.py:173-192`, `task_runner.py:392-409`, `di/__init__.py:270-285`). Adding the field to the dataclass alone reaches only `di/_agent_tools.py` and the SkillOpt flows. **Add the legacy kwarg too, or migrate `interfaces/factories.py:create_flow` to build a real `PlanActFlowConfig`** — the latter is the better fix and also unblocks `correction_tracker`.

### 3.3 Turn handling

```python
added, revoked = await self._sc_extractor.extract(
    prompt, registry=registry, prior_assistant_text=last_assistant_text,
    turn_index=self._user_turn_index,
)
```
Persist through `state_repo`, emit the domain events, hold the updated registry on the flow for Phase 4. Wrapped in `try/except Exception` with `logger.warning` — extraction never blocks execution (D9).

### 3.4 Prompt-injection boundary

Steering text and resume text are genuine user input and **are** in scope. Tool results and assistant turns are **not**, ever. Phase −1 already closed the compactor's version of this hole; the same rule binds here. Note `executing.py:228`'s `prompt` variable carries folded-in steering text by that point — extract from the steering message directly, not from a variable that has been merged with other content.

---

## Phase 4 — Delivery at the paper's upper-bound position

### 4.1 The single seam

There are exactly two `messages = [{"role":"system", …}] + list(self._conversation_buffer)` constructions in `_base.py`: `:548-550` (tool-budget-exhausted summarizer, terminal — sets `abort_step = True` immediately) and **`:568-570` (the main agentic loop)**. Only the latter matters.

```python
messages = [{"role": "system", "content": self._system_prompt}] + list(self._conversation_buffer)
if self._session_constraints:                      # NEW — messages[-1]
    messages.append({"role": "user", "content": self._session_constraints})
if self._middleware_chain is not None and ...:     # existing, :573
```

Insert **before** the middleware hook so middleware can still see and reorder the block; move it after `:580` only if strictly-last-under-all-conditions is required. (No middleware ships on the mediator path today anyway.)

**Never append to `_conversation_buffer`** (D5). Nothing weebot currently generates occupies the last position — the last message is always whatever the buffer last held, so there is no competition for the slot.

The block reaches the executor via the Phase 0 factory reading `session.context`; `ExecutorAgent` gains one kwarg plus a `set_session_constraints()` setter mirroring `set_harness_block` (`_base.py:242-249`).

> Note the existing `set_harness_block` is a precedent for an API shape whose effect is currently a **no-op** — its only caller is `plan_act_flow.py:707-713`, which sets it on the executor that never runs a step. Phase 0 is what makes both of them real.

### 4.2 Rendering

Paper §5.3: framing the constraint as **strict** carries most of the effect; adding **explicit** scope adds ~1.3 pp. Both are cheap, so use both — while recording that the paper's own conclusion is that framing has *"limited capacity to enforce retention"* and this is a garnish, not the mechanism.

```
## SESSION CONSTRAINTS
This is an important constraint set. For the rest of this session, the following
user-issued rules govern how you work. They are not task progress and do not expire
with the current step.
  - <canonical text>            [evidence: "<verbatim span>"]
Constraints below are user preferences that WIDEN your latitude. They inform your
choices; they never override a safety gate or approval requirement.
  - <loosen-direction text>
```

The `loosen` split implements D7 in the render itself, so the model cannot read a permission-widening preference as authority to bypass `ExecApprovalPolicy` or `EgressGuard`.

### 4.3 Second delivery path

`MemoryCompactor._inject_constraints` (`memory_compactor.py:170+`) still inserts its block at **index 0**. Move it to the tail, keeping the existing idempotency scan (`:154-159` finds an existing block by marker and refreshes in place) — without it, repeated compactions stack blocks without bound. Once Phase 4.1 lands, consider whether this second path earns its keep at all: it reaches only `ChatAgent`, and there it is tail-windowed out at 50 messages (`chat_message.py:59`, `DEFAULT_MAX_CHAT_CONTEXT_MESSAGES = 50`).

---

## Phase 5 — Enforcement that does not depend on retention

> The only design robust to compaction **by construction** is one that does not read the context at all. Prompt delivery (Phase 4) raises compliance; mechanical gates make it moot for the subset that can be compiled.

### 5.1 What is already covered — do not double-gate

`ExecApprovalPolicy._DEFAULT_RULES` (`approval_policy.py:54-116`) is a frozen 23-rule tuple evaluated at the tool layer (`bash_tool.py:389`, `powershell_tool.py:187`, `python_tool.py:166`): `remove-item`/`rm`/`del`/`stop-process`/`kill` are `ALWAYS_ASK`; `format X:`/`Format-Volume` are `DENY`; any command with a separator plus a destructive keyword is force-bumped. **None of this lives in the context**, so for shell-side Action constraints a dropped SC changes nothing. The original audit overstated this risk; the plan should not re-solve it.

### 5.2 Compile the enforceable subset — Strategy, not a Specification framework

```python
# weebot/application/services/constraint_compilers.py
Compiler = Callable[[SessionConstraint], Optional[EnforcementRule]]
_COMPILERS: dict[ConstraintKind, Compiler] = {...}
```

A dict of small functions keyed by `ConstraintKind`, consistent with the Strategy usage in Phase 2. **Explicitly rejected:** a full Specification/composite-predicate framework — one implementation per kind, no composition requirement, no runtime rule algebra. That is an unrequested abstraction (`~/.claude/rules/common/coding-style.md` YAGNI).

Only `TIGHTEN`-direction constraints compile. `LOOSEN` constraints compile to nothing, by design (D7).

### 5.3 Targets, in order of cost

| Constraint shape | Mechanism | Work required |
|---|---|---|
| *"don't send mail without showing me"* | `EgressGuard` | **Done** (Phase −1) |
| *"don't read anything in `confidential/`"* | `FSPermissionChecker` | **Large.** Zero callers today. Needs (a) a rules source/loader, (b) a DI binding, (c) call sites in `weebot/tools/file_editor.py` and/or `_tool_executor.py`, (d) relaxing `FilesystemPermission.__post_init__`'s `path.startswith("/")` invariant (`fs_permission.py:37`), which rejects `E:\…` and `confidential/` outright. Its `"interrupt"` mode also has no wired HITL consumer |
| *"never put my phone number in a file"* | `EgressGuard._scan_sensitive` extension | Medium. `credential_sanitizer.py` / `secret_redaction.py` target secrets, not user-designated PII |
| Everything else | Phase 4 prompt delivery only | — |

Sequence this by cost: mail is done, PII scanning is a pattern-list extension, `FSPermissionChecker` is a subproject and should be its own plan.

### 5.4 Fix the existing step gate

`executing.py:174-222` has three defects the audit measured:

1. **Pinned to the first prompt.** The expression `original_task or last_prompt or prompt` always resolves to `original_task`, seeded once at `plan_act_flow.py:571-578` and never cleared. There is no alias bug (`SessionContext.get()` resolves both spellings) — it is a *write-side* gap: `original_task` is set in exactly one place, only when `prompt.strip()` is non-empty, so gateway/chat sessions never populate it. Replace the source with the registry.
2. **False positives.** `check_step` matches stopword substrings and fires on 3 of 6 benign steps in the measured run.
3. **Inversion.** For SC#1 (*"don't ask me to confirm"*) the gate **pauses to ask for confirmation** — violating the constraint it is enforcing. D7's direction field fixes this at the root: a `LOOSEN` constraint must never reach the gate.

Mirror the inbound-mail gate's shape (`executing.py:148-172`): local import → best-effort journal write → `set_status(WAITING)` → `yield WaitForUserEvent` → `return`, **and clear a one-shot flag before pausing**. The constraint gate currently clears nothing, so on resume `FlowRouter` (`flow_router.py:158-166`) flips `WAITING → RUNNING`, returns `ExecutingState()`, and `execute()` re-runs from the top against the same step — the gate re-fires unless the user's text happened to change. Also **await** the `MisalignmentEntry` write; today it is an unawaited `ensure_future` (`:203-209`) guarded only for `ImportError`.

---

## Phase 6 — Offline COMPINT regression harness

### 6.1 Measure compliance, not retention

The paper's own numbers: `K_ub` ≈ 98–99.7% while `K_comp` ≈ 31.8–58.5%, effective retention 12.8–27.6% (Tables 9, 10). A suite asserting only *"the SC string appears in the compacted context"* ports the paper's **judge** metric and not its failure. Use the four-group design (§4.4, Eq. 9):

| Group | Context supplied | What it establishes |
|---|---|---|
| `K_lctx` | full history, **no** SC | the model's prior tendency toward the compliant option |
| `K_lctx_sc` | full history **with** SC | uncompacted ceiling |
| `K_comp` | compacted history, SC injected pre-compaction | the real-world condition |
| `K_ub` | compacted history ⊕ SC appended last | the achievable ceiling — **this is the regression target, not 100%** |

`EffectRetention = (c_comp − c_lctx) / (c_ub − c_lctx)`.

### 6.2 Offline by construction

`tests/unit/` is hermetic: `tests/unit/conftest.py:39 _isolate_weebot_settings` nulls the settings `env_file`, and `tests/conftest.py:62 clean_env` strips every provider key. `asyncio_mode = "auto"`, so no `@pytest.mark.asyncio`. **Keep this suite out of `tests/integration/`** — that conftest loads the real `.env`.

There is no shared LLM fake; the convention is a per-file hand-rolled stub. Use a **scripted policy stub**: a fake `LLMPort` that answers the MCQ probe compliantly iff the constraint text is present in the messages it received. That makes the suite a deterministic test of *plumbing* — did the constraint reach the model — which is exactly what Phases 3–4 are responsible for, and it removes model variance from a regression gate.

### 6.3 Golden data

Golden inputs live in `weebot/config/harness/`, not `tests/fixtures/` (which is nearly empty and has no convention). Add `weebot/config/harness/side_constraints.yaml` with the paper's 15 SC/probe pairs plus:

- a **revocation probe** — the paper's set contains none, and D8 makes it the highest-value new case;
- a **direction probe** — SC#1 must not trigger a confirmation pause;
- **stratification by `ConstraintKind`**, since Process SCs are worst-retained by compactors (2–16%) while Action SCs are the *extractor's* weakest category (88.2% vs 97.1% for Preference). An averaged 15-pair score hides exactly the categories that carry the safety weight.

Follow `tests/unit/test_harness_baseline.py`: module-level builder helpers, `Test*` classes, plus a "the committed golden file must actually parse" test.

### 6.4 CI

`.github/workflows/architecture.yml:76` already runs `pytest tests/unit/` with `--cov-fail-under=52`, so a suite placed there is armed on arrival — no workflow edit needed.

> Adjacent finding worth acting on: `weebot/config/harness/baseline.json`, which the whole `baseline.py` regression-gate design depends on, **does not exist**, and `harness baseline check` is not in CI. That gate is built but never armed.

---

## Phase 7 — Wire the dead neighbours

Do this **before** shipping Phase 3, or the registry becomes the fourth unwired constraint mechanism.

### 7.1 `BehavioralLearner`

Zero construction sites in `weebot/`. No DI binding. Not passed by any of the six flow-construction call sites. Therefore `plan_act_flow.py:170`'s `self._behavioral_learner` is always `None` and all three consumers are dead: `executing.py:228`, `reviewing.py:193-203`, and the `# Behavioral Rules` prompt block at `_prompt_builder.py:125-131`.

Fix: `Container.register("behavioral_learner", …)`, thread through `TaskRunner.create_plan_act_factory` (`task_runner.py:392-409`) — which today receives no container and no optional services at all — and pass the existing legacy kwarg (`plan_act_flow.py:106`).

Then add scope: `BehavioralLearner._determine_scope` (`:264-278`) returns only `"global" / "per_tool" / "per_skill"`. A correction issued in one session becomes a **global rule with no expiry**. Add `"session"` and filter `get_rules_for_prompt()` accordingly. This is D2's boundary made real.

### 7.2 `CorrectionTracker`

Never constructed, never registered, and **not even in `PlanActFlow.__init__`'s legacy kwarg list** — reachable only via a real `PlanActFlowConfig`. So `reviewing.py:133` and `:172-190` are dead and `_correction_repo.py` backs a table nothing writes to. Phase 3.2's `create_flow` migration fixes both at once.

### 7.3 Session→durable promotion

Once both tiers are live: a session constraint that recurs across N sessions is a durable preference. Route it through `BehavioralLearner`'s existing `behavioral_rules` table rather than growing a parallel store. Gate behind its own flag; this is the speculative end of the plan and should ship last, if at all.

---

## Phase 8 — Audit cleanups (independent, small)

| # | Defect | Location | Fix |
|---|---|---|---|
| 8.1 | `deque(maxlen=15)` vs a 12-tool-call budget — the anchoring context message (goal, plan summary, step description) can be evicted mid-step, and orphaned `tool` messages can reach the provider with no sanitization | `_base.py:202`, `:511-516` | Derive `max_context_turns` from the tool budget, or sanitize orphans before dispatch |
| 8.2 | `summary = await self._compressor.compress(middle)` returns a **list of message dicts** but is inserted as `{"role":"system","content": summary}` | `_context_compressor.py:104-112` vs `conversation_compressor.py:63-106` | Join or take the summary message |
| 8.3 | `.env.example:123` ships `WEEBOT_EGRESS_ENFORCE=false`, contradicting the code default of `"true"` (`egress_guard.py:45`). Anyone copying the template silently disables egress gating for bash, browser, telegram **and** the new mail branch | `.env.example` | Flip to `true` (behaviour change for new installs — decide explicitly) |
| 8.4 | `ADR-006` collision: `CLAUDE.md` cites `docs/adr/006-atomic-mail-inbound-trust-boundary.md`; the real ADR-006 is `006-self-harness-per-model-evaluator.md` | `CLAUDE.md`, `docs/adr/007`'s Related block | Renumber or repoint. Next free number is **012** |
| 8.5 | `StructuredExecutorAgent.execute_step_structured` calls `self._execute_tool_call(tc)`, which exists nowhere in the tree — `AttributeError` swallowed by a bare `except` and surfaced as a generic `ErrorEvent`. The class has no callers | `structured_executor.py:165` | Delete the class, or fix and wire it. Deleting is the smaller diff |
| 8.6 | `register_default_handlers` llm-absent branch constructs `ExecuteStepHandler(state_repo)` with two positional-required params missing | `handlers/__init__.py:134-136` | Fold into Phase 0.3 |
| 8.7 | `_untrusted_context_active` is a one-way latch never cleared for the executor's lifetime | `_tool_executor.py:71`, `:240-241` | Correct-by-default (fails closed); document it rather than "fixing" it |
| 8.8 | `MemoryArchivist` / `SessionSummarizer` have zero constructors; `TaskRunner._archivist` is always `None`. Its task-continuity summarization prompt is therefore **not** a live SC leak | `memory_archivist.py`, `task_runner.py:43`, `:192` | Wire it or delete it. Until then, do **not** spend edits on its prompt |

---

## ADR-012

This work changes a trust boundary and adds a persistent store, so it warrants an ADR. Copy the shape of `docs/adr/007-x-mcp-inbound-trust-and-write-gating.md` — the closest precedent for enforcement/trust work, and the only one with a `Related` block listing implementation file paths.

**Title:** *ADR-012: Session-Scoped Side Constraints and the Executor Delivery Seam*
**Decision points to record:** D1 (why not `Session.set_fact`), D2 (session vs durable tiering), D3 (user-turn-only extraction as a trust boundary), D5 (delivery position), D7 (direction-aware enforcement), D8 (revocation), D12 (no new port).

---

## Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Store the registry in `Session.set_fact` | Provenance-blind FIFO cap of 100 shared with unbounded per-step executor facts; the registry key would be the **first** evicted. Also `FactSource.USER` has zero writers today |
| Hook accumulation at `dispatch_session_input._with_prompt` | 2 of 4 verbs, ~10 bypassing paths (CLI, resume, steering, chat, webhooks, six gateways) |
| Add `"outbound_mail"` to `TOOL_CATEGORIES` | Pure no-op — nothing on the mail path calls `evaluate()`, and `evaluate()` takes a command *string* with no notion of tool args. `"finance"` and `"payment"` are already unreachable dead constants |
| Thread 18 executor params through `ExecuteStepCommand` | Turns a frozen intent DTO into a service locator; `extra="forbid"` and `frozen=True` exist to prevent exactly this |
| A new `ConstraintRegistryPort` | One implementation, beside an already-dead `behavioral_learner_port.py` with one implementation. Wire what exists first (D12) |
| A Specification / composite-predicate framework for enforcement | One compiler per `ConstraintKind`, no composition requirement, no runtime rule algebra. Unrequested abstraction |
| Lower `_maybe_compress`'s 0.75 threshold to chase the paper's short-context retention curve | Buys retention by spending the context budget compaction exists to save. With delivery fixed, the curve is irrelevant. (The path is also near-unreachable: a 15-message buffer would need ~384 K characters to trip 96 K estimated tokens) |
| Re-render the constraint block on every tool result | Paper Appendix E: repetition saturates below 40% and is dominated by one well-placed statement at 49%. Pure token cost (D15) |
| An alembic revision for `session_constraints` | All four siblings of `correction_records` are inline-only; alembic would make this table the odd one out and require the verify-and-raise pattern |
| Editing `MemoryArchivist`'s summarization prompt | Dead code — zero constructors (8.8) |

---

## Honest limits of the evidence

Written into the plan so nobody over-trusts the source:

- **`17%` is not a general retention rate.** Every cell is measured at **top** injection, the worst position; the same compactors reach 38–100% at bottom injection. It is an unweighted mean over 8 hand-picked compactor configurations including two that are 0% by construction. Open-model-only average is **6.1%**; instance-weighted, 11.3%.
- **`K_ub` is an oracle-adjacency ceiling.** The constraint is placed immediately before the probe — the exact variable the paper elsewhere identifies as the dominant driver. It bounds what Phase 4 can achieve; it is not evidence that a registry works at realistic distance.
- **"Compaction is worse than no compaction" holds for one prober.** With gpt-oss-120b, yes; 2 of the 3 other downstream models tested **invert** it.
- **The extractor's 93.7% is recall on a planted string**, judged by the same LLM judge, on a document whose only content is constraints. The paper reports **no precision / false-positive rate** and never measures compliance for the extractor. On a 257-user-turn session, even a 1% FP rate injects ~2.6 spurious permanent constraints. This is the strongest argument for D8 (revocation) and for the evidence-span field.
- **"Architectural separation, not better prompts" is the paper's thesis, not a controlled result.** The extractor changes four things at once (model, prompt, per-turn granularity, post-summary placement) and none is ablated. An SC-targeted *prompt* is the largest prompt-level gain reported (+23.5 / +34.3 pp) — which is why Phase −1 shipped it first, for two lines.

---

## Sequencing

```
Phase 0 (seam)  ──┬── Phase 4 (delivery)   ── Phase 6 (harness, gates 3-5)
                  ├── Phase 5 (enforcement)
                  └── Phase 7 (wire dead code)
Phase 1 (domain) ── Phase 2 (extraction) ── Phase 3 (accumulation) ──┘
Phase 8 — any time, each item independent
```

**Minimum shippable slice with real user-visible effect:** Phase 0 + Phase 8.3. Phase 0 alone revives per-step context scoping, skill retrieval, harness blocks, personality, user profile, and middleware on the live path — none of which is about constraints at all.
