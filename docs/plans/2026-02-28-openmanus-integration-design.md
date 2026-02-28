# OpenManus Integration Design

**Date:** 2026-02-28
**Approach:** Architecture-first selective integration (Approach 2)
**Strategy:** Port OpenManus's core agent architecture and tools into weebot additively — no existing code deleted.

---

## What We're Taking From OpenManus

| OpenManus Component | Where It Goes In weebot |
|---|---|
| `BaseTool(BaseModel)` + `to_param()` | `weebot/tools/base.py` |
| `Message` / `Memory` | `weebot/domain/models.py` (extend) |
| `ToolCallAgent` (ReAct loop) | `weebot/core/tool_agent.py` |
| `WebSearch` multi-engine | `weebot/tools/web_search.py` |
| `StrReplaceEditor` | `weebot/tools/file_editor.py` |
| `AskHuman` + `Terminate` | `weebot/tools/control.py` |
| `PlanningFlow` + `PlanningTool` | `weebot/flow/planning.py` |

**What we do NOT take:** Docker sandbox, A2A protocol, Daytona, Loguru (we keep our own logger), Bedrock client (we keep ModelRouter), Crawl4AI (out of scope).

---

## Architecture

### Layer map (additive — existing code unchanged)

```
weebot/tools/base.py          ← NEW: BaseTool protocol
weebot/tools/web_search.py    ← NEW: WebSearchTool (Google/DDG/Bing)
weebot/tools/file_editor.py   ← NEW: StrReplaceEditorTool
weebot/tools/control.py       ← NEW: AskHumanTool, TerminateTool
weebot/tools/tool_collection.py ← NEW: ToolCollection registry

weebot/domain/models.py       ← EXTEND: add Message, Memory, AgentState
weebot/core/tool_agent.py     ← NEW: ToolCallWeebotAgent (ReAct loop)
weebot/flow/planning.py       ← NEW: PlanningFlow, PlanningTool

weebot/agent_core_v2.py       ← UNCHANGED (WeebotAgent lives on)
weebot/ai_router.py           ← UNCHANGED (ModelRouter provides LLM)
weebot/notifications.py       ← UNCHANGED (integrated into ToolCallWeebotAgent)
weebot/state_manager.py       ← UNCHANGED (integrated into ToolCallWeebotAgent)
```

---

## Key Design Decisions

### 1. BaseTool Protocol
Follows OpenManus exactly:
```python
class BaseTool(ABC, BaseModel):
    name: str
    description: str
    parameters: dict  # JSON Schema

    async def execute(self, **kwargs) -> ToolResult: ...
    def to_param(self) -> dict: ...  # → OpenAI function spec
```
`ToolResult` is a simple dataclass: `output: str`, `error: str | None`, `base64_image: str | None`.

Existing tools (PowerShellTool, ScreenCaptureTool) get thin `BaseTool` wrappers in their files — no core logic change.

### 2. Message / Memory Model
Added to `weebot/domain/models.py`:
- `Role` enum: `system | user | assistant | tool`
- `Message` dataclass with `role`, `content`, `tool_calls`, `tool_call_id`
- `Memory` with `max_messages=100`, `add()`, `to_openai_format()` for LLM calls

### 3. ToolCallWeebotAgent (ReAct Loop)
```
while not finished and steps < max_steps:
    think()  →  LLM call with tool specs → get tool_calls or text response
    act()    →  execute tool_calls → store results in memory
    if Terminate called → finished = True
    if stuck (duplicate messages) → inject anti-stuck prompt
```

**weebot additions over OpenManus:**
- Uses `ModelRouter` (not raw OpenAI) → cost tracking + multi-provider
- Calls `StateManager.save_checkpoint()` after each step → crash recovery
- Calls `NotificationManager.notify()` on task start/complete/error
- Respects `SafetyChecker` before executing PowerShell commands

### 4. WebSearch Tool
Three backends: `GoogleSearch`, `DuckDuckGoSearch`, `BingSearch`.
Fallback order: Google → DuckDuckGo → Bing.
Uses `aiohttp` (already installed). Returns top-N results as formatted text.

### 5. StrReplaceEditorTool
Operations: `view`, `create`, `str_replace`, `insert`.
Local filesystem only (no sandbox). Uses Python stdlib `pathlib`.

### 6. PlanningFlow
```
1. LLM generates numbered step plan (using PlanningTool)
2. For each step: dispatch to ToolCallWeebotAgent
3. Mark step complete, persist to StateManager
4. Final LLM summary
```

---

## Test Strategy

Each phase has tests before implementation (TDD):
- `tests/unit/test_base_tool.py` — BaseTool protocol, ToolResult
- `tests/unit/test_tool_agent.py` — ReAct loop with mocks
- `tests/unit/test_web_search.py` — engine fallback logic
- `tests/unit/test_file_editor.py` — str_replace, view, create
- `tests/integration/test_planning_flow.py` — full flow with MockModelProvider

---

## Non-Goals (explicitly out of scope)

- Docker sandbox
- A2A / MCP server mode
- Loguru migration
- Bedrock / Ollama support
- Crawl4AI
- Chart visualization

---

## Success Criteria

1. All 73 existing tests still pass after each phase
2. New `ToolCallWeebotAgent` can complete a multi-step task using WebSearch + FileEditor + PowerShell
3. `PlanningFlow` generates and executes a 3-step plan end-to-end
4. No import of OpenManus code — everything is ported/rewritten to fit weebot conventions
