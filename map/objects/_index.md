# Object index

One line per noun. Lines marked `stub` have no card and make no behavior claim: they are addresses read on 2026-10-21, not facts about behavior. Lines marked `verified` link to a card.

Format: `name` — `path:line` — status

## domain
- Plan (with PlanStatus, PlanCritique) — `weebot/domain/models/plan.py:154` — verified 2026-10-23 — [card](domain/Plan.md)
- Step (with StepStatus, ContextScope) — `weebot/domain/models/plan.py:53` — verified 2026-10-23 — [card](domain/Step.md)
- PlanCritique — `weebot/domain/models/plan.py:124` — in the [Plan card](domain/Plan.md)
- Session (with SessionContext, Fact) — `weebot/domain/models/session.py:201` — verified 2026-10-23 — [card](domain/Session.md)
- SessionContext / Fact — `weebot/domain/models/session.py:52` — in the [Session card](domain/Session.md)
- Event (BaseEvent / AgentEvent union, DomainEvent) — `weebot/domain/models/event.py:34` — verified 2026-10-23 — [card](domain/Event.md)
- Ports (ABC/Protocol, 73 interfaces) — `weebot/application/ports/` — verified 2026-10-23 — [card](domain/Ports.md)

## application
- PlanActFlow — `weebot/application/flows/plan_act_flow.py:73` — verified 2026-10-21 — [card](application/PlanActFlow.md)
- FlowRouter — `weebot/application/flows/flow_router.py:25` — verified 2026-10-21 — [card](application/FlowRouter.md)
- FlowState (state classes) — `weebot/application/flows/states/base.py:55` — verified 2026-10-21 — [card](application/FlowState.md)
- PlannerAgent — `weebot/application/agents/planner.py:77` — verified 2026-10-21 — [card](application/PlannerAgent.md)
- ExecutorAgent — `weebot/application/agents/executor/_base.py:197` — verified 2026-10-21 — [card](application/ExecutorAgent.md)
- CascadeExecutor — `weebot/application/agents/executor/_cascade.py:38` — verified 2026-10-21 — [card](application/CascadeExecutor.md)
- Mediator (CQRS) — `weebot/application/cqrs/mediator.py:37` — verified 2026-10-21 — [card](application/Mediator.md)
- DI Container — `weebot/application/di/__init__.py:72` — verified 2026-10-21 — [card](application/DIContainer.md)
- SkillRegistry — `weebot/application/skills/skill_registry.py:27` — verified 2026-10-23 — [card](application/SkillRegistry.md)

## infrastructure
- SQLiteStateRepository — `weebot/infrastructure/persistence/sqlite_state_repo.py:44` — verified 2026-10-21 — [card](infrastructure/SQLiteStateRepository.md)
- LLM adapters (factory + resilience layer) — `weebot/infrastructure/adapters/llm/` — verified 2026-10-21 — [card](infrastructure/LLMAdapters.md)
- Event store (audit journal) — `weebot/infrastructure/event_store.py:93` — verified 2026-10-21 — [card](infrastructure/EventStore.md)
- Event bus (AsyncEventBus, DurableEventBus, Valkey) — `weebot/infrastructure/event_bus.py:43,180`, `weebot/infrastructure/events/redis_event_bus.py:24` — verified 2026-10-21 — [card](infrastructure/EventBus.md)
- Sandbox (port, factory, Native/WSL2/Docker backends) — `weebot/infrastructure/sandbox/factory.py:38` — verified 2026-10-21 — [card](infrastructure/Sandbox.md)
- Browser adapter and session pool — `weebot/infrastructure/browser/playwright_adapter.py:25` — verified 2026-10-23 — [card](infrastructure/Browser.md)

## interfaces
- CLI — `cli/main.py:132` — verified 2026-10-23 — [card](interfaces/CLI.md)
- Web API (FastAPI) — `weebot/interfaces/web/main.py:392` — verified 2026-10-23 — [card](interfaces/WebAPI.md)
- Chat gateways — `weebot/interfaces/gateways/base.py:77` — verified 2026-10-23 — [card](interfaces/ChatGateways.md)
- MCP server (WeebotMCPServer) — `weebot/mcp/server.py:109` — verified 2026-10-23 — [card](interfaces/MCPServer.md)
- Web UI — `weebot-ui/src/lib/api.ts:91` — verified 2026-10-23 — [card](interfaces/WebUI.md)

## core
- BashGuard / RiskLevel (+ shell-tool gate chain) — `weebot/core/bash_guard.py:48` — verified 2026-10-21 — [card](core/BashGuard.md)
- EgressGuard — `weebot/core/egress_guard.py:237` — verified 2026-10-21 — [card](core/EgressGuard.md)
- ExecApprovalPolicy — `weebot/core/approval_policy.py:200` — verified 2026-10-21 — [card](core/ExecApprovalPolicy.md)
- CommandSecurityAnalyzer (4-layer shell analyzer) — `weebot/tools/bash_security.py:43` — verified 2026-10-21 — [card](core/CommandSecurityAnalyzer.md)
- ApprovalManager (tool-call grant store since ADR-013; was a ghost prompt layer) — `weebot/core/approval.py` — stale 2026-10-22 — [card](core/ApprovalManager.md)
- Model cascade config (catalog cost estimate and context-size switch, not the cascade driver) — `weebot/core/model_cascade_config.py` — verified 2026-10-23 — [card](core/ModelCascadeConfig.md)
- WeebotSettings — `weebot/config/settings.py:36` — verified 2026-10-21 — [card](core/WeebotSettings.md)

## tools
- RoleBasedToolRegistry — `weebot/tools/tool_registry.py:15` — stale 2026-10-23 (line numbers drifted; collection code now `:406-514`) — [card](tools/RoleBasedToolRegistry.md)
- BaseTool / ToolResult / ToolCollection (tool contract, dispatch, guard and approval path) — `weebot/domain/models/base_tool.py:20` — verified 2026-10-23 — [card](tools/BaseTool.md)
- Exec tools (bash, powershell, python_execute, file_editor, secure_output, validation) — `weebot/tools/bash_tool.py:37` — verified 2026-10-23 — [card](tools/ExecTools.md)
- Web tools (web_search, spacescraper, moli_fetch, vane_search, agent_reach, search_images, knowledge, search_history, weather, ocr) — `weebot/tools/web_search.py:28` — verified 2026-10-23 — [card](tools/WebTools.md)
- Browser and desktop tools — `weebot/tools/advanced_browser.py:55` — verified 2026-10-23 — [card](tools/BrowserTools.md)
- Orchestration tools (debate, swarm, dispatch, workflow, MoA, reasoner, berb, control, todo, schedule, memory, audit) — `weebot/tools/dispatch_agents.py:26` — verified 2026-10-23 — [card](tools/OrchestrationTools.md)
- Integration tools (atomic_mail, apify_*, product, design_system, external MCP) — `weebot/interfaces/factories.py:348` — verified 2026-10-23 — [card](tools/IntegrationTools.md)
- Media tools (image_gen, video_gen, video_ingest, remotion_video, voice_in/out, youtube_download) — `weebot/tools/image_gen_tool.py:255` — verified 2026-10-23 — [card](tools/MediaTools.md)
- Built-in skills (data) — `weebot/application/skills/skill_registry.py:48` — verified 2026-10-23 — [card](tools/BuiltinSkills.md)
- Personas (AgentPersona) — `weebot/agents/models.py:46` — verified 2026-10-23 — [card](tools/Personas.md)

## flagged
- weebot/osworld — leftover — `weebot/osworld/`
