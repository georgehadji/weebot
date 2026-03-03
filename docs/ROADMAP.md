# 📊 Weebot Development Roadmap

**Last Updated:** 2026-03-03
**Status:** Phases 1-7 Complete | Phase 2 In Progress (draft files exist)
**Last Commit:** `a34110f` — Critical bug fixes (ai_router + agent_factory)

---

## 🎯 Executive Summary

The weebot project is a sophisticated AI Agent Framework for Windows 11 with clean architecture (Hexagonal/Ports & Adapters) and comprehensive autonomous agent capabilities.

| Metric | Value |
|--------|-------|
| **Committed Phases** | 1-7 (100%) |
| **Committed Tests** | 428 passing ✅ |
| **Total Tests (incl. draft files)** | 558 passing |
| **Test Failures** | 32 (pre-existing or in draft files — not regressions) |
| **Known Critical Issues** | 0 — 3 bugs found & fixed in `a34110f` |
| **Draft Files (Phase 2 components)** | 6 core + 4 test files (untracked) |
| **Architecture Style** | Clean/Hexagonal (Ports & Adapters) |

---

## 🏗️ Overall Architecture

The project follows **Clean Architecture** principles with clear separation of concerns:

```
weebot/
├── domain/             # Business logic (models, ports, exceptions)
├── core/              # Core orchestration & agent logic
├── tools/             # Tool implementations (bash, python, browser, etc)
├── mcp/               # MCP server integration
├── config/            # Settings & configuration
├── sandbox/           # Code execution sandbox
├── utils/             # Utility functions & helpers
└── tray.py            # System tray integration
```

Key architectural decisions documented in: `docs/plans/2026-02-28-architecture-design.md`

---

## ✅ COMPLETED PHASES (1-7)

### Phase 1: Computer Use Tools ✅ COMPLETE
- **Status:** Complete
- **Key Features:** Mouse control, keyboard input, OCR, screen capture
- **Files:** `weebot/tools/computer_use.py`, `weebot/tools/screen_tool.py`
- **Tests:** Passing ✅
- **Technologies:** asyncio, mss, Pillow

### Phase 2: Advanced Browser Automation ✅ COMPLETE
- **Status:** Complete
- **Key Features:** Playwright integration, multi-browser support, JS evaluation
- **Files:** `weebot/tools/advanced_browser.py`
- **Tests:** Passing ✅
- **Technologies:** Playwright async

### Phase 3: Scheduling & Cron ✅ COMPLETE
- **Status:** Complete
- **Key Features:** APScheduler, recurring jobs, timezone support
- **Files:** `weebot/tools/scheduler.py`
- **Tests:** Passing ✅
- **Technologies:** APScheduler

### Phase 4: Code Execution ✅ COMPLETE
- **Status:** Complete
- **Commit:** `219f68b`
- **Key Features:** Bash & Python execution, sandboxing, memory monitoring
- **Files:**
  - `weebot/tools/bash_tool.py`
  - `weebot/tools/python_tool.py`
  - `weebot/sandbox/executor.py`
- **Tests:** 24 tests (8 Bash + 8 Python + 8 Sandbox) ✅
- **Technologies:** subprocess, psutil, asyncio

### Phase 5: MCP Server Integration ✅ COMPLETE
- **Status:** Complete
- **Commit:** `034b9be`
- **Key Features:** FastMCP 1.26.0, stdio/SSE transport, resources
- **Files:**
  - `weebot/mcp/server.py`
  - `weebot/mcp/resources.py`
  - `run_mcp.py`
- **Tests:** 29 tests ✅
- **Technologies:** FastMCP, async resources

### Phase 6: Claude Desktop Integration ✅ COMPLETE
- **Status:** Complete
- **Commit:** `0ff93fd`
- **Key Features:** Config template, setup guide
- **Files:**
  - `claude_desktop_config.json.example`
  - `docs/setup/claude-desktop.md`
  - `run_mcp.py`
- **Documentation:** Complete setup guide included

### Phase 7: Multi-Agent Orchestration Foundation ✅ COMPLETE
- **Status:** Complete
- **Commit:** `0ee6ccd`
- **Key Features:** AgentContext, EventBroker, AgentFactory, RoleBasedToolRegistry
- **Files:**
  - `weebot/core/agent_context.py`
  - `weebot/core/agent_factory.py`
  - `weebot/tools/tool_registry.py`
- **Tests:** 20 tests ✅
- **Technologies:** asyncio pub/sub, DAG validation, role-based access

---

## 🛠️ BUG FIXES — Commit `a34110f` (2026-03-03)

Three critical bugs were discovered via epistemic decomposition + Chain of Verification (CoVe) and fixed with 21 new tests. **None were regressions — all pre-existed.**

### Fix 1: Bare `except:` in ModelRouter swallowed `asyncio.CancelledError`
- **File:** `weebot/ai_router.py`
- **Root Cause:** `asyncio.CancelledError` is a `BaseException` subclass in Python ≥3.8. The bare `except:` in the fallback loop caught it, preventing proper task cancellation, `asyncio.wait_for()` timeouts, and graceful shutdown.
- **Fix:** `except:` → `except Exception as fallback_exc:` with warning logging
- **Tests Added:** 3 (cancellation propagates, timeout fires, regular exception still falls back)

### Fix 2: `CostTracker.is_budget_exceeded()` defined but never called
- **File:** `weebot/ai_router.py`
- **Root Cause:** `DAILY_AI_BUDGET` was tracked in `CostTracker.today_cost` but the enforcement gate was never placed in `generate_with_fallback()`. Budget could be exceeded indefinitely.
- **Fix:** Budget guard added at the top of `generate_with_fallback()`, before any API call. Cache hits bypass the check.
- **Tests Added:** 5 (budget blocks API call, passes when under budget, cache bypass, tracker logic, zero budget)

### Fix 3a: Tool name validation only caught empty strings
- **File:** `weebot/core/agent_factory.py`
- **Root Cause:** `[t for t in allowed_tools if not t]` only rejected `""` and `None`. Typos like `"bash_tol"` silently passed validation, only failing at tool call time with an unhelpful error.
- **Fix:** Typos validated against `RoleBasedToolRegistry._build_tool_class_map()` at spawn time.
- **Tests Added:** 5 (valid names accepted, typo raises at spawn, empty/None rejected, role-based bypass)

### Fix 3b: Duplicate roles in `spawn_orchestrator_agents` silently overwrote agents
- **File:** `weebot/core/agent_factory.py`
- **Root Cause:** `spawned[role] = agent` — if two specs shared the same role, the second silently overwrote the first. Lost agents were invisible.
- **Fix:** Duplicate role guard raises `ValueError` before any agent is spawned.
- **Tests Added:** 3 (duplicate raises before spawn, unique roles work, error names the duplicate)

**New test files:**
- `tests/unit/test_ai_router_fixes.py` — 8 tests
- `tests/unit/test_agent_factory_fixes.py` — 8 tests (+ 5 pre-existing in `test_agent_factory.py` corrected)

**Reference:** `docs/PRIORITY_ISSUES_ANALYSIS.md` (v2), `docs/RESILIENCE_AND_DEPLOYMENT.md`

---

## 🟡 PHASE 2 (IN PROGRESS): Multi-Agent Orchestration Engine

**Status:** 🟡 Draft files exist (untracked) — needs integration, finalization, and tests to pass
**Dependencies:** All completed ✅
**Prerequisites:** All Phase 1-7 features stable ✅

> **Note (2026-03-03 codebase audit):** All Phase 2 components already exist as untracked draft files in `weebot/core/`. The work is to finalize, integrate, and commit them with passing tests — not to create them from scratch.

---

### 2.1 WorkflowOrchestrator — 📄 DRAFT EXISTS

**File:** `weebot/core/workflow_orchestrator.py` — untracked draft
**Test:** `tests/unit/test_workflow_orchestrator.py` — untracked draft

**Purpose:** Coordinate multiple agents, manage task graphs, enable parallel execution

**Key Responsibilities:**
- Agent spawning & lifecycle management
- Task dependency resolution (DAG execution)
- Parallel task execution with semaphores
- Result aggregation & state propagation
- Error handling & recovery
- Resource constraint management

**Implementation Strategy:**
- Build on AgentFactory (Phase 7) ✅
- Use asyncio for true parallelism
- Track execution metrics
- Implement backpressure mechanism

**Risks & Mitigations:**
| Risk | Mitigation |
|------|-----------|
| Task graph deadlocks | Cycle detection before execution |
| Resource exhaustion | Semaphores + configured limits |
| Cascading failures | CircuitBreaker pattern (see 2.2) |
| Memory leaks | Proper cleanup in finally blocks |
| Concurrent budget exhaustion | `threading.Lock` on CostTracker (see RESILIENCE doc) |

**Action to finalize:**
1. Review draft, run `pytest tests/unit/test_workflow_orchestrator.py -v`
2. Fix failing tests; add missing coverage
3. Integrate with AgentFactory and EventBroker
4. Commit when 12+ tests pass

```python
from weebot.core.workflow_orchestrator import WorkflowOrchestrator

orchestrator = WorkflowOrchestrator(
    max_parallel_agents=4,
    timeout_per_task=300
)
result = await orchestrator.execute(task_graph)
```

---

### 2.2 CircuitBreaker Pattern — 📄 DRAFT EXISTS (7 tests failing)

**File:** `weebot/core/circuit_breaker.py` — untracked draft
**Test:** `tests/unit/test_circuit_breaker.py` — untracked draft (7 failing)

**Purpose:** Prevent cascading failures, enable graceful degradation

**State Machine:**
```
CLOSED ──[failures ≥ threshold]──> OPEN
  ↑                                 │
  └──[timeout elapsed]──────> HALF_OPEN ──[success]──> CLOSED
                                     │
                                [failure]
                                     └──> OPEN
```

**Key Features:**
- Failure threshold tracking
- Automatic recovery timing
- Fallback strategies
- Metrics collection

**Action to finalize:**
1. `pytest tests/unit/test_circuit_breaker.py -v` — see which 7 tests fail
2. Fix implementation gaps; target 10+ passing tests
3. Integrate with `generate_with_fallback()` (Phase 4 observability gate)

```python
from weebot.core.circuit_breaker import CircuitBreaker, CircuitBreakerConfig

breaker = CircuitBreaker(
    failure_threshold=5,
    recovery_timeout=60,
    name="api_calls"
)
async with breaker:
    result = await potentially_failing_operation()
```

---

### 2.3 ToolResult Enhancement — ✅ ALREADY COMPLETE

**File:** `weebot/tools/base.py` — modified (uncommitted changes)
**Test:** `tests/unit/test_tool_result_enhanced.py` — untracked draft

> **Codebase audit finding:** `weebot/tools/base.py` already contains the enhanced `ToolResult` structure with `success`, `data`, `error_type`, `metadata` (including `execution_time_ms`, `tool_name`, `retry_count`, `timestamp`). This task is complete — needs only to be committed.

**Current Structure (already implemented):**
```python
class ToolResult(BaseModel):
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    metadata: Dict[str, Any] = {}  # execution_time_ms, tool_name, timestamp, retry_count
```

**Action to finalize:**
1. Run `pytest tests/unit/test_tool_result_enhanced.py -v` — verify tests pass
2. Include `weebot/tools/base.py` in the Phase 2 commit

---

### 2.4 Dependency Graph Engine — 📄 DRAFT EXISTS

**File:** `weebot/core/dependency_graph.py` — untracked draft
**Test:** `tests/unit/test_dependency_graph.py` — untracked draft

**Purpose:** Resolve task dependencies, detect cycles, plan execution order

**Capabilities:**
- DAG construction & validation
- Cycle detection (raise error)
- Topological sorting (execution order)
- Critical path analysis
- Visualization (Mermaid/Graphviz)

**Action to finalize:**
1. `pytest tests/unit/test_dependency_graph.py -v` — see current pass rate
2. Fix gaps; target 8+ passing tests

```python
from weebot.core.dependency_graph import DependencyGraph

graph = DependencyGraph({
    "fetch": {"deps": []},
    "process": {"deps": ["fetch"]},
    "analyze": {"deps": ["process"]},
    "report": {"deps": ["analyze"]}
})
graph.validate()           # Raises if cycle detected
order = graph.topological_sort()
critical = graph.critical_path()
mermaid = graph.to_mermaid()
```

---

## Phase 2 Summary

| Component | Status | Files | Tests |
|-----------|--------|-------|-------|
| WorkflowOrchestrator | 📄 Draft (untracked) | `workflow_orchestrator.py` | Draft (untracked) |
| CircuitBreaker | 📄 Draft (7 failing) | `circuit_breaker.py` | Draft (7 failing) |
| ToolResult Enhancement | ✅ Complete (uncommitted) | `tools/base.py` | Draft (untracked) |
| Dependency Graph | 📄 Draft (untracked) | `dependency_graph.py` | Draft (untracked) |

**Definition of Done for Phase 2:**
- [ ] All 4 components committed and tracked
- [ ] 40+ tests passing for Phase 2 components
- [ ] `pytest tests/unit/ -q` shows 0 new failures
- [ ] `examples/06_orchestration_demo.py` runs successfully

---

## 🟡 PHASE 3 (PLANNED): Workflow Templates & Examples

**Status:** Design phase
**Dependency:** Phase 2 Complete
**Purpose:** Provide reusable workflow patterns for common AI tasks

### 3.1 Template Engine
- YAML/JSON workflow definitions
- Parameter substitution & validation
- Output schema validation
- Template versioning & inheritance

### 3.2 Predefined Templates
- Research → Analysis pipeline
- Competitive analysis workflow
- Parallel data processing
- Report generation workflow

### 3.3 Example Scripts
- `examples/06_research_analysis_workflow.py`
- `examples/07_competitive_analysis.py`
- `examples/08_parallel_data_processing.py`
- `examples/09_advanced_multi_agent.py`

---

## 🟢 PHASE 4 (PLANNED): Observability & Monitoring

**Status:** Design phase
**Dependency:** Phase 3 Complete
**Purpose:** Production observability, tracing, metrics, alerting

### 4.1 Structured Logging
**File:** `weebot/structured_logger.py` (untracked draft exists)
- JSON-formatted logs
- Correlation IDs across agents
- Performance tracking per tool
- Error categorization & stacks

### 4.2 Workflow Tracing
**File:** `weebot/core/workflow_tracer.py` (NEW)
- Agent execution timeline
- Tool call tracing with timing
- Decision point logging
- Error propagation tracking

### 4.3 Metrics Dashboard
**File:** `weebot/core/dashboard.py` (NEW)
- Agent performance metrics
- Tool usage statistics
- Success/failure rates
- Response time analytics (p99 latency thresholds: warn >10s, critical >30s)
- Resource utilization

### 4.4 Alert System
**File:** `weebot/core/alerting.py` (NEW)
- Threshold-based alerts (see runtime monitor parameters in `docs/RESILIENCE_AND_DEPLOYMENT.md`)
- Performance degradation detection
- Error spike detection

---

## 🏗️ Draft Files — Current Integration Status

| File | Purpose | Status | Target Phase |
|------|---------|--------|-------------|
| `weebot/core/workflow_orchestrator.py` | Core orchestration engine | 📄 Draft (untracked) | Phase 2 |
| `weebot/core/circuit_breaker.py` | Failure prevention | 📄 Draft (7 tests failing) | Phase 2 |
| `weebot/core/dependency_graph.py` | DAG task ordering | 📄 Draft (untracked) | Phase 2 |
| `weebot/tools/base.py` | Enhanced ToolResult | ✅ Done (uncommitted) | Phase 2 |
| `weebot/core/agent_context_final.py` | AgentContext v3 | 📄 Draft (untracked) | Phase 2 |
| `weebot/core/agent_profile.py` | Agent profiling & analytics | 📄 Draft (untracked) | Phase 4 |
| `weebot/security_validators.py` | Security checks | 📄 Draft (untracked) | Phase 2 |
| `weebot/error_system_base.py` | Error handling | 📄 Draft (untracked) | Phase 3 |
| `weebot/error_system_handler.py` | Error processing | 📄 Draft (untracked) | Phase 3 |
| `weebot/error_system_user_messages.py` | User-friendly errors | 📄 Draft (untracked) | Phase 3 |
| `weebot/structured_logger.py` | JSON logging | 📄 Draft (untracked) | Phase 4 |
| `weebot/utils/rate_limiter.py` | Rate limiting | 📄 Draft (untracked) | Phase 2 |

---

## 📊 Dependency Graph

```
Phase 1 ✅ Computer Use
    ↓
Phase 2 ✅ Browser Automation
    ↓
Phase 3 ✅ Scheduling
    ↓
Phase 4 ✅ Code Execution
    ↓
Phase 5 ✅ MCP Server
    ↓
Phase 6 ✅ Claude Desktop
    ↓
Phase 7 ✅ Multi-Agent Foundation
    ↓
🛠️  Bug Fixes ✅ (commit a34110f)
    ↓
Phase 2* (NEW) 🟡 Orchestration Engine (DRAFT FILES EXIST)
├─ WorkflowOrchestrator (draft → finalize)
├─ CircuitBreaker (draft → fix 7 failing tests)
├─ ToolResult Enhancement ✅ (complete, uncommitted)
└─ Dependency Graph (draft → finalize)
    ↓
Phase 3* (NEW) 🟡 Workflow Templates (design phase)
├─ Template Engine
└─ 4 Example Scripts
    ↓
Phase 4* (NEW) 🟢 Observability (design phase)
├─ Structured Logger (draft exists)
├─ Workflow Tracing (new)
├─ Metrics Dashboard (new)
└─ Alert System (new)
```

---

## ⚠️ Known Issues & Risks

### Fixed Issues (not blocking)
- ✅ `asyncio.CancelledError` swallowed in fallback loop → **FIXED** (`a34110f`)
- ✅ Budget enforcement absent → **FIXED** (`a34110f`)
- ✅ Tool name typos pass validation → **FIXED** (`a34110f`)
- ✅ Duplicate roles silently overwrite → **FIXED** (`a34110f`)

### Pre-existing Failures (not regressions, not blocking Phase 2)
| Test File | Count | Reason |
|-----------|-------|--------|
| `test_circuit_breaker.py` | 7 | Draft implementation gaps |
| `test_file_editor.py` | 8 | Known pre-existing failures |
| `test_settings.py` | 2 | Missing API keys in test env |
| `test_event_broker_resilience.py` | 1 | Draft/stress test |
| `test_tool_registry.py` | 1 | Registry mismatch |
| Others | ~13 | Various draft test files |

### Residual Known Risks
| ID | Risk | Severity | Mitigation |
|----|------|----------|-----------|
| R1 | Race window in concurrent budget check | LOW | GIL-safe; add `threading.Lock` in Phase 2 |
| R2 | `ResponseCache` file writes not atomic | LOW | Windows `write_text()` non-atomic; add in Phase 4 |
| R3 | `None` project_id silently keyed in ActivityStream | LOW | Add `assert project_id` in Phase 2 hardening |
| R4 | StateManager no timeout on `run_in_executor` | LOW | Add `asyncio.wait_for(..., timeout=30)` in Phase 4 |

**Rollback Threshold:** Any critical metric sustained > 2 minutes, OR deployment doubles error rate within 5 minutes. See `docs/RESILIENCE_AND_DEPLOYMENT.md` for full recovery plans.

### Critical Path
1. **Phase 2 CircuitBreaker** → Blocks Orchestrator stability
2. **Phase 2 Orchestrator** → Blocks Phase 3 templates
3. **Phase 3 Templates** → Blocks Phase 4 observability

---

## 📅 Timeline (Dependency-Based)

**Phase 2:** Now — draft files exist, need finalization and passing tests
**Phase 3:** After Phase 2 Orchestrator is tested and committed
**Phase 4:** After Phase 3 examples work

---

## 🚀 Getting Started with Phase 2

### Prerequisites
- [x] All Phase 1-7 tests passing (428 committed ✅)
- [x] Bug fixes committed (`a34110f` ✅)
- [x] Draft files already exist (no need to create from scratch)

### Step-by-Step Execution

**Step 1: Assess draft files**
```bash
# Run all Phase 2 draft tests to see current state
pytest tests/unit/test_workflow_orchestrator.py -v
pytest tests/unit/test_circuit_breaker.py -v
pytest tests/unit/test_dependency_graph.py -v
pytest tests/unit/test_tool_result_enhanced.py -v
```

**Step 2: Fix CircuitBreaker (7 failing tests)**
```bash
# Inspect failures
pytest tests/unit/test_circuit_breaker.py -v --tb=short
# Edit draft
code weebot/core/circuit_breaker.py
# Re-run until green
pytest tests/unit/test_circuit_breaker.py -v
```

**Step 3: Finalize WorkflowOrchestrator**
```bash
code weebot/core/workflow_orchestrator.py
pytest tests/unit/test_workflow_orchestrator.py -v
# Target: 12+ tests passing
```

**Step 4: Finalize DependencyGraph**
```bash
code weebot/core/dependency_graph.py
pytest tests/unit/test_dependency_graph.py -v
# Target: 8+ tests passing
```

**Step 5: Commit Phase 2**
```bash
git add weebot/core/workflow_orchestrator.py \
        weebot/core/circuit_breaker.py \
        weebot/core/dependency_graph.py \
        weebot/tools/base.py \
        tests/unit/test_workflow_orchestrator.py \
        tests/unit/test_circuit_breaker.py \
        tests/unit/test_dependency_graph.py \
        tests/unit/test_tool_result_enhanced.py \
        examples/06_orchestration_demo.py
pytest tests/unit/ -q  # Verify no new failures
git commit -m "feat: Phase 2 — Multi-Agent Orchestration Engine"
```

**Step 6: Verify Completion**
```bash
pytest tests/unit/ -v  # Should have 470+ tests passing
git log --oneline | head -5
```

---

## 🔗 Related Documentation

- **Architecture:** `docs/plans/2026-02-28-architecture-design.md`
- **Phase 4 Plan:** `docs/plans/2026-03-01-phase4-code-execution.md`
- **Project Memory:** `MEMORY.md`
- **System Knowledge Map:** `docs/SYSTEM_KNOWLEDGE_MAP.md` ← new v2
- **Priority Issues Analysis:** `docs/PRIORITY_ISSUES_ANALYSIS.md` ← new v2
- **Resilience & Deployment:** `docs/RESILIENCE_AND_DEPLOYMENT.md` ← new
- **Production Summary:** `docs/FINAL_PRODUCTION_SUMMARY.md`
- **Security Fixes:** `docs/SECURITY_FIXES_SUMMARY.md`
- **Multi-Agent README:** `weebot/core/README_MULTI_AGENT.md`

---

**Document Status:** ✅ Active
**Last Review:** 2026-03-03 — full codebase audit vs roadmap
**Next Review:** Upon Phase 2 completion
**Maintainer:** Weebot Development Team
