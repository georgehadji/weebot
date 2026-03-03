# System Knowledge Map — Weebot AI Agent Framework

**Version:** 2.0 (Updated 2026-03-03 — full epistemic decomposition)
**Method:** Epistemic classification + Chain of Verification (CoVe)
**Classifications:** [VERIFIED] = confirmed by test + code | [HYPOTHESIS] = inferred | [UNKNOWN] = untested

---

## 1. Module Hierarchy & Dependency Graph

```
weebot/
├── config/settings.py          [VERIFIED]   — WeebotSettings (pydantic-settings)
├── domain/
│   ├── models.py               [VERIFIED]   — Task, Project, Message, AgentState, Role
│   ├── ports.py                [VERIFIED]   — IModelProvider, IRepository, INotifier, ITool
│   └── exceptions.py           [VERIFIED]   — WeebotError hierarchy (9 exception types)
├── utils/
│   ├── logger.py               [VERIFIED]   — RotatingFileHandler 5MB
│   └── backoff.py              [VERIFIED]   — RetryWithBackoff + BackoffConfig
├── tools/
│   ├── base.py                 [VERIFIED]   — BaseTool + ToolResult + ToolCollection
│   ├── bash_tool.py            [VERIFIED]   — BashTool (PowerShell/WSL2)
│   ├── python_tool.py          [VERIFIED]   — PythonExecuteTool
│   ├── file_editor.py          [VERIFIED]   — StrReplaceEditorTool
│   ├── web_search.py           [VERIFIED]   — DuckDuckGo + Bing fallback
│   ├── computer_use.py         [VERIFIED]   — ComputerUseTool (mouse/keyboard/OCR)
│   ├── advanced_browser.py     [VERIFIED]   — Playwright-based browser automation
│   ├── scheduler.py            [VERIFIED]   — APScheduler cron/interval jobs
│   ├── control.py              [VERIFIED]   — TerminateTool + AskHumanTool
│   └── screen_tool.py          [VERIFIED]   — mss screen capture
├── sandbox/
│   └── executor.py             [VERIFIED]   — SandboxedExecutor + ExecutionResult
├── core/
│   ├── agent.py                [VERIFIED]   — RecursiveWeebotAgent (OEAR loop)
│   ├── safety.py               [VERIFIED]   — SafetyChecker
│   ├── approval_policy.py      [VERIFIED]   — ExecApprovalPolicy (deny/ask/auto)
│   ├── agent_context.py        [VERIFIED]   — AgentContext + EventBroker (Phase 7)
│   ├── agent_factory.py        [HYPOTHESIS] — AgentFactory (tool validation gap)
│   └── (circuit_breaker.py)    [UNKNOWN]    — Draft only, not integrated
├── mcp/
│   ├── server.py               [VERIFIED]   — WeebotMCPServer (FastMCP 1.26.0)
│   └── resources.py            [VERIFIED]   — activity/state/schedule resources
├── flow/planning.py            [VERIFIED]   — PlanningTool + PlanningFlow
├── agent_core_v2.py            [VERIFIED]   — WeebotAgent + ToolCallWeebotAgent (ReAct)
├── ai_router.py                [UNKNOWN]    — ModelRouter (2 critical bugs — see section 6)
├── state_manager.py            [VERIFIED]   — SQLite + ThreadPoolExecutor (WAL)
├── activity_stream.py          [VERIFIED]   — Ring buffer (per-project secondary index)
├── notifications.py            [VERIFIED]   — Telegram/Slack/Log/WindowsToast
├── notifications_categorizer.py [VERIFIED]  — 3-tier notification categorization
└── tray.py                     [VERIFIED]   — System tray app (pystray)
```

---

## 2. Dependency Ownership Map

| Module | Depends On | Depended By |
|--------|-----------|-------------|
| `config/settings.py` | pydantic-settings | ALL modules |
| `domain/models.py` | pydantic | agent_core_v2, state_manager, mcp/server |
| `domain/ports.py` | domain/models | agent_core_v2, core/agent |
| `domain/exceptions.py` | — | ALL modules |
| `utils/backoff.py` | asyncio | ai_router, notifications, core/agent_context |
| `tools/base.py` | pydantic, asyncio | all tool implementations |
| `sandbox/executor.py` | asyncio, psutil | bash_tool, python_tool |
| `tools/bash_tool.py` | sandbox/executor, core/approval_policy | agent_core_v2, mcp/server |
| `core/agent_context.py` | asyncio, utils/logger | core/agent_factory |
| `core/agent_factory.py` | core/agent_context, tools/tool_registry | (Phase 2 Orchestrator) |
| `ai_router.py` | langchain_openai, langchain_anthropic | agent_core_v2 |
| `state_manager.py` | sqlite3, asyncio, json | agent_core_v2, mcp/resources |
| `activity_stream.py` | collections | mcp/resources, state_manager |
| `mcp/server.py` | FastMCP, all tools | run_mcp.py |

---

## 3. State Ownership Map

| State | Owner | Access Pattern | Thread Safety |
|-------|-------|----------------|---------------|
| `Task/Project records` | `state_manager.SQLite` | async read/write via ThreadPool | [VERIFIED] WAL + locks |
| `AgentContext.shared_data` | `core/agent_context` | async via asyncio.Lock | [VERIFIED] lock added |
| `EventBroker._subscribers` | `core/agent_context` | asyncio.Queue per subscriber | [VERIFIED] pub/sub with retry |
| `ActivityStream._buffer` | `activity_stream` | single-writer, main thread | [VERIFIED] deque(maxlen) |
| `ActivityStream._by_project` | `activity_stream` | single-writer, main thread | [VERIFIED] cleanup on evict |
| `ModelRouter.cost_tracker` | `ai_router` | sync in async context | [UNKNOWN] not thread-safe |
| `ResponseCache (file)` | `ai_router` | file I/O, no locking | [UNKNOWN] race condition possible |
| `SchedulerTool._scheduler` | `tools/scheduler` | APScheduler internal | [VERIFIED] max_instances=1, coalesce |
| `AgentFactory.spawned` | `core/agent_factory` | dict, async context | [HYPOTHESIS] no eviction policy |

---

## 4. Async Boundary Map

| Location | Pattern | Classification |
|----------|---------|----------------|
| `ToolCollection.execute()` | `await tool.execute(**kwargs)` | [VERIFIED] |
| `AgentContext.store_result()` | `async with self._data_lock` + `asyncio.timeout(10.0)` | [VERIFIED] |
| `EventBroker.publish()` | `asyncio.wait_for(q.put(), timeout=5.0)` + exponential backoff | [VERIFIED] |
| `StateManager` | `loop.run_in_executor(self._pool, ...)` | [VERIFIED] |
| `SandboxedExecutor.run()` | `asyncio.create_subprocess_exec` + `asyncio.wait_for` | [VERIFIED] |
| `ModelRouter.generate_with_fallback()` | bare `except:` swallows CancelledError | **[CRITICAL BUG]** |
| `ResponseCache.get/set()` | Synchronous file I/O inside async function | [HYPOTHESIS] blocks event loop |
| `ComputerUseTool.execute()` | `asyncio.to_thread(...)` | [VERIFIED] |
| `AdvancedBrowserTool` | Playwright async API | [VERIFIED] |

---

## 5. Error Handling Map

| Module | Exception Handling | Classification |
|--------|-------------------|----------------|
| `ToolCollection.execute()` | Catches Exception only → ToolResult.error_result | [VERIFIED] |
| `EventBroker.publish()` | Catches asyncio.QueueFull + Exception, retries | [VERIFIED] |
| `SandboxedExecutor.run()` | asyncio.TimeoutError -> kills proc | [VERIFIED] |
| `BashTool.execute()` | ExecApprovalPolicy gate -> ToolResult.error_result | [VERIFIED] |
| `StateManager` | DB errors re-raised as WeebotError | [VERIFIED] |
| `ModelRouter.generate_with_fallback()` | Bare `except:` catches ALL including BaseException | **[CRITICAL BUG]** |
| `AgentFactory.spawn_agent()` | Minimal try/except | [HYPOTHESIS] |
| `ActivityStream.push()` | No error handling (none needed) | [VERIFIED] |

---

## 6. Hidden Assumptions (Epistemic Inventory)

| ID | Assumption | Module | Classification | Risk |
|----|-----------|--------|----------------|------|
| A1 | `asyncio.CancelledError` is subclass of `Exception` | ai_router | **WRONG** — BaseException in Python 3.8+ | CRITICAL |
| A2 | Budget limits enforced before API calls | ai_router | **WRONG** — `is_budget_exceeded()` never called | HIGH |
| A3 | Allowed tool names validated against registry | agent_factory | **WRONG** — only checks for empty strings `not t` | MEDIUM |
| A4 | Per-project ActivityStream deques stay bounded | activity_stream | [VERIFIED] — cleanup logic correct for single-writer | LOW |
| A5 | File-based cache safe for concurrent async access | ai_router | [HYPOTHESIS] — no locking on file writes | LOW |
| A6 | AgentContext nesting depth is bounded | agent_context | [VERIFIED] — depth limit enforced | OK |
| A7 | ToolCollection.execute() kwargs dict not mutated | tools/base | [HYPOTHESIS] — `_max_retries` popped from caller's dict | LOW |
| A8 | Langchain providers handle cancellation correctly | ai_router | [UNKNOWN] — not tested | MEDIUM |
| A9 | Spawned agents in AgentFactory tracked for cleanup | agent_factory | [HYPOTHESIS] — dict may grow indefinitely | LOW |
| A10 | ResponseCache file writes are atomic | ai_router | [HYPOTHESIS] — write_text() not atomic on Windows | LOW |

---

## 7. Data Flow: Critical Paths

### 7.1 Tool Execution Flow (VERIFIED — correct)
```
WeebotAgent.step()
  -> ToolCollection.execute(name, **kwargs)
     -> BaseTool.execute(**kwargs)
        -> SandboxedExecutor.run()   [bash/python]
           -> asyncio.create_subprocess_exec
           -> asyncio.wait_for(communicate(), timeout)
           -> ExecutionResult
        -> ToolResult(success, data, metadata)
     -> metadata.update({execution_time_ms, retry_count, tool_name})
  -> ToolResult
```

### 7.2 AI Routing Flow (BUGS PRESENT)
```
WeebotAgent.generate()
  -> ModelRouter.generate_with_fallback(prompt, task_type)
     -> ResponseCache.get(cache_key)         [sync I/O — blocks event loop]
     -> ModelRouter.select_model()
     -> ModelRouter._call_model(model_id, prompt)
        -> LangChain client.ainvoke(messages)
     -> [EXCEPTION] -> fallback loop
           except:                             [BUG-1: catches CancelledError]
               continue
     -> CostTracker.record_call()              [records cost]
     -> [MISSING] is_budget_exceeded()         [BUG-2: budget never checked]
  -> str response
```

### 7.3 Multi-Agent Coordination Flow (HYPOTHESIS — validation gap)
```
AgentFactory.spawn_agent(role, context)
  -> RoleBasedToolRegistry.get_tools_for_role(role)
     -> invalid_tools = [t for t in allowed if not t]   [BUG-3: only catches ""]
  -> AgentContext.create_child()
     -> asyncio.Lock() shared
     -> EventBroker inherited
  -> WeebotAgent created
  -> spawned[role] = agent                              [BUG-4: duplicate role overwrites]
```

### 7.4 State Persistence Flow (VERIFIED — correct)
```
StateManager.save_task_async(task)
  -> loop.run_in_executor(pool, self._save_task, task)
     -> sqlite3 connection (WAL mode)
     -> json.dumps(task.dict())                         [safe serialization]
     -> INSERT OR REPLACE
  -> None
```

---

## 8. CoVe Validation Results

### Chain 1: AgentContext Concurrency Safety
- Claim: Multiple async tasks can safely write to shared_data
- Verify: `async with self._data_lock` present in store_result() — PASS
- Verify: Lock created in `__init__` as `asyncio.Lock()` — PASS
- Verify: Lock passed to child contexts — PASS
- **Result: [VERIFIED] — Race condition from v1 analysis is FIXED**

### Chain 2: EventBroker Delivery Guarantee
- Claim: Events are reliably delivered to all subscribers
- Verify: `asyncio.wait_for(q.put(), timeout=5.0)` prevents indefinite block — PASS
- Verify: Exponential backoff: `0.1 * (2 ** attempt)` capped at 30s — PASS
- Verify: `_dropped_events` counter maintained — PASS
- Verify: `MAX_HISTORY_SIZE = 1000` prevents memory exhaustion — PASS
- **Result: [VERIFIED] — Silent event dropping from v1 analysis is FIXED**

### Chain 3: StateManager Non-Blocking
- Claim: SQLite operations don't block the async event loop
- Verify: `ThreadPoolExecutor(max_workers=4)` initialized — PASS
- Verify: `loop.run_in_executor(self._pool, ...)` in all async methods — PASS
- Verify: `__aexit__` uses async variant `_close_subsession_async()` — PASS
- **Result: [VERIFIED] — Blocking from v1 analysis is FIXED**

### Chain 4: ModelRouter Budget Enforcement
- Claim: API calls stop when daily budget is exceeded
- Verify: `CostTracker.is_budget_exceeded()` defined — PASS
- Verify: `generate_with_fallback()` calls `is_budget_exceeded()` — FAIL (not found)
- Verify: `_call_model()` calls `is_budget_exceeded()` — FAIL (not found)
- **Result: [CRITICAL FAILURE] — Budget tracked but NEVER enforced**

### Chain 5: Cancellation Safety
- Claim: Async tasks using ai_router can be properly cancelled
- Verify: `generate_with_fallback()` uses `except Exception:` — FAIL (uses bare `except:`)
- Verify: `asyncio.CancelledError` is BaseException subclass in Python 3.8+ — PASS (confirms bug)
- **Result: [CRITICAL FAILURE] — Task cancellation broken in fallback loop**

### Chain 6: SandboxedExecutor Memory Safety
- Claim: Runaway processes killed before OOM
- Verify: Memory monitor thread via `asyncio.to_thread()` — PASS
- Verify: `proc.kill()` on timeout — PASS
- Verify: Graceful degradation if psutil absent — PASS
- **Result: [VERIFIED] — Memory safety implemented correctly**

---

## 9. Module Quality Summary

| Module | Quality | Issues | Priority |
|--------|---------|--------|----------|
| `sandbox/executor.py` | EXCELLENT | None | None |
| `core/agent_context.py` | EXCELLENT | v1 issues all fixed | None |
| `state_manager.py` | EXCELLENT | v1 issues all fixed | None |
| `activity_stream.py` | GOOD | Per-project deques unbound (cleanup logic correct) | Monitor |
| `tools/base.py` | GOOD | Linear retry backoff; kwargs mutation (minor) | Low |
| `core/agent_factory.py` | FAIR | Tool validation gap; duplicate role overwrite | Medium |
| `ai_router.py` | POOR | **2 critical bugs** (bare except; no budget enforcement) | **IMMEDIATE** |
| `core/agent.py` | GOOD | No issues | None |
| `mcp/server.py` | GOOD | No issues | None |
| `notifications.py` | GOOD | No issues | None |

---

*Last Updated: 2026-03-03 | Version 2.0*
*v1.0 (2026-03-03 08:33) — issues #1,#2,#3 all confirmed FIXED in codebase*
