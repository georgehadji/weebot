# Sub-Agent Implementation — Bug Fix Plan

> Based on code review of commit `0da9c6c`. All fixes respect Clean Architecture.

---

## 🔴 Critical

### Bug 1: Unregistered Mediator breaks ALL sub-agents

**File:** `weebot/infrastructure/adapters/sub_agent_factory.py:117-127`

**Evidence:**
```python
def _build_flow(self, session, spec):
    mediator = Mediator()  # ← NO HANDLERS REGISTERED
    return PlanActFlow(..., mediator=mediator, ...)
```

A bare `Mediator()` has zero handlers. When `PlanningState` calls `mediator.send(CreatePlanCommand(...))`, it fails with `HandlerNotRegisteredError`. Since Risk 3 made the mediator mandatory (no fallback), EVERY sub-agent immediately errors out.

**Architecture impact:** The DI container has `build_mediator()` which creates a properly configured Mediator with pipeline behaviors + default handlers. The factory should use that rather than constructing a naked one.

**Fix:** Inject a pre-configured Mediator from the DI container, or build one correctly:

```python
# sub_agent_factory.py — modify _build_flow

def _build_flow(self, session: Session, spec: SubAgentSpec):
    from weebot.application.flows.plan_act_flow import PlanActFlow
    from weebot.application.di import Container

    container = Container()
    container.configure_defaults()
    mediator = container.build_mediator()

    return PlanActFlow(
        llm=self._llm,
        tools=self._tools,
        session=session,
        event_bus=None,
        model=spec.model or _TIER_MODEL[spec.tier],
        mediator=mediator,
        state_repo=container._maybe_get(StateRepositoryPort),  # persist sub-agent sessions
        skill_prompt=None,
        max_steps=spec.max_tool_calls,
    )
```

**Architecture check:** `SubAgentFactory` (Infrastructure) → `Container` (Application DI) → `Mediator` (Application CQRS). Infrastructure → Application is **allowed** in Clean Architecture. The DI container is a composition root, not a layer boundary violation.

---

### Bug 2: SynthesizerAgent receives model name as role

**File:** `weebot/application/agents/hyper_agent.py:138-140`

**Evidence:**
```python
summaries = [
    {"role": r.model_used, "summary": r.summary}  # ← model_used, not role
    for r in results if r.is_success
]
```

`synthesizer_agent.py:92` uses `role` for clustering:
```python
transcript_parts.append(f"## {role}\n{summary}")
```

When `role` is `"minimax/minimax-m3"` instead of `"researcher"`, the synthesizer clusters by model name — meaningless.

**Fix:** Use the actual agent role, not the model name:

```python
summaries = [
    {"role": r.agent_id, "summary": r.summary, "model_used": r.model_used}
    for r in results if r.is_success
]
```

But `agent_id` is the session ID like `"sub-abc123-researcher"`. Better: add `role` to `SubAgentResult`:

```python
# sub_agent.py — add to SubAgentResult
role: str = Field(default="")
```

Then in `sub_agent_factory.py:spawn()`:
```python
return SubAgentResult(
    ...
    role=spec.role.value,
)
```

Then in `hyper_agent.py:_synthesize()`:
```python
summaries = [
    {"role": r.role, "summary": r.summary}
    for r in results if r.is_success
]
```

**Architecture check:** Adding a field to a domain model (`SubAgentResult`) is a domain-layer change. Zero imports from outer layers. ✅

---

## 🟡 High

### Bug 3: Timeout never enforced on sub-agent execution

**File:** `weebot/infrastructure/adapters/sub_agent_factory.py:82-92`

**Evidence:** The `except asyncio.TimeoutError:` block exists but `flow.run(prompt)` is NEVER wrapped in `asyncio.wait_for()`. A hanging sub-agent blocks forever.

**Fix:**
```python
async for event in asyncio.wait_for(
    flow.run(prompt),
    timeout=spec.timeout_seconds,
):
    ...
```

---

### Bug 4: Token counting uses private attribute

**File:** `weebot/infrastructure/adapters/sub_agent_factory.py:89-91`

**Evidence:**
```python
if hasattr(flow, "_executor") and hasattr(flow._executor, "token_usage"):
    tu = flow._executor.token_usage
```

This accesses `PlanActFlow._executor` — a private attribute that can be renamed at any time without notice.

**Fix:** Add a public `token_usage` property to `PlanActFlow`:

```python
# plan_act_flow.py — add property
@property
def token_usage(self) -> dict[str, int]:
    return self._executor.token_usage if self._executor else {}
```

Then use it:
```python
if hasattr(flow, "token_usage"):
    tu = flow.token_usage
```

**Architecture check:** Adding a public property to an existing Application-layer class. No new imports. ✅

---

## 🟠 Medium

### Bug 5: `hyper.py list-costs` creates unconfigured Container

**File:** `cli/commands/hyper.py:102`

**Evidence:**
```python
state_repo = Container().get(StateRepositoryPort)  # ← configure_defaults() never called
```

**Fix:**
```python
container = Container()
container.configure_defaults()
state_repo = container.get(StateRepositoryPort)
```

---

### Bug 6: Voted strategy uses "longest summary" — not actual voting

**File:** `weebot/infrastructure/adapters/sub_agent_factory.py:112-115`

**Evidence:**
```python
# Return the longest summary (most detailed)
return max(successes, key=lambda r: len(r.summary))
```

This is a heuristic placeholder. Not a bug per se, but the method name `spawn_voted` is misleading.

**Fix:** Rename to `spawn_multi_model` and document the heuristic:

```python
async def spawn_multi_model(
    self, spec: SubAgentSpec, models: list[str] | None = None
) -> SubAgentResult:
    """Run the same spec on multiple models and return the best result.

    Currently uses longest-summary heuristic. Future: majority voting
    when eval data confirms improvement over single-model.
    """
```

Also rename in the port:

```python
# sub_agent_factory_port.py
@abstractmethod
async def spawn_multi_model(
    self, spec: SubAgentSpec, models: list[str] | None = None
) -> SubAgentResult:
    """Run same spec on multiple models, return best result."""
```

And update the call site:

```python
# hyper_agent.py
elif strategy == DispatchStrategy.VOTED and len(specs) == 1:
    results = [await self._factory.spawn_multi_model(specs[0])]
```

**Architecture check:** Port + adapter rename. Both files changed, signature stays compatible. ✅

---

### Bug 7: `hyper.py` imports unused `AgentEvent`

**File:** `cli/commands/hyper.py:21`

**Fix:** Remove line 21: `from weebot.domain.models.event import AgentEvent`

### Bug 8: `sub_agent_factory.py` imports unused `Any`

**File:** `weebot/infrastructure/adapters/sub_agent_factory.py:13`

**Fix:** Remove `Any` from the typing import.

---

## 🔵 Low

### Bug 9: `hyper.py` uses `event.error` without type guard

**File:** `cli/commands/hyper.py:82`

**Evidence:**
```python
console.print(f"[red]Error: {event.error}[/red]")
```

If the event has a differently-named error field, this produces `Error: None`.

**Fix:**
```python
error_msg = getattr(event, "error", "") or str(event)
console.print(f"[red]Error: {error_msg}[/red]")
```

---

### Bug 10: `hyper.py list-costs` imports Container but doesn't use it at module level

**File:** `cli/commands/hyper.py:12`

Actually `Container` is used inside `hyper_list_costs`'s `_run()` — but the function currently accesses it as `Container()` without importing it. Wait, it's imported at the top. Let me re-read.

Actually the import IS there at line 12 — `from weebot.application.di import Container`. This is fine.

---

### Bug 11: Sub-agent `TokenUsage` property missing

**File:** `weebot/application/flows/plan_act_flow.py`

Related to Bug 4 — the public property doesn't exist yet. Let me add it.

---

## Implementation Order

| # | Bug | Files | Effort |
|---|-----|-------|--------|
| 1 | Mediator has no handlers | `sub_agent_factory.py` | 10 min |
| 2 | Synthesizer role = model name | `sub_agent.py`, `sub_agent_factory.py`, `hyper_agent.py` | 10 min |
| 3 | Timeout never enforced | `sub_agent_factory.py` | 5 min |
| 4 | Private `_executor` access | `plan_act_flow.py`, `sub_agent_factory.py` | 10 min |
| 5 | Unconfigured Container | `hyper.py` | 2 min |
| 6 | spawn_voted → spawn_multi_model | `sub_agent_factory_port.py`, `sub_agent_factory.py`, `hyper_agent.py` | 10 min |
| 7 | Unused import AgentEvent | `hyper.py` | 1 min |
| 8 | Unused import Any | `sub_agent_factory.py` | 1 min |
| 9 | event.error null guard | `hyper.py` | 2 min |

**Total: ~50 minutes.** 7 files changed. Zero layer violations.
