# Repository Audit Report

**Codebase:** Weebot AI Agent Framework  
**Audit Date:** 2025-07-21  
**Auditor:** DeepSeek V4 Pro (Principal Architect / Security Auditor / SRE)  
**Repository:** https://github.com/georgehadji/weebot  

---

## Repository Architecture Map

```
weebot/                          # Python backend (Clean Architecture)
├── domain/                      # Pure domain models — zero infra imports
│   ├── models/                  # Session, Plan, Step, Event, etc.
│   ├── services/                # Human interaction, session/working memory
│   ├── exceptions.py            # SecurityException, PathTraversalError, etc.
│   └── ports.py                 # Domain-level event publisher
├── application/                 # Orchestration layer
│   ├── flows/                   # PlanActFlow (state machine), ChatFlow, HyperAgentFlow
│   ├── agents/                  # PlannerAgent, ExecutorAgent, StructuredExecutor
│   ├── cqrs/                    # Mediator, commands, queries, handlers
│   ├── services/                # Plan critic, context switcher, memory, etc.
│   ├── ports/                   # 50+ port interfaces (LLMPort, SandboxPort, etc.)
│   ├── di/                      # Dependency injection container
│   ├── middleware/              # Subagent middleware
│   └── models/                  # ToolCollection, PlanActFlowConfig
├── infrastructure/              # Adapter implementations
│   ├── adapters/llm/            # OpenAI, Anthropic, OpenRouter, DeepSeek adapters
│   ├── persistence/             # SQLite state repo, connection pool, FTS5
│   ├── sandbox/                 # NativeWindows, WSL2, Docker sandboxes
│   ├── security/                # PathValidator, CommandValidator, InputSanitizer
│   ├── cache/                   # LLM response cache
│   ├── mcp/                     # MCP client manager, tool bridge
│   ├── browser/                 # Playwright browser automation
│   ├── observability/           # Prometheus, OpenTelemetry, health checks
│   └── notifications/           # Telegram, Slack, Windows toast
├── interfaces/                  # Entry points
│   ├── web/                     # FastAPI server (main.py + routers)
│   ├── cli/                     # Agent runner, support commands
│   └── gateways/                # Discord, Slack, Telegram
├── mcp/                         # MCP server (FastMCP)
├── tools/                       # Tool implementations (Bash, Python, FileEditor, etc.)
├── config/                      # Settings, constants, model refs
├── core/                        # Cross-cutting (bash_guard, circuit_breaker, errors)
├── scheduling/                  # APScheduler-based job scheduling
└── templates/                   # Adaptive agent templates, hook system

tests/                           # Test suite
├── unit/                        # 60+ unit test files
├── integration/                 # Real API, state manager, security penetration
├── e2e/                         # Portfolio website generation, persistence
├── contracts/                   # Port contract tests
└── smoke/                       # CLI and API contract smoke tests

weebot-ui/                       # Next.js frontend (TypeScript)
├── src/app/                     # Pages (dashboard, sessions, settings, debug)
├── src/components/              # Chat, plan, behavior, session components
├── src/hooks/                   # WebSocket, SSE, event hooks
└── src/lib/                     # API client utilities

cli/                             # CLI entry point (click-based)
├── main.py                      # CLI dispatcher
└── commands/                    # agents, flow, guard, harness, skills, etc.
```

## Technology Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.12, asyncio |
| Web Framework | FastAPI, Starlette |
| Database | SQLite (aiosqlite + synchronous sqlite3) |
| AI Providers | OpenRouter, OpenAI, Anthropic, DeepSeek, Kimi |
| State Management | Custom Clean Architecture + CQRS |
| Frontend | Next.js 14, TypeScript, Tailwind CSS |
| Task Scheduling | APScheduler |
| Testing | pytest, pytest-asyncio, hypothesis |
| Monitoring | Prometheus, OpenTelemetry |
| MCP | FastMCP (Model Context Protocol) |
| Sandbox | Native Windows, WSL2, Docker |

## Key Dependencies

| Dependency | Purpose | Risk |
|-----------|---------|------|
| aiosqlite >=0.20.0 | Async SQLite pool | Low |
| mcp >=1.5 | MCP server protocol | Low |
| playwright >=1.40.0 | Browser automation | Low |
| openai >=1.0.0 | LLM API calls | Medium (API key mgmt) |
| cryptography >=41.0.0 | Secret handling | Low |
| prometheus-client >=0.21.0 | Metrics | Low |
| apscheduler >=3.10 | Background jobs | Low |

## Overall Assessment

**Risk Level: HIGH (mitigated by recent fixes)**

The codebase has strong architectural foundations (Clean Architecture, port/adapter pattern, CQRS). The recently completed audit and remediation cycle addressed 4 critical security flaws, 3 high-priority performance issues, and 2 architectural anti-patterns. 90 new regression and adversarial tests now guard against regression. Remaining work: EventStore async migration, circuit breaker persistence, and PlanActFlow decomposition.
