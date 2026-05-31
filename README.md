# Weebot — Production-Ready AI Agent Framework

[![Tests](https://img.shields.io/badge/tests-1,100%2B%20passing-success)](https://github.com/yourusername/weebot/actions)
[![Version](https://img.shields.io/badge/version-2.7.0-blue)](VERSION)
[![Status](https://img.shields.io/badge/status-Production%20Ready-green)](docs/PROJECT_FINAL_SUMMARY.md)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](.python-version)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Enterprise-grade AI Agent Framework** with Clean Architecture, CQRS/event-driven orchestration, structured output protocols, multi-model cascading, secure sandboxed execution, and self-evolving agent skills via SkillOpt.

[Documentation](docs/) • [Quick Start](#quick-start) • [Architecture](#architecture) • [Testing](#testing) • [Roadmap](#roadmap)

---

## Overview

Weebot is a sophisticated AI agent framework designed for production deployments on Windows 11. It combines **Clean Architecture (Hexagonal)** with **CQRS** and **event-driven** orchestration, advanced reliability features, bash safety guardrails, model cascading for cost optimization, and comprehensive observability. The codebase has been through a complete forensic architecture audit with all 3 critical findings resolved.

### Key Design Principles

- **Clean Architecture:** Domain → Application → Infrastructure → Interfaces with strict dependency direction (verified by automated fitness tests)
- **CQRS + Event-Driven:** All write operations flow through `mediator.send()` with pipeline behaviours (logging, validation, telemetry)
- **Single Composition Root:** `application/di.py` is the only place infrastructure adapters are created
- **Self-Evolving Skills:** SkillOpt optimizer loop enables automatic skill improvement from trajectory evidence
- **Reliability First:** Structured output protocols eliminate ambiguity; circuit breakers prevent cascading failures
- **Security by Default:** Multi-layer bash safety with 40+ attack pattern detectors
- **Cost Optimization:** FREE→Budget→Premium model cascading reduces costs by 60-80%
- **Observability:** Complete event logging with cost tracking and audit trails

---

## Features

### Core Capabilities

| Feature | Description | Status |
|---------|-------------|--------|
| **Clean Architecture** | Domain → Application → Infrastructure → Interfaces | ✅ Production |
| **CQRS + Mediator** | 14 commands, 9 queries with pipeline behaviours | ✅ Production |
| **Event-Driven** | 19 event types streaming through unified event bus | ✅ Production |
| **Self-Evolving Skills** | SkillOpt optimizer with validation gate (paper §3.5) | ✅ Production |
| **Structured Output Protocol** | Mandatory JSON output with Pydantic validation | ✅ Production |
| **Bash Safety Guardrails** | 40+ security patterns; 4-tier risk classification | ✅ Production |
| **Model Cascading** | Automatic FREE→Budget→Premium fallback | ✅ Production |
| **Event Logging** | SQLite-based audit trail with cost tracking | ✅ Production |
| **Validation Pipeline** | Pre-execution code validation (syntax, imports, tests) | ✅ Production |
| **Response Caching** | L1 (memory) + L2 (SQLite) tiered caching | ✅ Production |
| **Multi-Model Routing** | 58+ models via OpenRouter with cost optimization | ✅ Production |
| **Secure Execution** | Sandboxed Bash/Python with timeout & memory limits | ✅ Production |
| **Browser Automation** | Playwright with session pooling | ✅ Production |
| **MCP Server** | Claude Desktop integration with dynamic tools | ✅ Production |
| **Web Dashboard** | Next.js 14 UI with real-time monitoring | ✅ Production |
| **Knowledge Graph** | Graphify-powered architecture visualization | ✅ graphify-out/ |

### Architecture Quality Gates

| Gate | Enforcement | Verified |
|------|-------------|----------|
| **Dependency direction inward** | Domain imports nothing from outer layers | ✅ Fitness test |
| **CQRS for writes** | Every mutation through `mediator.send()` | ✅ Fitness test |
| **Port/adapter for I/O** | 11 ports with concrete adapters in infrastructure/ | ✅ All present |
| **DI composition root** | `application/di.py` is single wiring hub | ✅ Fitness test |
| **Immutable domain models** | All models use `model_copy(update=…)` | ✅ Static analysis |
| **Architecture fitness tests** | CI gate prevents regression | ✅ 5 tests in CI |

### Reliability & Performance

- **Circuit Breaker Pattern:** Automatic failure detection with cooldown recovery
- **Connection Pooling:** SQLite WAL mode with async connection pooling
- **Adaptive Concurrency:** Dynamic worker scaling based on CPU/memory load
- **Memory Monitoring:** Automatic GC triggers and backpressure handling
- **Health Checks:** Component monitoring with JSON output for monitoring systems

---

## Quick Start

### Installation

```bash
# Clone repository
git clone https://github.com/yourusername/weebot.git
cd weebot

# Install dependencies
pip install -r requirements.txt

# Configure environment
copy .env.example .env
# Edit .env with your API keys (OpenRouter recommended for cascading)
```

### Health Check

```bash
# Check system health
python -m cli.main health

# JSON output for monitoring systems
python -m cli.main health --json
```

### Flow Commands (CQRS-backed)

```bash
# Run a task with PlanActFlow and structured output
python -m cli.main flow run "Analyze this codebase for security issues"

# List active/waiting sessions
python -m cli.main flow list

# Resume a waiting session (HITL)
python -m cli.main flow resume <session_id> "Yes, proceed with the fix"

# Cancel a running session
python -m cli.main flow cancel <session_id>

# View session logs with cost breakdown
python -m cli.main logs show <session_id>
```

### SkillOpt — Self-Evolving Skills

```bash
# Run a skill optiization epoch
python -m cli.main skill optimize <skill_name> --epochs 4 --train-tasks <task_list>

# Transfer a skill to a different model/harness
python -m cli.main skill transfer <skill_name> --target-model gpt-5.4-mini

# Export best validated skill
python -m cli.main skill export <skill_name>
```

See [docs/plans/SKILLOPT_IMPLEMENTATION_PLAN.md](docs/plans/SKILLOPT_IMPLEMENTATION_PLAN.md) for details.

### Interactive Mode

```bash
# Start interactive REPL with rich UI
python run.py --interactive

# With specific model tier
python run.py --interactive --model anthropic/claude-sonnet-4
```

### MCP Server (Claude Desktop)

```bash
# Run MCP server with dynamic tools
python run_mcp.py --mcp-config mcp_servers.json

# With SSE transport for remote access
python run_mcp.py --transport sse --port 8765
```

### Web UI Dashboard

```bash
# Terminal 1: Start backend API
python -m weebot.interfaces.web.main

# Terminal 2: Start frontend
cd weebot-ui
npm run dev

# Access: http://localhost:3000
```

**Dashboard Features:**
- Real-time chat with WebSocket streaming
- Session management with cost tracking
- Plan visualization (ReactFlow)
- Code editor (Monaco) with syntax highlighting
- System metrics and observability panels

---

## Architecture

```
weebot/
├── domain/                            # Business logic (innermost layer)
│   ├── models/                       # Plan, Step, Session, Skill, SkillEdit, TrajectorySummary, AgentEvent, DomainEvent
│   └── services/                     # HumanInteractionService, WorkingMemory, SessionMemory
├── application/                      # Use cases and orchestration
│   ├── cqrs/                        # Mediator, 14 commands, 9 queries, 17 handlers, pipeline behaviours
│   ├── flows/                       # PlanActFlow (6 states), SkillOptFlow (epoch loop)
│   ├── agents/                      # PlannerAgent, ExecutorAgent, StructuredExecutorAgent, OptimizerAgent
│   ├── services/                    # TaskRunner, TrajectoryBuilder, ValidationRunner, LearningRateScheduler
│   ├── ports/                       # 11 ports: LLMPort, EventBusPort, StateRepositoryPort, ScoringPort, OptimizerPort …
│   └── di.py                        # Single composition root (DI container)
├── infrastructure/                  # External adapters
│   ├── adapters/                    # LLM adapters (OpenAI, Anthropic, DeepSeek, OpenRouter) with resilient wrapper
│   ├── persistence/                 # SQLiteStateRepository, SkillStore, TrajectoryRepository, LegacyProjectAdapter
│   ├── events/                      # AsyncEventBus, EventBrokerAdapter
│   ├── scoring/                     # ExactMatchScorer, ExecutionResultScorer, VerifierScorer
│   ├── cache/                       # L1 Memory + L2 SQLite caching
│   ├── browser/                     # PlaywrightAdapter with session pooling
│   ├── sandbox/                     # NativeWindows, WSL2, Docker
│   ├── notifications/               # WindowsToast, Telegram, SSE
│   └── observability/               # Health checks, metrics
├── interfaces/                      # Delivery mechanisms
│   ├── cli/                         # AgentRunner with rich UI
│   ├── web/                         # FastAPI + WebSocket (6 router modules)
│   └── factories.py                 # FlowFactory, ToolkitFactory
├── tools/                           # Agent function-calling tools (20 tools)
├── models/                          # Structured output models
│   └── structured_output.py         # WeebotOutput, CodeChange, BashCommand
├── core/                            # Shared utilities
│   ├── bash_guard.py                # Security pattern detection (40+ patterns)
│   ├── circuit_breaker.py           # Resilience wrapper
│   ├── approval.py                  # Approval workflow
│   └── behavior_tracker.py          # Session-level behavior tracking
├── tests/                           # 123 test files (64 unit, 4 integration, 3 e2e, 52+ architecture)
└── graphify-out/                    # Knowledge graph of architecture
    ├── graph.html                   # Interactive HTML visualization
    ├── graph.json                   # Raw graph data (8,105 nodes, 27,480 edges)
    └── GRAPH_REPORT.md              # Audit report with god nodes and communities
```

**Dependency Rule:** Dependencies point inward. Domain knows nothing of outer layers — verified by automated CI fitness tests.

See [docs/plans/ENHANCEMENT_PROPOSALS.md](docs/plans/ENHANCEMENT_PROPOSALS.md) for the full architecture audit findings and enhancement roadmap.

---

## Architecture Audit & Remediation

The codebase underwent a complete forensic architecture reconstruction (May 2026), uncovering and resolving:

### Findings Resolved

| Finding | Severity | Resolution |
|---------|----------|------------|
| **CQRS write path bypassed** | CRITICAL | Handlers now execute agents directly and return serialized events; flow states consume from mediator result |
| **Two parallel event buses** | CRITICAL | EventBrokerAdapter bridges `EventBroker` → `AsyncEventBus`; single `EventPublisher` protocol |
| **Two parallel persistence systems** | CRITICAL | LegacyProjectAdapter wraps StateRepositoryPort; StateManager references replaced |
| **Web routes create dependencies inline** | MEDIUM | FastAPI Depends + Container from DI composition root |
| **No ScoringPort implementation** | MEDIUM | 3 adapters: ExactMatchScorer, ExecutionResultScorer, VerifierScorer |
| **CQRS commands use dataclasses** | LOW | Migrated to Pydantic BaseModel with `ConfigDict(frozen=True)` |
| **Step status set after execution** | HIGH | BUG-005 fixed: RUNNING state set before mediator/agent call |
| **Terminate detection broken in mediator path** | HIGH | BUG-009 fixed: signals reconstructed from serialized events |
| **Model switch after plan creation** | MEDIUM | BUG-010 fixed: model switching before any execution |

### Enhancement Roadmap

| # | Enhancement | Effort | Status |
|---|-------------|--------|--------|
| 1 | CQRS execution delegates | 3d | ✅ Complete |
| 2 | Event bus unification | 2d | ✅ Complete |
| 3 | Legacy StateManager replacement | 1d | ✅ Complete |
| 4 | Web router DI | 1d | ✅ Complete |
| 5 | Real ScoringPort | 2d | ✅ Complete |
| 6 | SkillOpt component tests | 4d | ✅ Complete (102 tests) |
| 7 | Pydantic commands | 1d | ✅ Complete |
| 8 | Cross-model transfer | 2d | 📋 Planned |
| 9 | Architecture fitness tests | 0.5d | ✅ Complete |
| 10 | Flat module classification | 3d | 📋 Planned |

See [docs/plans/ENHANCEMENT_PROPOSALS.md](docs/plans/ENHANCEMENT_PROPOSALS.md) for detailed proposals.

---

## SkillOpt — Self-Evolving Agent Skills

Integration of the SkillOpt paper (Yang et al., arXiv:2605.23904v2) enables automatic skill improvement from execution trajectories:

**Pipeline (Figure 2):**
1. **Rollout** — run target model on training tasks with current skill
2. **Reflection** — optimizer analyses failures and successes (parallel minibatch)
3. **Merge** — 3-stage hierarchical merge (failure priority)
4. **Rank** — score by expected utility, clip to budget
5. **Validate** — held-out selection split gate (ties rejected)
6. **Accept/Reject** — accept only if validation score strictly improves
7. **Slow Update** — epoch-boundary longitudinal comparison for protected section

**Key properties:**
- **No inference overhead** — deployed artifact is just `best_skill.md`
- **Harness-agnostic** — same optimizer for direct chat, Codex, Claude Code
- **Cross-model transfer** — Codex-trained skill improves GPT-5.4 by +60.7 points (paper)
- **Compact output** — 1–4 accepted edits per optimization (300–2,000 tokens)

**Test coverage:** 102 unit/integration tests across 8 test files.

```
docs/plans/
├── SKILLOPT_IMPLEMENTATION_PLAN.md      # Full 6-phase, 9-week plan
└── ENHANCEMENT_PROPOSALS.md             # 10 proposals from architecture audit
```

---

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage report
pytest tests/ --cov=weebot --cov-report=html

# Run architecture fitness tests (CI gate)
pytest tests/unit/test_architecture_fitness.py -v

# Run SkillOpt component tests
pytest tests/unit/domain/test_skill_edit.py -v
pytest tests/unit/domain/test_skill_optimization.py -v
pytest tests/unit/application/test_lr_scheduler.py -v
pytest tests/unit/application/test_validation_runner.py -v
pytest tests/unit/application/test_executing_regression.py -v

# Run CQRS handler tests
pytest tests/integration/test_integration_skill_edit.py -v

# Run specific component tests
pytest tests/unit/models/test_structured_output.py -v
pytest tests/unit/core/test_bash_guard.py -v
pytest tests/unit/infrastructure/test_event_store.py -v

# Run integration tests
pytest tests/integration/ -v

# Run E2E tests
pytest tests/e2e/ -v
```

**Test Status:** 1,100+ passing, 102 new SkillOpt tests, 3 regression tests (BUG-005/009/010), ~90% coverage on new code ✅

---

## Knowledge Graph

Weebot's architecture is available as a navigable knowledge graph:

```
graphify-out/
├── graph.html         # Interactive HTML (open in browser)
├── graph.json         # Raw graph data (16 MB, 8,105 nodes, 27,480 edges)
└── GRAPH_REPORT.md    # Audit report with community analysis
```

**Top 10 God Nodes (highest degree):**

| Node | Degree | Type |
|------|--------|------|
| WorkflowTemplate | 382 | Data model |
| Built-in workflow templates (doc bridge) | 316 | Documentation |
| ToolResult | 256 | Data model |
| PlannedTask | 249 | Data model |
| WorkflowPlan | 237 | Data model |
| TemplateRegistry | 223 | Service |
| TemplateEngine | 220 | Service |
| StateRepositoryPort | 217 | Boundary port |
| TemplateParser | 216 | Service |
| AdaptiveSuggestionEngine | 213 | Service |

---

## Configuration

### Environment Variables

```bash
# Required: API key for LLM access
OPENROUTER_API_KEY=sk-or-v1-...

# Optional: Optimizer model for SkillOpt
OPTIMIZER_MODEL=anthropic/claude-sonnet-4

# Optional: Default model
DEFAULT_MODEL=openrouter/auto

# Optional: Safety settings
AUTO_APPROVE_SAFE=true
BLOCKED_COMMANDS=rm -rf /,format C:

# Optional: Cache settings
CACHE_L1_TTL=3600
CACHE_L2_TTL=86400
```

### YAML Config File

Create `~/.weebot/config.yaml`:

```yaml
llm:
  default_model: "openrouter/auto"
  optimizer_model: "anthropic/claude-sonnet-4"
  use_cascade: true
  max_cost_per_task: 0.50

safety:
  auto_approve_safe: true
  require_approval_for: ["dangerous"]
  blocked_commands: ["rm -rf /", "format C:"]

skillopt:
  epochs: 4
  steps_per_epoch: 5
  batch_size: 40
  minibatch_size: 8
  initial_budget: 8
  floor_budget: 2
  schedule: "cosine"

cache:
  l1_ttl: 3600
  l2_ttl: 86400
  max_l1_entries: 1000

ui:
  theme: "auto"
  show_progress: true
  show_cost: true
```

---

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1-10 | ✅ | Core framework, multi-agent, web UI |
| **Phase 11** | ✅ | **Reliability & Cost Optimization** |
| Phase 11.1 | ✅ | Structured Output Protocol |
| Phase 11.2 | ✅ | Bash Safety Guardrails |
| Phase 11.3 | ✅ | Event Logging System |
| Phase 11.4 | ✅ | Model Cascading |
| Phase 11.5 | ✅ | Validation Pipeline |
| Phase 11.6 | ✅ | Response Caching |
| **Architecture Audit** | ✅ | **Forensic reconstruction + 10 enhancement proposals** |
| Enhancement #1 | ✅ | CQRS execution delegates |
| Enhancement #2 | ✅ | Event bus unification |
| Enhancement #3 | ✅ | Legacy StateManager |
| Enhancement #4 | ✅ | Web router DI |
| Enhancement #5 | ✅ | Real ScoringPort |
| Enhancement #6 | ✅ | 102 SkillOpt tests |
| Enhancement #7 | ✅ | Pydantic commands |
| Enhancement #9 | ✅ | Architecture fitness tests |
| Enhancement #8 | 🔄 | Cross-model transfer (planned) |
| Enhancement #10 | 🔄 | Flat module classification (planned) |
| Phase 12 | 📋 | Plugin System |
| Phase 13 | 📋 | Multi-agent coordination enhancements |

---

## Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature/amazing-feature`
3. Run architecture fitness tests: `pytest tests/unit/test_architecture_fitness.py -v`
4. Run SkillOpt tests: `pytest tests/unit/domain/ tests/unit/application/ -v`
5. Commit changes: `git commit -m 'Add amazing feature'`
6. Push to branch: `git push origin feature/amazing-feature`
7. Open Pull Request

### Development Guidelines

- Follow Clean Architecture dependency rules (verified by CI fitness tests)
- All state mutations go through `mediator.send(Command)` — no direct agent calls in flow states
- Domain models use Pydantic `BaseModel` with `model_copy(update=…)` — never mutate in place
- Infrastructure imports in the application layer use `TYPE_CHECKING` guards or lazy imports
- Add tests for new functionality (target 80%+ coverage)
- Update documentation for public API changes
- Run regression tests before committing

---

## License

MIT License — see [LICENSE](LICENSE) file.

---

## Acknowledgments

- [SkillOpt](https://arxiv.org/abs/2605.23904v2) — Self-evolving agent skills (Yang et al., Microsoft)
- [Pydantic](https://docs.pydantic.dev/) — Data validation
- [Playwright](https://playwright.dev/) — Browser automation
- [FastMCP](https://github.com/modelcontextprotocol/python-sdk) — MCP server
- [Rich](https://rich.readthedocs.io/) — Terminal formatting
- [Next.js](https://nextjs.org/) — React framework
- [shadcn/ui](https://ui.shadcn.com/) — UI components
- [Graphify](https://github.com/safishamsi/graphify) — Knowledge graph extraction

---

**Version:** 2.7.0  
**Last Updated:** 2026-05-28
