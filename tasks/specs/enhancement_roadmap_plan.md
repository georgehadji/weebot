# Weebot Enhancement Roadmap — Implementation Plan

**Status:** Draft  
**Architecture baseline:** Clean Hexagonal (Interfaces → Infrastructure → Application → Domain)  
**Fitness gate:** `pytest tests/unit/test_architecture_fitness.py` must stay green after every phase  
**Source research:** Deep Agents (`langchain-ai/deepagents` v0.6.8) architecture patterns — middleware stack, BackendProtocol, FilesystemPermission, DeltaChannel, SubAgentMiddleware, HarnessProfile

---

## 1. Architecture Constraints

All changes must satisfy `tests/unit/test_architecture_fitness.py`:

- **Domain pure:** `weebot/domain/` must not import from Application or Infrastructure
- **Application no module-level infra:** Infrastructure imports only inside functions or `TYPE_CHECKING` blocks
- **Tools no sqlite3:** `weebot/tools/` must not import `sqlite3`, `aiosqlite`, `sqlalchemy`
- **Ports need adapters:** Every new `weebot/application/ports/` needs a registered adapter in DI
- **No circular imports:** Verify with `test_no_circular_imports`
- **No flat files at `weebot/` root:** New modules live inside the correct layer package
- **Immutable state mutations:** Always `model_copy(update=...)`, never in-place assignment
- **Fail-open defaults:** Every LLM call returns a safe default on exception

Layer placement for new files:

| What | Where |
|------|-------|
| New port | `weebot/application/ports/` + adapter in `weebot/infrastructure/` or `weebot/application/services/` |
| New service | `weebot/application/services/` |
| New middleware | `weebot/application/middleware/` (new directory) |
| New domain model | `weebot/domain/models/` |
| DI wiring | `weebot/application/di/_factories.py` + `weebot/application/di/__init__.py` |
| Config extension | `weebot/application/models/plan_act_flow_config.py` |
| Flow wiring | `weebot/application/flows/plan_act_flow.py` |
| CLI commands | `cli/commands/` |

---

## 2. Phase Overview

```
Phase 1   Quick wins (6 items, ≤20 lines each)                       (1 hour)
Phase 2   BackendProtocol + unified tool I/O                          (2-3 hours)
Phase 3   FilesystemPermission model                                  (1 hour)
Phase 4   DI wiring fix for code_reviewer                             (30 min)
Phase 5   Memory lifecycle + retention automation                    (1-2 hours)
Phase 6   Executor monolithic → middleware extraction                (4-6 hours, largest change)
Phase 7   Sub-agent middleware                                        (3-4 hours)
Phase 8   DreamerAgent auto-pipeline                                  (2 hours)
Phase 9   Harness profiles (model-specific tool/middleware configs)   (2-3 hours)
```

Phases 1, 2, 3, and 4 are independent and can run in parallel.
Phase 6 depends on Phase 2 (middleware uses BackendProtocol).
Phase 7 depends on Phase 6 (sub-agent middleware extends middleware stack).
Phases 5, 8, and 9 are independent.

---

## 3. Phase 1 — Quick Wins (≤20 lines each)

### 3.1 Goal
Six changes that improve observability, correctness, and discoverability with minimal risk.

### 3.2 Changes

| # | File | Change | Lines |
|---|------|--------|-------|
| 1 | `weebot/application/models/tool_collection.py` | Add `logger.warning()` to `_get_cache()` except path so silent cache-disable is observable | +2 |
| 2 | `weebot/application/models/tool_collection.py` | Add `", "` to boundary truncation `max()` call so JSON dict entries (not just arrays) are properly truncated at record boundaries | +1 |
| 3 | `weebot/tools/weather_tool.py` | Add `health_check()` — try `import aiohttp` | +8 |
| 4 | `weebot/tools/schedule_tool.py` | Add `health_check()` — try `import schedule` | +8 |
| 5 | `weebot/tools/image_gen_tool.py` | Add `health_check()` — always `True` (no hard optional deps) | +5 |
| 6 | `weebot/skills/builtin/reify_skill/SKILL.md` + `weebot/skills/builtin/seo_optimizer/SKILL.md` | Verify trigger keywords in frontmatter are correct so the skills auto-activate on matching prompts | +0-2 |

### 3.3 Tests

Each is a unit-testable, single-function change. Test file: `tests/unit/test_quick_wins.py` covering:
- `_get_cache` warning is emitted once on import failure
- Boundary truncation handles `"key": "value",` entries
- WeatherTool, ScheduleTool health_check returns expected value

### 3.4 Risk: Low

Additive-only. No behavioral changes to existing code paths.

---

## 4. Phase 2 — BackendProtocol (Unified Tool I/O)

### 4.1 Goal

Replace the pattern where every tool (`BashTool`, `PowerShellTool`, `FileEditor`, `BrowserTool`) builds its own subprocess/sandbox path with a single `BackendPort` interface backed by the existing `SandboxPort` adapter. This reduces 39 tool files to shared backend calls and makes tool behavior consistent.

### 4.2 Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ Tools (BashTool, FileEditor, etc.)                           │
│   → call backend.read(path) / backend.write(path, content)   │
│       / backend.execute(command) / backend.glob(pattern)     │
│                                                              │
│          ↓                                                    │
│ ┌──────────────────────────────────────┐                     │
│ │ BackendPort (new ABC)                │ ← application/ports │
│ │  • ls(path) → LsResult               │                     │
│ │  • read(path, offset, limit) → str   │                     │
│ │  • write(path, content) → bool       │                     │
│ │  • edit(path, old, new) → EditResult │                     │
│ │  • glob(pattern, path) → list[str]   │                     │
│ │  • grep(pattern, path, glob) → list  │                     │
│ │  • execute(cmd, timeout) → ExecuteR  │ ← extends Sandbox   │
│ └──────────────────┬───────────────────┘                     │
│                    │                                          │
│ ┌──────────────────▼───────────────────┐                     │
│ │ SandboxBackendAdapter (existing)     │ ← infrastructure    │
│ │  delegates to SandboxPort            │                     │
│ └──────────────────────────────────────┘                     │
│                    │                                          │
│ ┌──────────────────▼───────────────────┐                     │
│ │ SandboxPort (existing)               │ ← application/ports │
│ │  execute_shell(script, shell, ...)   │                     │
│ └──────────────────────────────────────┘                     │
└──────────────────────────────────────────────────────────────┘
```

### 4.3 New Files

| File | Purpose |
|------|---------|
| `weebot/application/ports/backend_port.py` | `BackendPort` ABC — `ls`, `read`, `write`, `edit`, `glob`, `grep` methods |
| `weebot/domain/models/backend_results.py` | Domain models: `LsResult`, `ReadResult`, `WriteResult`, `EditResult`, `GlobResult`, `GrepResult` |
| `weebot/infrastructure/adapters/sandbox_backend_adapter.py` | `SandboxBackendAdapter(BackendPort)` — implements all methods by delegating to `SandboxPort.execute_shell()` with PowerShell commands |
| `tests/unit/test_backend_port.py` | Contract tests for BackendPort |
| `tests/unit/test_sandbox_backend_adapter.py` | Adapter unit tests |

### 4.4 `BackendPort` ABC

```python
# weebot/application/ports/backend_port.py
class BackendPort(ABC):
    """Unified I/O interface for all filesystem and execution operations."""
    
    @abstractmethod
    async def ls(self, path: str) -> LsResult: ...
    
    @abstractmethod
    async def read(self, file_path: str, offset: int = 0, limit: int = 100) -> ReadResult: ...
    
    @abstractmethod
    async def write(self, file_path: str, content: str) -> WriteResult: ...
    
    @abstractmethod
    async def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> EditResult: ...
    
    @abstractmethod
    async def glob(self, pattern: str, path: str | None = None) -> GlobResult: ...
    
    @abstractmethod
    async def grep(self, pattern: str, path: str | None = None, glob: str | None = None) -> GrepResult: ...
    
    @abstractmethod
    async def execute(self, command: str, timeout: float | None = None) -> ExecuteResult: ...
```

### 4.5 Tool Refactoring

Each tool that currently calls `self._sandbox.execute_shell()` or `subprocess.run()` directly is refactored to call `self._backend.read()` / `self._backend.execute()` instead:

| Tool | Current pattern | New pattern |
|------|----------------|-------------|
| `BashTool` | `self._sandbox.execute_shell(script, shell, timeout, cwd)` | `self._backend.execute(command, timeout)` |
| `PowerShellTool` | `self._sandbox.execute_shell(script, "powershell", timeout)` | `self._backend.execute(command, timeout)` |
| `StrReplaceEditorTool` | Own file read/write logic via `SandboxPort` | `self._backend.read()` + `self._backend.write()` / `self._backend.edit()` |
| `BrowserTool` | Own `_run_browser_task` → subprocess | Unchanged (browser is not a filesystem operation) |

### 4.6 DI Wiring

```python
# weebot/application/di/_factories.py
@staticmethod
def _create_backend() -> BackendPort:
    from weebot.infrastructure.adapters.sandbox_backend_adapter import SandboxBackendAdapter
    sandbox = FactoriesMixin._create_sandbox()
    return SandboxBackendAdapter(sandbox=sandbox)

# weebot/application/di/__init__.py
self.register(BackendPort, self._create_backend)
```

Tools that currently accept `sandbox: SandboxPort` now accept `backend: BackendPort` instead. The constructor signature changes from `__init__(self, sandbox: Optional[SandboxPort] = None)` to `__init__(self, backend: Optional[BackendPort] = None)`.

### 4.7 Architecture Fitness

`test_ports_have_adapters` — `BackendPort` maps to `SandboxBackendAdapter`.  
`test_domain_has_no_outer_imports` — `LsResult`, `ReadResult`, etc. are pure domain models.  
`test_no_circular_imports` — `BackendPort` imports domain only. `SandboxBackendAdapter` imports ports + infrastructure but not tools.

### 4.8 Tests

- `test_backend_port.py` — contract tests: `ls` returns struct with entries/error, `read` returns content with line numbers, `write` returns path, `edit` returns occurrences, `glob` returns matching paths, `grep` returns matches with line numbers
- `test_sandbox_backend_adapter.py` — the adapter translates `read("/f.txt")` → `execute_shell("Get-Content /f.txt")`, `ls("/dir")` → `execute_shell("Get-ChildItem /dir")`, etc.
- `test_semaphore_limits_concurrent` (existing) — phase 2 test must stay green — semaphore gating in ToolCollection is unaffected

### 4.9 Risk: Medium

`BashTool` and `PowerShellTool` constructors change — any code that constructs them directly (e.g., `RoleBasedToolRegistry.create_tool_collection_from_names()`) must be updated to pass `backend` instead of `sandbox`. The `SandboxPort` constructor parameter in `BashTool.__init__` can be kept as a deprecated keyword that wraps itself in `SandboxBackendAdapter` for backward compatibility.

---

## 5. Phase 3 — FilesystemPermission Model

### 5.1 Goal

Replace the 4 separate security layers (`BashGuard`, `ExecApprovalPolicy`, `CommandSecurityAnalyzer`, `bash_security.py`) with a single declarative `FilesystemPermission` model. The existing security layers become fallback-only — called only when no permission rule matches.

### 5.2 New Files

| File | Purpose |
|------|---------|
| `weebot/domain/models/fs_permission.py` | `FilesystemPermission`, `FSOperation` literal type, `PermissionMode` literal type |
| `weebot/application/services/fs_permission_checker.py` | `FSPermissionChecker` — evaluates rules against operations/paths |
| `tests/unit/test_fs_permission.py` | Unit tests |

### 5.3 Domain Models

```python
# weebot/domain/models/fs_permission.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

FSOperation = Literal["read", "write", "execute"]
PermissionMode = Literal["allow", "deny", "interrupt"]

@dataclass(frozen=True)
class FilesystemPermission:
    """A single access rule for filesystem operations.
    
    Paths are glob patterns anchored at the workspace root.
    First-match-wins: rules are evaluated in declaration order.
    """
    operations: list[FSOperation]
    paths: list[str]          # glob patterns, e.g., "**/secrets/**"
    mode: PermissionMode = "allow"
    description: str = ""     # Human-readable reason for audits
    
    def __post_init__(self):
        for p in self.paths:
            if ".." in p:
                raise ValueError(f"Path must not contain '..': {p!r}")
```

### 5.4 `FSPermissionChecker`

```python
# weebot/application/services/fs_permission_checker.py
class FSPermissionChecker:
    """Evaluates FilesystemPermission rules against tool operations."""
    
    def __init__(self, rules: list[FilesystemPermission] | None = None):
        self._rules = rules or []
    
    def check(self, operation: FSOperation, path: str) -> PermissionMode:
        """Return the mode for *operation* on *path*.
        
        First matching rule wins. Returns "allow" if no rule matches.
        """
        import fnmatch
        for rule in self._rules:
            if operation not in rule.operations:
                continue
            if any(fnmatch.fnmatch(path, p) for p in rule.paths):
                return rule.mode
        return "allow"
    
    def filter_paths(self, operation: FSOperation, paths: list[str]) -> list[str]:
        """Remove paths denied by any rule."""
        return [p for p in paths if self.check(operation, p) != "deny"]
```

### 5.5 Integration

Each tool calls `FSPermissionChecker.check()` before executing an operation:

```python
# In BashTool.execute():
permission = self._perm_checker.check("execute", command)
if permission == "deny":
    return ToolResult(error="Permission denied for command")
if permission == "interrupt":
    return ToolResult(error="Command requires user confirmation", data={"awaiting_human": True})
```

The existing `BashGuard`, `ExecApprovalPolicy`, and `CommandSecurityAnalyzer` remain as fallbacks — called only after `FSPermissionChecker` returns `"allow"`.

### 5.6 DI Wiring

```python
# weebot/application/di/_factories.py
@staticmethod
def _create_fs_permission_checker() -> FSPermissionChecker:
    from weebot.domain.models.fs_permission import FilesystemPermission
    # Default rules — safe by default, opt-in for restricted paths
    default_rules = [
        FilesystemPermission(
            operations=["write", "execute"],
            paths=["**/secrets/**", "**/.env", "**/.git/**"],
            mode="deny",
            description="Block modifications to secrets and version control",
        ),
    ]
    return FSPermissionChecker(rules=default_rules)
```

### 5.7 Risk: Low

Additive gate — `"allow"` is the default when no rules match. Existing behavior is preserved. `"interrupt"` mode requires `HumanInTheLoopMiddleware` (Phase 7) to be useful; until then it falls back to `"deny"`.

---

## 6. Phase 4 — DI Wiring Fix for Code Reviewer

### 6.1 Goal

The `code_reviewer` is resolved by constructing a new `Container()` + `configure_defaults()` on every `create_flow()` call [interfaces/factories.py:108-112](weebot/interfaces/factories.py). This wastes connections and is fragile. The `AgentRunner` already holds a reference to `mediator` and `state_repo` — it should also hold the reviewer.

### 6.2 Changes

| File | Change | Lines |
|------|--------|-------|
| `weebot/interfaces/cli/agent_runner.py` | Accept `code_reviewer` in `__init__`, store as `self._code_reviewer` | +3 |
| `weebot/interfaces/factories.py` | Accept `code_reviewer` parameter in `create_flow()`, pass through to `PlanActFlow` | +3, -2 |
| `weebot/application/flows/plan_act_flow.py` | `code_reviewer` already accepted — no change needed | 0 |
| `weebot/interfaces/cli/agent_runner.py` | `_ensure_flow()` passes `self._code_reviewer` to `create_flow()` | +1 |

### 6.3 Risk: None

Moving a DI resolution from function scope to constructor scope. The reviewer is already optional (`None` default). No behavioral change.

---

## 7. Phase 5 — Memory Lifecycle + Retention Automation

### 7.1 Goal

`MemoryLifecycleService` exists [memory_lifecycle_service.py](weebot/application/services/memory_lifecycle_service.py) but is never called. `RetentionAgent` exists [retention_agent.py](weebot/application/agents/retention_agent.py) but only fires in PlanActFlow's `CompletedState` — the 27 "pending" sessions in `weebot_sessions.db` are never reviewed.

Wire `MemoryLifecycleService.classify()` into `PersistentMemoryTool` and run `RetentionAgent` on session load.

### 7.2 Changes

| File | Change | Lines |
|------|--------|-------|
| `weebot/tools/persistent_memory.py` | After `add_memory()`, call `MemoryLifecycleService.classify()` on all entries. Demote HOT→WARM→COLD via `model_copy` | +15 |
| `weebot/interfaces/cli/agent_runner.py` | In `resume_session()`, if session status is `pending` and `updated_at > 24h ago`, run `RetentionAgent.review()` as a background task before resuming | +20 |
| `weebot/application/services/memory_lifecycle_service.py` | Add a `run_cycle(entries)` public method that calls `demote_candidates()` + `enforce_hot_capacity()` and returns updated entries | +8 |

### 7.3 Risk: Low

`RetentionAgent` is fire-and-forget (`asyncio.ensure_future`). `MemoryLifecycleService` is pure computation — no I/O. Both are fail-safe (default to PARK and no-demotion respectively).

---

## 8. Phase 6 — Executor Monolith → Middleware Extraction

### 8.1 Goal

`ExecutorAgent.execute_step()` is ~700 lines handling tool dispatch, trajectory monitoring, policy-error-loop detection, step validation, conversation buffer management, facts extraction, and event logging. Refactor into composable middleware classes.

### 8.2 Architecture

```
┌─────────────────────────────────────────────────────────┐
│ ExecutorAgent (thin orchestrator, ~150 lines)           │
│                                                         │
│  execute_step():                                        │
│    1. Build system prompt + context                     │
│    2. Call LLM via cascade                              │
│    3. For each model response:                           │
│       state = MiddlewareState(messages, tool_calls, ...)│
│       for mw in self._middleware:                       │
│         state = await mw.process(state)  ← NEW          │
│    4. Yield events from state                           │
│    5. Check termination conditions                       │
└─────────────────────────────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
   ┌──────────┐   ┌──────────┐   ┌──────────┐
   │ToolCall  │   │Trajectory│   │PolicyErr │
   │Middleware│   │Middleware│   │Middleware│
   └──────────┘   └──────────┘   └──────────┘
   • Batch      │  • Monitor   │  • Classify
     execute     │  • Diagnose  │    errors
   • Semaphore   │  • Recovery  │  • Detect
   • Event emit  │    message   │    loops
                 │              │  • HITL
                 └──────────────┘    request
```

### 8.3 New Files

| File | Purpose |
|------|---------|
| `weebot/application/middleware/__init__.py` | Public API |
| `weebot/application/middleware/base.py` | `MiddlewareState`, `Middleware` ABC |
| `weebot/application/middleware/tool_dispatch.py` | `ToolDispatchMiddleware` — parallel batch + semaphore |
| `weebot/application/middleware/trajectory.py` | `TrajectoryMiddleware` — monitor → diagnose → recovery injection |
| `weebot/application/middleware/policy_error_loop.py` | `PolicyErrorLoopMiddleware` — error classification + loop detection |
| `weebot/application/middleware/step_validation.py` | `StepValidationMiddleware` — StepResultValidator integration |
| `weebot/application/middleware/facts_extraction.py` | `FactsExtractionMiddleware` — tool result → context facts |
| `weebot/application/middleware/conversation_buffer.py` | `ConversationBufferMiddleware` — message append + compression |
| `tests/unit/middleware/` | Test directory |
| `tests/unit/middleware/test_tool_dispatch.py` | Existing parallel execution tests, refactored |
| `tests/unit/middleware/test_trajectory.py` | Existing trajectory tests, refactored |
| `tests/unit/middleware/test_policy_error_loop.py` | Unit tests |
| `tests/unit/middleware/test_step_validation.py` | Unit tests |

### 8.4 `Middleware` ABC

```python
# weebot/application/middleware/base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

@dataclass
class MiddlewareState:
    """State passed through the middleware chain."""
    conversation_buffer: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[Any] = field(default_factory=list)  # list[ToolResult]
    tool_call_events: list[Any] = field(default_factory=list)
    error_class_counts: dict[str, int] = field(default_factory=dict)
    step_result: str = ""
    facts: dict[str, Any] = field(default_factory=dict)
    should_terminate: bool = False
    abort_step: bool = False
    loop_error: str | None = None
    hitl_paused: bool = False

class Middleware(ABC):
    """A composable step in the tool-call processing pipeline."""
    
    @abstractmethod
    async def process(self, state: MiddlewareState) -> MiddlewareState:
        """Transform *state*. Must return a new or mutated state."""
        ...
```

### 8.5 Refactoring Strategy

The existing `execute_step()` method is refactored by moving each processing block into its own middleware class. The order of middleware in the chain matches the current execution order exactly — no behavioral change:

```python
# In ExecutorAgent.__init__():
self._middleware_chain: list[Middleware] = [
    ToolDispatchMiddleware(tools=self._tools),
    ToolEventMiddleware(event_bus=self._event_bus),
    TrajectoryMiddleware(monitor=self._trajectory_monitor),
    PolicyErrorLoopMiddleware(),
    StepValidationMiddleware(),
    FactsExtractionMiddleware(facts=self._facts),
    ConversationBufferMiddleware(
        buffer=self._conversation_buffer,
        compressor=self._compressor,
    ),
]
```

### 8.6 Tests

Existing test files `test_parallel_tool_execution.py` and `test_trajectory_cross_step.py` are refactored to test middleware classes directly rather than testing through the full `ExecutorAgent`. Tests must pass both before and after refactoring. New tests cover each middleware class in isolation.

### 8.7 Risk: High

This is the largest change. Mitigations:
- Extract one middleware class at a time, verify tests, commit
- Keep the old `execute_step()` method alongside the new chain during migration, toggled by a feature flag (`WEEBOT_USE_MIDDLEWARE=1`)
- `test_parallel_tool_execution.py` must stay green after every extraction

---

## 9. Phase 7 — Sub-Agent Middleware

### 9.1 Goal

Replace the 3 separate sub-agent dispatch mechanisms (`DispatchAgentsTool`, `SwarmTool`, `HyperAgentFlow`) with a single `SubAgentMiddleware` that exposes a `task` tool to the parent agent. The LLM calls `task(description="...", subagent_type="coder")` and the middleware compiles, invokes, and returns the result inline.

### 9.2 New Files

| File | Purpose |
|------|---------|
| `weebot/domain/models/sub_agent_spec.py` | `SubAgentSpec` (already exists — extend with middleware config) |
| `weebot/application/middleware/sub_agent.py` | `SubAgentMiddleware` — registers `task` tool, dispatches to `SubAgentFactoryPort.spawn()` |
| `tests/unit/middleware/test_sub_agent.py` | Unit tests |

### 9.3 Architecture

```
Parent LLM call
  │
  ▼
SubAgentMiddleware.intercept_request(state)
  │
  ├── Injects "task" tool into tool list
  │   task(description: str, subagent_type: Literal["coder","researcher",...])
  │
  ▼
LLM calls task(description="audit security", subagent_type="reviewer")
  │
  ▼
SubAgentMiddleware.intercept_tool_call(tool_call)
  │
  ├── Builds SubAgentSpec from description + type
  ├── Calls SubAgentFactoryPort.spawn(spec)  ← existing
  ├── Waits for SubAgentResult
  ├── Returns result as ToolMessage to parent
  │
  ▼
Parent LLM sees result and continues
```

### 9.4 `SubAgentMiddleware`

```python
class SubAgentMiddleware(Middleware):
    def __init__(self, sub_factory: SubAgentFactoryPort, max_concurrent: int = 4):
        self._factory = sub_factory
        self._max_concurrent = max_concurrent
    
    async def process(self, state: MiddlewareState) -> MiddlewareState:
        # 1. Register "task" tool in the tool list before the LLM call
        # 2. After the LLM call, if any tool_call is "task":
        #    a. Build SubAgentSpec from the call args
        #    b. Call self._factory.spawn(spec)
        #    c. Append result as a tool message to state.conversation_buffer
        # 3. Return updated state
        ...
```

### 9.5 Tool Deprecation

`DispatchAgentsTool` and `SwarmTool` are deprecated (emit `DeprecationWarning`) but remain available for backward compatibility. `HyperAgentFlow` remains for standalone use but is no longer exposed as a tool — the `task` tool replaces it.

### 9.6 Risk: Medium

`SubAgentFactoryPort.spawn()` is already proven. The middleware is additive — existing sub-agent mechanisms continue to work. The risk is in the LLM learning to use the new `task` tool correctly; mitigate with a system prompt addition in the `SubAgentMiddleware` that describes when and how to use `task`.

---

## 10. Phase 8 — DreamerAgent Auto-Pipeline

### 10.1 Goal

`DreamerAgent` surfaces ideas, `IdeaGate` filters them, but `dream scan` only runs manually. Automate the pipeline so ideas are surfaced and approved contracts auto-execute when confidence is high.

### 10.2 Changes

| File | Change | Lines |
|------|--------|-------|
| `weebot/application/flows/states/completed.py` | After `CompletedState` yields `DoneEvent`, run `dream scan` as a background task if `WEEBOT_DREAM_AUTO=1` | +15 |
| `weebot/application/services/trajectory_monitor.py` | In detector #6 (cross-step failure), when 5+ consecutive errors fire, trigger `asyncio.create_task(dream_scan())` — errors are signals for improvement | +8 |
| `cli/commands/dream.py` | `dream scan --auto-build` flag: if set, auto-runs `dream build` for contracts with `heat_score >= 0.8` AND `risk_band != "high"` | +20 |

### 10.3 Auto-build gate

```python
# In dream scan --auto-build:
for contract in approved:
    if contract.heat_score >= 0.8:
        main = await main_reviewer.review(contract, intent)
        if main.risk_band != RiskBand.HIGH:
            asyncio.create_task(_auto_build(contract))
```

### 10.4 Risk: Low

Feature-gated behind `WEEBOT_DREAM_AUTO=1`. Manual `dream scan` unchanged. Auto-build only fires for high-heat, low-risk contracts.

---

## 11. Phase 9 — Harness Profiles

### 11.1 Goal

`ROLE_MODEL_CONFIG` maps roles to models, but every model gets the same tool list and middleware. Extend the config to include per-model tool overrides, excluded tools, and middleware additions — matching Deep Agents' `HarnessProfile` pattern.

### 11.2 Extended Config

```python
# weebot/core/model_cascade_config.py — extended ROLE_MODEL_CONFIG entries

@dataclass
class HarnessProfile:
    """Model-specific configuration for tools, middleware, and prompts."""
    role: str
    models: list[str]                        # primary + fallbacks
    tools_override: list[str] | None = None  # if set, use these tools instead of role defaults
    excluded_tools: list[str] | None = None  # tools to exclude even if role has them
    extra_middleware: list[str] | None = None  # additional middleware class names
    rubric_prompt: str | None = None         # model-specific quality rubric
    system_prompt_append: str | None = None  # appended to executor system prompt

# Updated role config:
ROLE_MODEL_CONFIG: dict[str, HarnessProfile] = {
    "coder": HarnessProfile(
        role="coder",
        models=["deepseek/deepseek-v4-flash", "x-ai/grok-build-0.1", "moonshotai/kimi-k2.6"],
        excluded_tools=["advanced_browser", "image_gen"],
    ),
    "reviewer": HarnessProfile(
        role="reviewer",
        models=["openai/gpt-oss-120b:free", "nousresearch/hermes-3-llama-3.1-405b:free", "x-ai/grok-build-0.1"],
        rubric_prompt="Flag only correctness and security issues. Do not flag style.",
    ),
    # ... others
}
```

### 11.3 Integration

`RoleModelSelector` becomes `HarnessProfileResolver` — returns the full `HarnessProfile` for a role, not just a model ID. `RoleBasedToolRegistry.create_tool_collection()` respects `tools_override` and `excluded_tools`. The executor's middleware chain appends `extra_middleware` after user middleware.

### 11.4 Risk: Low

Backward-compatible — existing `ROLE_MODEL_CONFIG` entries are converted to `HarnessProfile` with default `None` for all new fields. `RoleModelSelector.select()` still works (returns `profile.models[0]`).

---

## 12. Test Plan

### 12.1 New Test Files

| Phase | Test File | Approx. Tests |
|-------|-----------|---------------|
| 1 | `tests/unit/test_quick_wins.py` | 3 |
| 2 | `tests/unit/test_backend_port.py` | 7 |
| 2 | `tests/unit/test_sandbox_backend_adapter.py` | 6 |
| 3 | `tests/unit/test_fs_permission.py` | 8 |
| 5 | `tests/unit/test_memory_lifecycle_integration.py` | 4 |
| 6 | `tests/unit/middleware/test_tool_dispatch.py` | 5 (refactored from existing) |
| 6 | `tests/unit/middleware/test_trajectory.py` | 5 (refactored from existing) |
| 6 | `tests/unit/middleware/test_policy_error_loop.py` | 4 |
| 6 | `tests/unit/middleware/test_step_validation.py` | 4 |
| 7 | `tests/unit/middleware/test_sub_agent.py` | 5 |
| 8 | `tests/unit/test_dream_auto.py` | 3 |
| 9 | `tests/unit/test_harness_profile.py` | 6 |

### 12.2 Regression Gate

After every phase:
```bash
pytest tests/unit/test_architecture_fitness.py -v         # 19 tests must stay green
pytest tests/unit/test_tool_collection_retry.py -v        # 4 tests
pytest tests/unit/test_parallel_tool_execution.py -v      # 5 tests
pytest tests/unit/test_code_reviewer_service.py -v        # 13 tests
pytest tests/unit/test_reviewing_state.py -v              # 9 tests
pytest tests/unit/test_task_preset.py -v                  # 10 tests
pytest tests/unit/test_role_model_selector.py -v          # 6 tests
```

---

## 13. Implementation Order

```
Week 1: Phase 1 (quick wins) + Phase 4 (DI fix) + Phase 3 (permissions)
Week 2: Phase 2 (BackendProtocol) + Phase 5 (memory/retention)
Week 3: Phase 6 (middleware extraction) — largest, highest risk
Week 4: Phase 7 (sub-agent middleware)
Week 5: Phase 8 (auto-pipeline) + Phase 9 (harness profiles)
```

---

## 14. Feature Flags

| Env var | Default | What it gates |
|---------|---------|--------------|
| `WEEBOT_USE_MIDDLEWARE` | `0` | Phase 6 middleware chain (keep old executor path until stable) |
| `WEEBOT_DREAM_AUTO` | `0` | Phase 8 auto-dream pipeline |
| `WEEBOT_PERMISSIONS_STRICT` | `0` | Phase 3 — when set, "interrupt" mode actually pauses; when unset, falls back to "deny" |
| `WEEBOT_BACKEND` | `sandbox` | Phase 2 — which backend adapter to use (future: `docker`, `remote`) |
