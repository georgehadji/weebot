# Pre-Existing Issues Fix Plan

**Date:** 2026-06-12
**Context:** Identified during complex task execution testing of the Self-Harness system.
These are NOT caused by Self-Harness — they're pre-existing wiring/memory/display issues.

---

## Issue 1: `web_search` returns "Unknown tool"

### Root Cause

The `web_search` tool IS registered in the admin role AND constructs successfully.
The `ToolCollection` receives it during construction. But at runtime,
`ToolCollection.execute()` reports `Unknown tool: 'web_search'`.

Two possible causes (need runtime debugging to confirm):

**Hypothesis A — Health check filtering:**
`ToolCollection.to_params()` (`tool_collection.py:120-133`) skips tools
where `self._healthy[tool.name] == False`. If the initial health check
(which runs web requests) failed for `web_search`, the tool's schema is
excluded from the LLM's tool list. The LLM never sees it, but if it
hallucinated the name from instructions, the execute path would find
the tool in `self._tools` and execute it. So this hypothesis only
explains "tool not offered to LLM", not "Unknown tool at execute time".

**Hypothesis B — ToolCollection rebuild in `build_tools()`:**
`factories.py:172` does `list(registry.create_tool_collection(...))`.
`ToolCollection` may not implement `__iter__` properly — if iterating
yields tool names (strings) instead of `BaseTool` instances, the
subsequent `ToolCollection(*combined)` receives strings, building
`self._tools = {"w": "w", "e": "e", ...}` (char-keyed dict from
iterating a string). This would mean NO tools are accessible by name.

### Fix Plan

**Phase 1: Diagnostic logging (15 min)**

Add to `ToolCollection.execute()` at `tool_collection.py:159`:
```python
if _name not in self._tools:
    logger.error(
        "Unknown tool %r. Available tools: %s (total: %d)",
        _name, list(self._tools.keys())[:10], len(self._tools),
    )
```

Add to `build_tools()` at `factories.py:175`:
```python
logger.info("Tools built for role %s: %s", role,
            [t.name for t in combined] if hasattr(combined[0], 'name') else combined)
```

**Phase 2: Fix `__iter__` if broken (15 min)**

Check if `ToolCollection.__iter__` exists. If not, add:
```python
def __iter__(self):
    return iter(self._tools.values())
```

If it exists but yields names instead of tools, fix the yield.

**Phase 3: Fix health-check race (15 min)**

Make `execute()` always find the tool in `self._tools` regardless of
health status — health should only gate `to_params()` (what the LLM
sees), not `execute()` (what happens when the LLM calls it).

### Effort: 45 min | Risk: Low

---

## Issue 2: `python_execute` no SandboxPort in CLI path

### Root Cause

`create_tool_collection_from_names()` in `tool_registry.py:227` calls
`PythonExecuteTool()` with no constructor arguments. The tool needs a
`SandboxPort` to execute Python code.

The DI container creates a sandbox via `_create_sandbox()` in
`_factories.py:134-149` — it checks `settings.sandbox_mode` and creates
`NativeWindowsSandbox()` on Windows. But this sandbox is never passed
to the tool registry when building tools for the CLI path.

The tool registry already has special-case injection for:
- `llm_port` → tools in `_llm_required_tools`
- `browser` → tools in `_browser_adapter_tools`
- `RerankPort` → tools with `set_rerank()` method

It needs the same pattern for `SandboxPort`.

### Fix Plan

**File:** `weebot/tools/tool_registry.py`

Add `PythonExecuteTool` to a `_sandbox_required_tools` set and inject
the sandbox during construction:

```python
_sandbox_required_tools = {"python_execute"}

# In create_tool_collection_from_names():
if name in _sandbox_required_tools:
    sandbox = None
    try:
        from weebot.infrastructure.sandbox.factory import create_sandbox
        sandbox = create_sandbox()
    except Exception as exc:
        logger.warning("Sandbox creation failed for %s: %s", name, exc)
    if sandbox:
        tool = tool_cls(sandbox=sandbox)
    else:
        logger.warning("Skipping %s: no sandbox available", name)
        continue
```

### Effort: 20 min | Risk: Low

---

## Issue 3: MemoryError in `constraint_extractor.py`

### Root Cause

`memory_compactor.py:52-53` concatenates up to 200 raw events into one
string via `str(e)` — which serializes the full Pydantic model including
`ToolEvent.result` (raw tool output that can be megabytes per event).

For a session with 50+ tool calls producing large outputs (HTML pages,
API responses, file listings), the concatenated string can exceed 1 GB.
Then `ConstraintExtractor.extract()` runs 8 regex `finditer()` passes
on this string, creating massive match objects → MemoryError.

### Fix Plan

**Phase 1: Cap event text size (15 min)**

File: `weebot/application/services/memory_compactor.py`

Before passing to constraint_extractor, truncate each event's text:
```python
MAX_EVENT_TEXT_LEN = 2000  # 2KB per event
MAX_TOTAL_TEXT_LEN = 200_000  # 200KB total

_tail = session.events[-200:]
parts = []
total = 0
for e in _tail:
    text = str(e)[:MAX_EVENT_TEXT_LEN]
    if total + len(text) > MAX_TOTAL_TEXT_LEN:
        break
    parts.append(text)
    total += len(text)
all_event_text = "\n".join(parts)
```

**Phase 2: Cap ToolEvent.result in str() (15 min)**

File: `weebot/domain/models/event.py`

Override `__str__` on `ToolEvent` to truncate large results:
```python
def __str__(self) -> str:
    if self.result and len(self.result) > 2000:
        truncated = self.result[:2000] + f"... [truncated {len(self.result)} chars]"
        return self.model_copy(update={"result": truncated}).__str__()
    return super().__str__()
```

### Effort: 30 min | Risk: Low

---

## Issue 4: Kimi `<system_reminder>` leaks in terminal output

### Root Cause

The Kimi K2.7 Code model includes `<system_reminder>` XML blocks in its
`msg.content` response. The OpenAI adapter passes this through verbatim:

```python
# openai_adapter.py:149
return LLMResponse(content=msg.content or "", ...)
```

The executor creates `ThoughtEvent(thought=assistant_content.strip())`
with the raw content, and the CLI event logger prints it:

```python
# event_logger.py:70
return f"    [dim italic]🤔 {event.thought}[/dim italic]"
```

No layer strips the XML system markers.

### Fix Plan

**File:** `weebot/infrastructure/adapters/llm/openai_adapter.py`

Add a post-processing step after reading `msg.content`:

```python
import re

def _strip_system_markers(content: str) -> str:
    """Remove provider-injected system markers from response content."""
    if not content:
        return content
    # Strip <system_reminder>...</system_reminder> blocks
    content = re.sub(
        r'<system_reminder>.*?</system_reminder>',
        '', content, flags=re.DOTALL,
    ).strip()
    return content

# In chat():
return LLMResponse(
    content=_strip_system_markers(msg.content or ""),
    ...
)
```

This handles Kimi, DeepSeek, and any other provider that injects
XML-style system markers into response content.

### Effort: 15 min | Risk: Low

---

## Priority Order

| # | Issue | Impact | Effort | Priority |
|---|---|---|---|---|
| 1 | web_search Unknown tool | 🔴 Blocks research tasks | 45 min | P0 |
| 2 | python_execute no sandbox | 🟡 Blocks code validation | 20 min | P1 |
| 3 | MemoryError on large sessions | 🟡 Crashes long-running tasks | 30 min | P1 |
| 4 | `<system_reminder>` leaks | 🟢 Cosmetic / noisy output | 15 min | P2 |

**Total effort:** ~2 hours

## Validation

After implementing all 4 fixes, re-run:
```
python -m cli.main flow run "Research the top 5 Python static analysis tools..."
```

**Success criteria:**
1. `web_search` tool calls return actual search results (not "Unknown tool")
2. `python_execute` runs Python code without "no SandboxPort" error
3. Task completes all 10+ steps without MemoryError
4. No `<system_reminder>` blocks in terminal output
