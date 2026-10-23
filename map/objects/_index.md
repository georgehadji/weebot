# Object index

One line per noun. Lines marked `stub` have no card and make no behavior claim: they are addresses read on 2026-10-21, not facts about behavior. Lines marked `verified` link to a card.

Format: `name` — `path:line` — status

## domain
- Plan — `weebot/domain/models/plan.py:154` — stub
- Step (with StepStatus, ContextScope) — `weebot/domain/models/plan.py:53` — stub
- PlanCritique — `weebot/domain/models/plan.py:124` — stub
- Session — `weebot/domain/models/session.py:201` — stub
- SessionContext / Fact — `weebot/domain/models/session.py:52` — stub
- Event (BaseEvent, PlanEvent, ErrorEvent) — `weebot/domain/models/event.py:34` — stub
- Ports (ABC) — `weebot/application/ports/` (one file per port) — stub

## application
- PlanActFlow — `weebot/application/flows/plan_act_flow.py:73` — verified 2026-10-21 — [card](application/PlanActFlow.md)
- FlowRouter — `weebot/application/flows/flow_router.py:25` — verified 2026-10-21 — [card](application/FlowRouter.md)
- FlowState (state classes) — `weebot/application/flows/states/base.py:55` — verified 2026-10-21 — [card](application/FlowState.md)
- PlannerAgent — `weebot/application/agents/planner.py:77` — verified 2026-10-21 — [card](application/PlannerAgent.md)
- ExecutorAgent — `weebot/application/agents/executor/_base.py:197` — verified 2026-10-21 — [card](application/ExecutorAgent.md)
- CascadeExecutor — `weebot/application/agents/executor/_cascade.py:38` — verified 2026-10-21 — [card](application/CascadeExecutor.md)
- Mediator (CQRS) — `weebot/application/cqrs/mediator.py:37` — verified 2026-10-21 — [card](application/Mediator.md)
- DI Container — `weebot/application/di/__init__.py:72` — verified 2026-10-21 — [card](application/DIContainer.md)
- SkillRegistry — `weebot/application/skills/skill_registry.py:27` — stub

## infrastructure
- SQLiteStateRepository — `weebot/infrastructure/persistence/sqlite_state_repo.py:44` — verified 2026-10-21 — [card](infrastructure/SQLiteStateRepository.md)
- LLM adapters (factory + resilience layer) — `weebot/infrastructure/adapters/llm/` — verified 2026-10-21 — [card](infrastructure/LLMAdapters.md)
- Event store (audit journal) — `weebot/infrastructure/event_store.py:93` — verified 2026-10-21 — [card](infrastructure/EventStore.md)
- Event bus (AsyncEventBus, DurableEventBus, Valkey) — `weebot/infrastructure/event_bus.py:43,180`, `weebot/infrastructure/events/redis_event_bus.py:24` — verified 2026-10-21 — [card](infrastructure/EventBus.md)
- Sandbox (port, factory, Native/WSL2/Docker backends) — `weebot/infrastructure/sandbox/factory.py:38` — verified 2026-10-21 — [card](infrastructure/Sandbox.md)
- Browser adapter and session pool — `weebot/infrastructure/browser/` — stub

## interfaces
- CLI — `cli/main.py` and `cli/commands/` — stub
- Web API (FastAPI) — `weebot/interfaces/web/main.py` — stub
- Chat gateways — `weebot/interfaces/gateways/` — stub
- MCP server (WeebotMCPServer) — `weebot/mcp/server.py:109` — stub
- Web UI — `weebot-ui/` — stub

## core
- BashGuard / RiskLevel (+ shell-tool gate chain) — `weebot/core/bash_guard.py:48` — verified 2026-10-21 — [card](core/BashGuard.md)
- EgressGuard — `weebot/core/egress_guard.py:237` — verified 2026-10-21 — [card](core/EgressGuard.md)
- ExecApprovalPolicy — `weebot/core/approval_policy.py:200` — verified 2026-10-21 — [card](core/ExecApprovalPolicy.md)
- CommandSecurityAnalyzer (4-layer shell analyzer) — `weebot/tools/bash_security.py:43` — verified 2026-10-21 — [card](core/CommandSecurityAnalyzer.md)
- ApprovalManager (tool-call grant store since ADR-013; was a ghost prompt layer) — `weebot/core/approval.py` — stale 2026-10-22 — [card](core/ApprovalManager.md)
- Model cascade config (catalog cost estimate and context-size switch, not the cascade driver) — `weebot/core/model_cascade_config.py` — verified 2026-10-23 — [card](core/ModelCascadeConfig.md)
- WeebotSettings — `weebot/config/settings.py:36` — verified 2026-10-21 — [card](core/WeebotSettings.md)

## tools
- RoleBasedToolRegistry — `weebot/tools/tool_registry.py:15` — verified 2026-10-21 — [card](tools/RoleBasedToolRegistry.md)
- Tools (bash, python, browser, file_editor, atomic_mail, ...) — `weebot/tools/` — stub
- Built-in skills (data) — `weebot/skills/builtin/` — stub
- Personas (AgentPersona) — `weebot/agents/models.py:46` — stub

## flagged
- weebot/osworld — leftover — `weebot/osworld/`
