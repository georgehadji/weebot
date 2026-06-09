# Tool Handling Enhancements — Implementation Plan

**Status:** Draft  
**Target branch:** `feature/tool-enhancements`  
**Architecture baseline:** Clean Hexagonal (Interfaces → Infrastructure → Application → Domain)  
**Fitness gate:** `pytest tests/unit/test_architecture_fitness.py` must stay green after every phase

---

## 1. Motivation

Six confirmed gaps in the current tool handling pipeline:

| # | Gap | Impact |
|---|-----|--------|
| 1 | Dead `openrouter_tools.py` with broken `WebSearchTool` | Confusion, dead code |
| 2 | `_max_retries` mechanism is never activated by callers | Transient failures never retry |
| 3 | Tool calls within one LLM response execute sequentially | Latency scales with call count |
| 4 | Global 60s timeout for all tools regardless of type | Bash hits ceiling; search wastes 45s |
| 5 | Hard prefix-cut truncation loses tail of shell output | LLM misses errors at end of output |
| 6 | `TrajectoryMonitor` resets on every step | Cross-step degenerate patterns invisible |

A seventh improvement (tool result cache) is scoped as Phase 5 — higher complexity, deferred until Phases 1–4 are stable.

---

## 2. Architecture Constraints

All changes must satisfy the rules enforced by `tests/unit/test_architecture_fitness.py`:

- **Domain pure:** `weebot/domain/` must not import from any outer layer
- **Application no module-level infra:** `weebot/application/` may only import `weebot.infrastructure` inside functions or `TYPE_CHECKING` blocks
- **Tools no sqlite3:** `weebot/tools/` must not import `sqlite3`, `aiosqlite`, or `sqlalchemy` directly
- **Tools no `WeebotSettings`:** Tools receive config via `ToolConfig` constructor injection
- **No flat files at `weebot/` root:** New modules must live inside the correct layer package
- **Ports need adapters:** Any new port added to `weebot/application/ports/` must have a corresponding adapter and be registered in `di.py`
- **No circular imports:** Verify with `test_no_circular_imports`

Layer placement for new files:

| What | Where |
|------|-------|
| New cache service | `weebot/application/services/` |
| Tool contract changes | `weebot/tools/base.py` |
| Executor changes | `weebot/application/agents/executor.py` |
| ToolCollection changes | `weebot/application/models/tool_collection.py` |
| New port (if needed) | `weebot/application/ports/` + adapter |

---

## 3. Phase Overview

```
Phase 1  Dead code + retry fix          (cleanup, no risk)
Phase 2  Parallel tool execution        (high impact, medium complexity)
Phase 3  Per-tool timeout + health      (contained, additive)
Phase 4  Context-aware truncation       (contained, additive)
Phase 5  Tool result cache              (moderate complexity, deferred)
Phase 6  Cross-step TrajectoryMonitor   (low risk, real gap)
```

Phases 3, 4, and 6 are independent of each other and can run in parallel after Phase 2 merges.  
Phase 5 depends on Phase 3 (needs `default_timeout_seconds` to set per-tool TTL).

---

## 4. Phase 1 — Dead Code & Retry Activation

### 4.1 Goal
Remove `openrouter_tools.py` and activate the dormant `_max_retries` mechanism in `ToolCollection`.

### 4.2 Files

| Action | File | Change |
|--------|------|--------|
| Delete | `weebot/core/openrouter_tools.py` | Entire file removed |
| Edit | `weebot/application/models/tool_collection.py` | Change retry default |

### 4.3 Implementation — `tool_collection.py`

`_max_retries` is currently populated by `kwargs.pop("_max_retries", 0)`, meaning only callers who explicitly pass it get retries. No tool or executor currently passes it.

**Change:** Promote the default to a class-level constant and apply it for all executions:

```python
# In ToolCollection.__init__
DEFAULT_MAX_RETRIES: int = 2
RETRYABLE_EXCEPTIONS = (OSError, TimeoutError, ConnectionError)

# In ToolCollection.execute()
# Replace: max_retries = kwargs.pop("_max_retries", 0)
# With:
max_retries = kwargs.pop("_max_retries", self.DEFAULT_MAX_RETRIES)
```

**Change:** Replace linear backoff with capped exponential:

```python
# Replace: await asyncio.sleep(0.1 * retry_count)
# With:
await asyncio.sleep(min(0.1 * (2 ** retry_count), 5.0))
```

**Change:** Only retry on retryable exception types — pass-through on non-retryable errors (e.g., `ValueError` from bad args) to avoid masking bugs:

```python
except Exception as exc:
    if not isinstance(exc, self.RETRYABLE_EXCEPTIONS):
        # Non-retryable: surface immediately
        return ToolResult.error_result(error=str(exc), ...)
    # ... retry logic
```

### 4.4 Tests

- `tests/unit/test_tool_collection_retry.py`
  - `test_retries_on_os_error` — verify exponential backoff fires up to 2 times
  - `test_no_retry_on_value_error` — verify non-retryable exceptions surface on first attempt
  - `test_retry_succeeds_on_second_attempt` — mock tool raises once, succeeds second time

### 4.5 Fitness Check

`test_no_flat_files_at_root` — verify `openrouter_tools.py` removal doesn't leave an orphaned reference.  
`grep -r "openrouter_tools"` across the codebase before deleting to confirm no imports exist.

### 4.6 Risk: Low

`openrouter_tools.py` has zero importers (confirmed by grep). Retry activation only affects error paths.

---

## 5. Phase 2 — Parallel Tool Execution

### 5.1 Goal
When the LLM returns multiple tool calls in a single response, execute them concurrently. Preserve declared order in `_conversation_buffer` regardless of completion order.

### 5.2 Files

| Action | File |
|--------|------|
| Edit | `weebot/application/agents/executor.py` |
| New | `tests/unit/test_parallel_tool_execution.py` |

### 5.3 Design

**Key invariant:** The OpenAI tool-call protocol requires that tool result messages appear in the conversation in the *same order* as the `tool_calls` array in the preceding assistant message. Reordering causes model confusion and API errors. `asyncio.gather` completes in arbitrary order, so results must be re-paired to their original index before appending.

**Dependency detection:** The current architecture does not declare tool dependencies, and the LLM does not tag calls as independent. Assume independence by default — the LLM uses sequential calls when the second genuinely needs the first's output (it will include the prior result in its reasoning text and issue a new call in the next turn, not batch them). Parallel execution within a single response batch is always safe under this model.

**Error isolation:** If one tool in the batch errors, append its error result in the correct slot and continue. Do not abort the whole batch.

### 5.4 Implementation

Extract the current sequential loop in `execute_step()` into a private method and replace with `gather`:

```python
# weebot/application/agents/executor.py

async def _execute_tool_batch(
    self,
    tool_calls: list[dict],
) -> list[ToolResult]:
    """Execute tool calls concurrently; return results in declared order."""
    tasks = [
        asyncio.ensure_future(self._execute_tool_call(tc))
        for tc in tool_calls
    ]
    # gather(return_exceptions=True) so one failure doesn't cancel siblings
    raw = await asyncio.gather(*tasks, return_exceptions=True)
    results: list[ToolResult] = []
    for i, r in enumerate(raw):
        if isinstance(r, Exception):
            results.append(ToolResult.error_result(
                error=f"Tool '{tool_calls[i]['function']['name']}' raised: {r}",
                tool_name=tool_calls[i]["function"]["name"],
            ))
        else:
            results.append(r)
    return results
```

Replace the `for tc in response.tool_calls` loop in `execute_step()` with:

```python
results = await self._execute_tool_batch(response.tool_calls)

for tc, result in zip(response.tool_calls, results):
    tool_name = tc["function"]["name"]
    # ... all existing per-result logic (events, trajectory monitor,
    #     policy-error-loop detection, facts, conversation_buffer append)
    #     unchanged — just iterating over pre-computed results
```

**Conversation buffer append order** is preserved because `zip(response.tool_calls, results)` iterates in declared order.

**Trajectory monitor and policy-error-loop** still execute per result after gather, exactly as before. No changes to those systems.

### 5.5 Tool-Level Concurrency Cap

Some tools (browser, computer_use, screen) should not run more than one instance at a time due to display/resource contention. Introduce an optional `max_concurrent: int = 0` (0 = unlimited) attribute on `BaseTool`. `_execute_tool_batch` acquires a per-tool semaphore when `max_concurrent > 0`:

```python
# In ToolCollection (or executor) — lazy semaphore registry
_tool_semaphores: dict[str, asyncio.Semaphore] = {}

def _get_semaphore(self, tool_name: str, limit: int) -> asyncio.Semaphore:
    if tool_name not in self._tool_semaphores:
        self._tool_semaphores[tool_name] = asyncio.Semaphore(limit)
    return self._tool_semaphores[tool_name]
```

Tools to set `max_concurrent = 1`: `AdvancedBrowserTool`, `ScreenTool`, `ComputerUseTool`, `VoiceInputTool`, `VoiceOutputTool`.

### 5.6 Tests

- `tests/unit/test_parallel_tool_execution.py`
  - `test_results_in_declared_order` — two tools complete in reverse order; buffer entries match declared order
  - `test_one_failure_does_not_abort_batch` — tool 1 raises; tool 2 succeeds; both results present
  - `test_concurrent_execution_is_faster` — mock tools sleep 100ms each; batch of 3 completes in < 200ms total
  - `test_single_tool_call_unchanged` — single-tool response still works correctly
  - `test_semaphore_limits_concurrent_browser` — browser tool capped at 1 concurrent; second waits for first

### 5.7 Fitness Check

No new imports at module level from infrastructure. `executor.py` already imports `asyncio` — no new dependencies.  
`test_no_blocking_calls_in_async` — `_execute_tool_batch` must not contain `time.sleep` or `subprocess.run`.

### 5.8 Risk: Medium

**Primary failure mode:** Conversation buffer ordering broken if `zip` is used with mismatched lengths. Guard with `assert len(results) == len(response.tool_calls)` before the zip.  
**Secondary failure mode:** A semaphore created in one event loop iteration is accessed in another if the executor is reused across asyncio loops. Lazy creation inside the running loop is safe; document the constraint.

---

## 6. Phase 3 — Per-Tool Timeout & Health Checks

### 6.1 Goal
Replace the global 60s timeout with per-tool defaults. Exclude tools whose runtime dependencies are unavailable from the LLM's tool menu.

### 6.2 Files

| Action | File |
|--------|------|
| Edit | `weebot/tools/base.py` |
| Edit | `weebot/application/agents/executor.py` |
| Edit | `weebot/application/models/tool_collection.py` |
| Edit (8 tool files) | See §6.4 |
| New | `tests/unit/test_tool_health.py` |

### 6.3 `BaseTool` Changes

Add two optional attributes with no-op defaults so existing tools require zero changes:

```python
class BaseTool(ABC, BaseModel):
    name: str
    description: str
    parameters: dict
    default_timeout_seconds: int = 60       # NEW
    max_concurrent: int = 0                 # NEW (0 = unlimited, from Phase 2)

    async def health_check(self) -> bool:   # NEW
        """Return False if this tool's runtime dependencies are unavailable."""
        return True

    # ... existing to_param(), execute()
```

`health_check()` is **non-abstract** (default `True`) so existing tools are unaffected. Tools with hard dependencies override it.

### 6.4 Per-Tool Timeout Assignments

| Tool file | `default_timeout_seconds` | Rationale |
|-----------|--------------------------|-----------|
| `bash_tool.py` | 300 | Long-running shell commands |
| `powershell_tool.py` | 300 | Same as bash |
| `advanced_browser.py` | 120 | Page load + JS render |
| `browser_tool.py` | 60 | Simple fetches |
| `screen_tool.py` | 30 | Screenshot is fast |
| `computer_use.py` | 30 | Individual click/type |
| `web_search.py` | 25 | External API; fail fast |
| `image_gen_tool.py` | 90 | Model inference time |
| `voice_input_tool.py` | 20 | Microphone capture |
| `voice_output_tool.py` | 30 | TTS synthesis |

### 6.5 Health Check Implementations

Override `health_check()` on tools with external runtime dependencies:

```python
# advanced_browser.py
async def health_check(self) -> bool:
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            _ = p.chromium
        return True
    except Exception:
        return False

# computer_use.py
async def health_check(self) -> bool:
    try:
        import pyautogui  # or whatever the dependency is
        return True
    except ImportError:
        return False

# voice_input_tool.py, voice_output_tool.py
async def health_check(self) -> bool:
    try:
        import sounddevice  # or pyaudio
        return True
    except ImportError:
        return False
```

### 6.6 `ToolCollection` — Health Filtering

Add a `check_health()` coroutine and cache results per session:

```python
class ToolCollection:
    def __init__(self, *tools, canonicalizer=None, contract_loader=None):
        # ... existing
        self._healthy: set[str] | None = None  # None = not yet checked

    async def check_health(self) -> dict[str, bool]:
        """Run health checks for all tools; cache results for this session."""
        results = await asyncio.gather(
            *[t.health_check() for t in self._tools.values()],
            return_exceptions=True,
        )
        self._healthy = {
            name: (r is True)
            for name, r in zip(self._tools.keys(), results)
        }
        return dict(self._healthy)

    def to_params(self) -> list[dict]:
        params = []
        for tool in self._tools.values():
            # Skip tools that failed health check (if check has run)
            if self._healthy is not None and not self._healthy.get(tool.name, True):
                continue
            # ... existing contract_loader logic
            params.append(spec)
        return params
```

Call `await tool_collection.check_health()` once during `PlanActFlow` initialization (inside `__init__` or the first `run()` call), not on every step.

### 6.7 `executor.py` — Read Per-Tool Timeout

```python
async def execute_tool(self, name, arguments=None):
    # ... existing arg parsing
    tool = self._tools._tools.get(name)  # access via ToolCollection
    timeout = getattr(tool, "default_timeout_seconds", 60)
    if "timeout" in args:
        try:
            timeout = min(float(args["timeout"]) + 5.0, 305.0)
        except (ValueError, TypeError):
            pass
    # ... rest unchanged
```

To avoid exposing `_tools._tools` (private dict), add a `get_tool(name)` accessor to `ToolCollection`.

### 6.8 Tests

- `tests/unit/test_tool_health.py`
  - `test_healthy_tool_appears_in_params` — tool with `health_check -> True` is included
  - `test_unhealthy_tool_excluded_from_params` — tool with `health_check -> False` is excluded
  - `test_health_check_not_run_uses_all_tools` — before `check_health()`, all tools appear
  - `test_per_tool_timeout_read_by_executor` — executor reads tool's `default_timeout_seconds`
  - `test_caller_timeout_overrides_default` — passing `timeout=10` in args still overrides

### 6.9 Fitness Check

`test_ports_have_adapters` — `health_check()` on `BaseTool` is not a port (it's a method on a concrete base class), so no new port/adapter entry needed.  
`test_domain_has_no_outer_imports` — `BaseTool` lives in `weebot/tools/`, not domain; no violation.

### 6.10 Risk: Low

Additive only. Default `health_check() -> True` means no existing tool changes behavior unless explicitly overridden. Health filtering in `to_params()` is gated on `self._healthy is not None`, so it has no effect until `check_health()` is explicitly called.

---

## 7. Phase 4 — Context-Aware Output Truncation

### 7.1 Goal
Replace the hard prefix-cut in `ToolCollection.execute()` with truncation that preserves the semantically useful part of each tool's output.

### 7.2 Files

| Action | File |
|--------|------|
| Edit | `weebot/tools/base.py` |
| Edit | `weebot/application/models/tool_collection.py` |
| Edit (target tools) | `bash_tool.py`, `powershell_tool.py`, `web_search.py` |
| New | `tests/unit/test_tool_truncation.py` |

### 7.3 `BaseTool` Changes

Add `truncation_strategy` as a `Literal` attribute:

```python
from typing import Literal

class BaseTool(ABC, BaseModel):
    # ...
    truncation_strategy: Literal["head", "tail", "boundary"] = "head"
```

- `"head"` — current behavior (keep start); correct for file reads, structured responses
- `"tail"` — keep end; correct for shell output where errors appear last
- `"boundary"` — truncate at the last complete record (newline, JSON object, result entry); correct for search results and structured lists

### 7.4 Tool Strategy Assignments

| Tool | Strategy | Rationale |
|------|----------|-----------|
| `bash_tool.py` | `"tail"` | Errors and results are at the end |
| `powershell_tool.py` | `"tail"` | Same |
| `web_search.py` | `"boundary"` | Don't cut mid-result |
| `knowledge_tool.py` | `"boundary"` | Don't cut mid-entry |
| All others | `"head"` (default) | No change |

### 7.5 `ToolCollection.execute()` — Apply Strategy

Replace the current truncation block:

```python
# Current (lines 103-113 of tool_collection.py)
if result.output and len(result.output) > MAX_TOOL_OUTPUT_CHARS:
    original_length = len(result.output)
    removed = original_length - MAX_TOOL_OUTPUT_CHARS
    result.output = (
        result.output[:MAX_TOOL_OUTPUT_CHARS]
        + f"\n...[truncated: {removed} chars omitted]"
    )
```

Replace with:

```python
def _truncate(output: str, limit: int, strategy: str) -> str:
    if len(output) <= limit:
        return output
    removed = len(output) - limit
    sentinel = f"\n...[{removed} chars omitted]"
    if strategy == "tail":
        return sentinel + output[-limit:]
    if strategy == "boundary":
        # Find last complete record boundary within limit
        chunk = output[:limit]
        boundary = max(chunk.rfind("\n"), chunk.rfind("}, "), chunk.rfind("}\n"))
        if boundary > limit // 2:
            removed = len(output) - boundary
            return output[:boundary] + f"\n...[{removed} chars omitted]"
        return chunk + f"\n...[{removed} chars omitted]"
    # "head" (default)
    return output[:limit] + f"\n...[{removed} chars omitted]"

# In execute():
tool_obj = self._tools[_name]
strategy = getattr(tool_obj, "truncation_strategy", "head")
if result.output and len(result.output) > MAX_TOOL_OUTPUT_CHARS:
    original_length = len(result.output)
    result.output = _truncate(result.output, MAX_TOOL_OUTPUT_CHARS, strategy)
    result.metadata["truncated"] = True
    result.metadata["original_length"] = original_length
    result.metadata["truncation_strategy"] = strategy
```

Extract `_truncate` as a module-level pure function so it is independently testable.

### 7.6 Tests

- `tests/unit/test_tool_truncation.py`
  - `test_head_truncation_keeps_start` — output > limit; result starts with original prefix
  - `test_tail_truncation_keeps_end` — output > limit; result ends with original suffix
  - `test_boundary_truncation_no_mid_record` — output has newlines; truncation lands on a boundary
  - `test_no_truncation_below_limit` — output <= limit; output unchanged, no sentinel
  - `test_metadata_records_strategy` — `result.metadata["truncation_strategy"]` matches tool setting
  - `test_bash_uses_tail_strategy` — integration: `BashTool` outputs > limit; end preserved

### 7.7 Fitness Check

`_truncate` is a pure function with no imports — no fitness concerns. `BaseTool` change is additive.

### 7.8 Risk: Low

Pure output post-processing. Does not affect execution, LLM input schemas, or tool logic.

---

## 8. Phase 5 — Tool Result Cache

### 8.1 Goal
Avoid re-executing identical idempotent tool calls within a session. Reduces latency and LLM/API costs.

### 8.2 Files

| Action | File |
|--------|------|
| New | `weebot/application/services/tool_result_cache.py` |
| Edit | `weebot/application/models/tool_collection.py` |
| Edit | `weebot/application/di/__init__.py` (or equivalent composition root) |
| New | `tests/unit/test_tool_result_cache.py` |

### 8.3 `ToolResultCache` Design

Lives in `weebot/application/services/` — it is a pure application-layer service with no infrastructure dependencies (in-memory dict, no sqlite3).

```python
# weebot/application/services/tool_result_cache.py
from __future__ import annotations
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Optional
from weebot.tools.base import ToolResult

NON_CACHEABLE_TOOLS: frozenset[str] = frozenset({
    "bash", "powershell", "run_shell",
    "write_file", "file_editor",
    "advanced_browser", "browser", "browser_inspector",
    "computer_use", "screen_tool",
    "terminate", "ask_human",
    "dispatch_agents", "subagent_rpc",
    "voice_input", "voice_output",
    "image_gen",
})

DEFAULT_TTL_SECONDS: dict[str, int] = {
    "web_search": 300,       # 5 min
    "weather_tool": 300,
    "knowledge_tool": 3600,  # 1 hr
    "read_file": 60,         # 1 min (file may change)
    "_default": 300,
}

@dataclass
class _CacheEntry:
    result: ToolResult
    expires_at: float

class ToolResultCache:
    """Session-scoped, in-memory LRU cache for idempotent tool results.

    Key: sha256(tool_name + sorted JSON-serialized args).
    Entries expire per-tool TTL. Non-cacheable tools bypass entirely.
    Write-tracking invalidates read_file entries after a write to the same path.
    """

    def __init__(self) -> None:
        self._store: dict[str, _CacheEntry] = {}
        self._written_paths: set[str] = set()

    @staticmethod
    def _make_key(tool_name: str, args: dict) -> str:
        payload = tool_name + ":" + json.dumps(args, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def get(self, tool_name: str, args: dict) -> Optional[ToolResult]:
        if tool_name in NON_CACHEABLE_TOOLS:
            return None
        # Invalidate read_file if path was written this session
        if tool_name in ("read_file", "file_editor"):
            path = args.get("path", "")
            if path in self._written_paths:
                return None
        key = self._make_key(tool_name, args)
        entry = self._store.get(key)
        if entry is None or time.monotonic() > entry.expires_at:
            return None
        return entry.result

    def set(self, tool_name: str, args: dict, result: ToolResult) -> None:
        if tool_name in NON_CACHEABLE_TOOLS or result.is_error:
            return
        # Track written paths for read_file invalidation
        if tool_name in ("write_file", "file_editor"):
            path = args.get("path", "")
            if path:
                self._written_paths.add(path)
            return  # Don't cache write results
        ttl = DEFAULT_TTL_SECONDS.get(tool_name, DEFAULT_TTL_SECONDS["_default"])
        key = self._make_key(tool_name, args)
        self._store[key] = _CacheEntry(
            result=result,
            expires_at=time.monotonic() + ttl,
        )

    def invalidate(self, tool_name: str, args: dict) -> None:
        key = self._make_key(tool_name, args)
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()
        self._written_paths.clear()

    @property
    def size(self) -> int:
        return len(self._store)
```

### 8.4 `ToolCollection` Integration

```python
class ToolCollection:
    def __init__(self, *tools, canonicalizer=None, contract_loader=None, cache=None):
        # ...
        self._cache: Optional[ToolResultCache] = cache

    async def execute(self, _name: str, **kwargs) -> ToolResult:
        # ... canonicalizer check

        # Cache lookup (before execution)
        if self._cache is not None:
            cached = self._cache.get(_name, kwargs)
            if cached is not None:
                cached.metadata["cache_hit"] = True
                return cached

        # ... existing execution logic

        # Cache store (after successful execution)
        if self._cache is not None and not result.is_error:
            self._cache.set(_name, kwargs, result)

        return result
```

### 8.5 DI Wiring

`ToolResultCache` is scoped to a session (not a singleton). Wire it in the composition root so each `PlanActFlow` instance gets its own cache:

```python
# In di.py or wherever PlanActFlow is constructed
from weebot.application.services.tool_result_cache import ToolResultCache
cache = ToolResultCache()
tool_collection = ToolCollection(*tools, cache=cache)
```

### 8.6 Tests

- `tests/unit/test_tool_result_cache.py`
  - `test_cache_hit_returns_same_result` — same tool+args called twice; second call returns cached
  - `test_non_cacheable_tool_bypasses_cache` — `bash` call never stored or returned from cache
  - `test_error_result_not_cached` — error result not stored; next call re-executes
  - `test_ttl_expiry` — mock `time.monotonic`; entry expires after TTL
  - `test_write_invalidates_read` — write to path X; subsequent read_file for X bypasses cache
  - `test_cache_metadata_flag` — cache hit sets `result.metadata["cache_hit"] = True`
  - `test_different_args_different_cache_entries` — same tool, different args → different entries

### 8.7 Fitness Check

`test_tools_no_direct_db` — `ToolResultCache` is pure Python (dict + time), no sqlite3/aiosqlite.  
`test_application_no_module_level_infra_imports` — no infrastructure import in services layer.

### 8.8 Risk: Medium

**Primary:** Stale read_file results if a bash command writes to a file (not via the `write_file` tool). Mitigated by the short 60s TTL for file reads and the `_written_paths` tracking for explicit write tool calls.  
**Secondary:** Cache is in-memory and not shared across `PlanActFlow` instances in concurrent sessions — correct by design (session-scoped cache).

---

## 9. Phase 6 — Cross-Step TrajectoryMonitor

### 9.1 Goal
`TrajectoryMonitor` currently resets on every call to `execute_step()` because it is instantiated inside that method. Move it to `ExecutorAgent.__init__()` so it accumulates state across steps and can detect multi-step degenerate patterns.

### 9.2 Files

| Action | File |
|--------|------|
| Edit | `weebot/application/agents/executor.py` |
| Edit | `weebot/application/services/trajectory_monitor.py` |
| New | `tests/unit/test_trajectory_cross_step.py` |

### 9.3 `TrajectoryMonitor` Changes

Add `reset_step()` to clear the within-step rolling window while preserving the cross-step accumulated state. This supports the existing within-step detection while enabling cross-step detection.

```python
class TrajectoryMonitor:
    def reset_step(self) -> None:
        """Clear per-step rolling windows; preserve cross-step accumulators."""
        self._tool_signatures.clear()
        self._output_hashes.clear()
        # NOTE: _step_results is cross-step by design — do not clear it here
```

Add a cross-step counter for tracking how many consecutive steps have produced an error-like output:

```python
def __init__(self, ...):
    # ... existing
    self._consecutive_failed_steps: int = 0
    self._cross_step_error_outputs: deque[str] = deque(maxlen=5)
```

In `diagnose()`, add a new detector:

```python
# 6. Cross-step failure accumulation
if tool_output and "ERROR" in tool_output.upper():
    self._cross_step_error_outputs.append(tool_output[:100])
    self._consecutive_failed_steps += 1
else:
    self._consecutive_failed_steps = 0

if self._consecutive_failed_steps >= 3:
    return TrajectoryDiagnosis(
        health=TrajectoryHealth.TERMINAL,
        detail=f"3 consecutive steps produced errors — possible systemic failure",
        recovery_message=(
            "Multiple consecutive steps have failed. Consider whether the overall "
            "task approach is correct, or whether external resources are unavailable."
        ),
        affected_step_ids=[step_id],
    )
```

### 9.4 `ExecutorAgent` Changes

Move monitor creation from `execute_step()` to `__init__`:

```python
class ExecutorAgent:
    def __init__(self, ...):
        # ... existing
        self._trajectory_monitor = TrajectoryMonitor()   # MOVED HERE
```

In `execute_step()`, replace:

```python
# REMOVE:
from weebot.application.services.trajectory_monitor import TrajectoryMonitor
self._trajectory_monitor = TrajectoryMonitor()
```

With:

```python
# At the start of execute_step() — reset per-step windows only:
self._trajectory_monitor.reset_step()
```

### 9.5 Tests

- `tests/unit/test_trajectory_cross_step.py`
  - `test_within_step_repetition_still_detected` — same-tool repeat within one step still fires
  - `test_cross_step_error_accumulation` — 3 consecutive steps with ERROR outputs trigger TERMINAL
  - `test_step_success_resets_failure_counter` — successful step resets cross-step error counter
  - `test_stagnation_detected_across_steps` — same `step_result` across 3 steps still fires

### 9.6 Fitness Check

No new imports or layer violations. `TrajectoryMonitor` stays in `application/services/`. No new ports.

### 9.7 Risk: Low

`reset_step()` is additive. Moving monitor creation to `__init__` is a one-line change. The new cross-step detector only fires on 3 consecutive error steps — not triggered by normal operation.

---

## 10. Test Strategy Summary

Each phase ships with its own test file. Shared test utilities (mock tools, fake LLM responses) live in `tests/conftest.py` or a new `tests/unit/fixtures/tool_fixtures.py`.

### Coverage targets

| Phase | New test file | Min coverage of changed code |
|-------|---------------|------------------------------|
| 1 | `test_tool_collection_retry.py` | 90% of retry path |
| 2 | `test_parallel_tool_execution.py` | 100% of `_execute_tool_batch` |
| 3 | `test_tool_health.py` | 90% of health check paths |
| 4 | `test_tool_truncation.py` | 100% of `_truncate` function |
| 5 | `test_tool_result_cache.py` | 95% of `ToolResultCache` |
| 6 | `test_trajectory_cross_step.py` | 90% of new monitor paths |

Run the full suite after each phase:

```bash
pytest tests/unit/test_architecture_fitness.py -v   # must stay green
pytest tests/unit/ -v --cov=weebot --cov-report=term-missing
```

---

## 11. Implementation Order

```
Week 1:  Phase 1 (cleanup) + Phase 6 (trajectory)  — lowest risk, shippable immediately
Week 2:  Phase 2 (parallel execution)               — most impactful, isolated to executor
Week 3:  Phase 3 (timeouts + health)                — additive to BaseTool
         Phase 4 (truncation)                        — pure post-processing
Week 4:  Phase 5 (cache)                            — new service, depends on Phase 3 stable
```

Each phase merges to `feature/tool-enhancements` via a separate PR. The fitness test suite runs on every PR as the CI gate.

---

## 12. Invariants to Preserve

The following must not change behavior regardless of which phases are active:

1. `ToolResult.is_error` semantics — `error is not None` means failure
2. `terminate` tool handling — `_should_terminate = True` must fire on first call, not be batched
3. `WaitForUserEvent` emission — must still pause the step loop immediately
4. `_conversation_buffer` ordering — tool results must appear in declared tool-call order
5. `StepBudget` accounting — each `_execute_tool_call` consumes exactly one step budget unit; parallel execution of N tools in one LLM turn still counts as N tool calls but only one iteration of the outer `while self._step_budget.consume()` loop
6. Architecture fitness tests — all 19 tests must pass after every phase
