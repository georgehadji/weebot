# Implementation Plan — Four Major Features · Weebot v2.9–3.0

**Date:** 2026-05-28  
**Derived from:** Architecture audit + enhancement roadmap (docs/plans/ENHANCEMENT_PROPOSALS.md)  
**Features:** Pre-built Chatbot · Cross-Model Skill Transfer (#8) · Plugin System (Phase 12) · Flat Module Classification (#10)

---

## Table of Contents

1. [Codebase Reconnaissance](#1-codebase-reconnaissance)
2. [Feature 1 — Pre-built Chatbot](#2-feature-1--pre-built-chatbot)
3. [Feature 2 — Cross-Model Skill Transfer (#8)](#3-feature-2--cross-model-skill-transfer-8)
4. [Feature 3 — Plugin System (Phase 12)](#4-feature-3--plugin-system-phase-12)
5. [Feature 4 — Flat Module Classification (#10)](#5-feature-4--flat-module-classification-10)
6. [Dependency Order & Sprint Schedule](#6-dependency-order--sprint-schedule)
7. [Risk Register](#7-risk-register)
8. [Architecture Compliance](#8-architecture-compliance)

---

## 1. Codebase Reconnaissance

### What already exists (relevant to these features)

| What | Where | Maturity |
|------|-------|----------|
| PlanActFlow state machine (6 states) | `application/flows/plan_act_flow.py` | ✅ Production |
| SkillOptFlow epoch loop | `application/flows/skill_opt_flow.py` | ✅ Production |
| WebSocket streaming + session management | `interfaces/web/` | ✅ Production |
| Next.js 14 frontend | `weebot-ui/` | ✅ Production |
| CQRS mediator with pipeline behaviours | `application/cqrs/mediator.py` | ✅ Production |
| OptimizerAgent (reflect/merge/rank/slow update) | `application/agents/optimizer_agent.py` | ✅ Production |
| SkillStore (versioned skills) | `infrastructure/persistence/skill_store.py` | ✅ Production |
| 338-model registry from OpenRouter | `application/services/model_selection.py` | ✅ Updated |
| Transfer commands/handlers placeholder | `application/cqrs/commands/__init__.py` | 🔲 Placeholder only |
| 41 flat modules in `weebot/*.py` | `weebot/` | ⚠️ Mix of dead/alive |
| No dedicated chat flow or state | `application/flows/` | ❌ Missing |

### What's missing

- **Chat flow** — no `ChatFlow(BaseFlow)` or chat state exists. The web UI has a bare WebSocket test page, not a proper chat UX.
- **Transfer commands** — only a placeholder `__init__.py` docstring mentions "transfer." No `ValidateTransferCommand`, no handler, no CLI.
- **Plugin system** — entirely greenfield. No plugin loading, lifecycle management, or sandboxing.
- **Flat module cleanup** — no migration guide. 13 dead files (0 references), 27 alive files with 1–16 callers each.

---

## 2. Feature 1 — Pre-built Chatbot

### Objective

Ship a conversational chatbot accessible via web UI and CLI that shares the infrastructure of PlanActFlow (same LLMPort, event bus, CQRS mediator, session persistence, WebSocket streaming) but uses a simpler conversation loop instead of plan-act-update state transitions.

### Design

#### Chatbot Data Flow

```
User message (CLI or Web)
  → ChatFlow.run(prompt)
    [State Machine Loop]
    → ChatMessageState.execute()
      → mediator.send(ProcessMessageCommand)       [CQRS delegate — see below]
        → ProcessMessageHandler.handle()            [handler owns the agent call]
          → ChatAgent.respond(message, history)     via LLMPort
          → returns CommandResult.data["events"]    [serialised MessageEvents]
      → ChatMessageState yields events from result  [consumed by flow]
      → Displayed in UI via WebSocket bridge
    → IdleState (wait for next user input)
      → if user responds: → ChatMessageState
      → if timeout/no response: → Done
```

**CQRS delegate pattern (matching Enhancement #1):** `ProcessMessageHandler`
calls `ChatAgent.respond()` internally and returns the serialised events in
`CommandResult.data["events"]`.  The flow state consumes the events from the
mediator result without calling the agent directly.  If no mediator is
configured, the flow falls back to the direct-agent-call path — identical to how
`PlanningState`/`ExecutingState`/`UpdatingState` work in `plan_act_flow.py`.```

#### New Components

| Component | Layer | Purpose |
|-----------|-------|---------|
| `ChatFlow(BaseFlow)` | `application/flows/chat_flow.py` | Conversational flow with 2 states |
| `ChatMessageState(FlowState)` | `application/flows/states/` | Single-turn message processing |
| `IdleState(FlowState)` | `application/flows/states/` | Wait-for-next-message state |
| `ChatAgent` | `application/agents/chat_agent.py` | Conversation agent using LLMPort directly |
| `ProcessMessageCommand` | `application/cqrs/commands.py` | New CQRS command |
| `ProcessMessageHandler` | `application/cqrs/handlers.py` | Chat-specific handler |
| `ChatRequest`, `ChatResponse` | `interfaces/web/schemas/` | REST API schemas |
| `POST /api/chat`, `GET /api/chat/{session_id}` | `interfaces/web/routers/` | New REST endpoints |
| `WebSocket /ws/chat/{session_id}` | `interfaces/web/main.py` | Real-time streaming endpoint |
| `chat_send` CLI subcommand | `cli/main.py` | CLI chat interface |

#### Observability — Chat Domain Events

New domain events emitted through the unified event bus (matched to the
existing `PlanEvent`/`StepEvent` observable surface for PlanActFlow):

| Event | Fields | When emitted |
|-------|--------|-------------|
| `ChatSessionStarted` | session_id, model, first_message | On first `ProcessMessageCommand` success |
| `ChatMessageProcessed` | session_id, model, input_tokens, output_tokens, latency_ms, cost | After each LLM response |
| `ChatSessionEnded` | session_id, total_messages, total_tokens, total_cost | On flow transition to Done |

These are `DomainEvent` subclasses in `domain/models/event.py`.  The
existing `EventStore` + `LoggingBehavior` pipeline records them without
any new infrastructure.  The web UI cost counter reads from these events.

```python
class ChatMessageProcessed(DomainEvent):
    type: str = "chat_message_processed"
    session_id: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost: float
```

#### ChatFlow vs PlanActFlow

| Aspect | PlanActFlow | ChatFlow |
|--------|-------------|----------|
| States | 6 (Planning→Executing→Updating→Summarizing→Completed) | 2 (ChatMessage→Idle) |
| Agent | PlannerAgent + ExecutorAgent | ChatAgent |
| Tool use | Full tool loop with loop detection | Tool use optional, simpler loop |
| Plan creation | Structured JSON plan required | No plan — straight conversation |
| Loop detection | Step repetition + tool call patterns | Message length/drift only |
| HITL | WaitForUserEvent | Built-in (every turn is user input) |
| Max iterations | 50 plan-act steps | 500 message exchanges |
| Persistence | Session + Plan events | Session + Message events only |
| Model switching | Context-aware (token-based) | Tiered by message count |

#### Web UI Integration

The existing `weebot-ui/` needs two new pages:

1. **Chat page** (`/chat`) — input box, message history, streaming display, model selector dropdown, cost counter
2. **Session list page** (`/chat/sessions`) — list of previous chat sessions with resume button

Both use the existing WebSocket infrastructure for real-time streaming and React components from the dashboard.

#### CLI Integration

```bash
# Start a chat session
python -m cli.main chat start "I'm building a FastAPI app..."

# Continue an existing chat session
python -m cli.main chat resume <session_id> "What should I do next?"

# List chat sessions
python -m cli.main chat list

# Chat with specific model
python -m cli.main chat start --model anthropic/claude-sonnet-4.6 "Explain this error"
```

#### Files Created (13 new, 5 modified)

**New:**
```
application/flows/chat_flow.py
application/flows/states/chat_message.py
application/flows/states/idle.py
application/agents/chat_agent.py
interfaces/web/schemas/chat_schemas.py
interfaces/web/routers/chat_router.py
tests/unit/application/test_chat_flow.py
tests/unit/application/test_chat_agent.py
tests/unit/application/test_chat_message_state.py
tests/integration/test_chat_integration.py
weebot-ui/src/app/chat/
weebot-ui/src/app/chat/sessions/
weebot-ui/src/components/chat/
```

**Modified:**
```
application/cqrs/commands.py        (+ProcessMessageCommand)
application/cqrs/handlers.py        (+ProcessMessageHandler)
application/di.py                   (+configure_chat, +build_chat_flow)
interfaces/web/main.py              (+ /ws/chat/{session_id} + chat_router)
interfaces/factories.py             (+create_chat_flow)
cli/main.py                         (+chat subcommand)
```

#### Estimated Effort: 4–5 days

| Phase | Days | Deliverable |
|-------|------|-------------|
| ChatAgent + ChatFlow | 2d | Working chat via CLI, CQRS wired |
| REST + WebSocket endpoints | 1d | Chat accessible via web API |
| Web UI chat page | 1d | Streaming chat UX in weebot-ui |
| Tests + integration | 1d | 15+ tests, chat→session lifecycle |

---

## 3. Feature 2 — Cross-Model Skill Transfer (#8)

### Objective

Enable skills optimized on one (model, harness) pair to be evaluated on different pairs without retraining. Implement the paper's deployment story: a skill trained on Codex transfers to GPT-5.4-mini with positive gains.

### Background

The SkillOpt paper demonstrated (Table 4):
- Codex-trained spreadsheet skill → Claude Code: +59.7 points
- GPT-5.4-trained OlympiadBench skill → omni-MATH: positive gain without retraining

The infrastructure for this feature already exists from Phases 1–5:
- `SkillStore` loads/saves versioned skills
- `TrajectoryRepository` stores scored trajectories per session
- `ValidationRunner` evaluates candidate skills on held-out tasks
- `OptimizerAgent` has all 6 reflection/merge/rank/slow-update methods

What's missing is the _transfer evaluation loop_ — the ability to take a `best_skill.md`, change the LLM adapter and harness scorer, run validation tasks, and report the score delta.

### Design

#### Transfer Evaluation Pipeline

```
Skill transfer CLI invocation
  → ValidateTransferCommand
    → ValidateTransferHandler
      1. Load skill from SkillStore (e.g., spreadsheet_skill v3)
      2. Create target LLM adapter (e.g., gpt-5.4-mini)
      3. Create target ScoringPort (e.g., claude_code scorer)
      4. Build no-skill baseline flows (run validation tasks without any skill)
         → average baseline_score
      5. Build skill-augmented flows (create flows that inject skill content as system prompt)
         → run same validation tasks
         → average transfer_score
      6. Compute Δ = transfer_score - baseline_score
      7. Store result in Skill.transfer_scores[f"{target_model}:{target_harness}"]
      8. Yield TransferEvaluated domain event
```

#### New Components

| Component | Layer | Purpose |
|-----------|-------|---------|
| `ValidateTransferCommand` | `application/cqrs/commands/transfer_commands.py` | Carry target model + harness + skill_name |
| `ValidateTransferHandler` | `application/cqrs/handlers/transfer_handler.py` | Execute the transfer evaluation |
| `TransferResult` (value object) | `domain/models/skill.py` | Transfer result stored in Skill model |
| `transfer_scores: dict[str, TransferResult]` | `domain/models/skill.py` | Field on Skill |
| `TransferEvaluated(DomainEvent)` | `domain/models/event.py` | Emitted after evaluation |
| `skill transfer` CLI subcommand | `cli/main.py` | CLI entry point |
| `create_transfer_runner()` | `interfaces/factories.py` | Factory for transfer flow |

#### Skill Model Extension

```python
class TransferResult(BaseModel):
    target_model: str          # e.g., "openai/gpt-5.4-mini"
    target_harness: str        # e.g., "direct_chat" | "codex" | "claude_code"
    baseline_score: float      # no-skill baseline on target
    transfer_score: float      # score with transferred skill
    delta: float               # transfer_score - baseline_score
    n_tasks: int               # number of validation tasks run
    latency_s: float = 0.0     # wall-clock time for the full evaluation
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Skill(BaseModel):  # existing model, extended
    # ... existing fields ...
    transfer_scores: dict[str, TransferResult] = Field(
        default_factory=dict,
        description="Transfer evaluation results keyed by 'model_id:harness'"
    )
```

#### CLI Interface

```bash
# Transfer a skill to a specific target
python -m cli.main skill transfer spreadsheet_skill \
    --target-model openai/gpt-5.4-mini \
    --target-harness direct_chat \
    --validation-tasks tasks/validation/spreadsheet_bench.jsonl

# Output:
# Skill: spreadsheet_skill v3 (optimized on anthropic/claude-sonnet-4.6 @ codex)
# Transfer to openai/gpt-5.4-mini @ direct_chat:
#   No-skill baseline: 22.1
#   Transferred score: 82.8
#   Δ: +60.7 points ✅ (stored in skill.transfer_scores)

# Transfer to multiple targets at once
python -m cli.main skill transfer-all spreadsheet_skill \
    --targets targets.jsonl \
    --validation-tasks tasks/validation/spreadsheet_bench.jsonl
```

#### How the transfer handler works (internals)

```python
class ValidateTransferHandler(CommandHandler):
    # flow_factory is injected by DI — it MUST NOT import from interfaces/.
    # The factory signature is: Callable[[Session, str | None], BaseFlow]
    def __init__(
        self,
        skill_store: SkillStore,
        state_repo: StateRepositoryPort,
        task_runner: TaskRunner,
        flow_factory: Callable,              # injected, not imported
    ):
        self._skill_store = skill_store
        self._state_repo = state_repo
        self._task_runner = task_runner
        self._create_flow = flow_factory

    async def handle(self, cmd: ValidateTransferCommand) -> CommandResult:
        import asyncio, time
        t0 = time.monotonic()

        skill = await self._skill_store.load(cmd.skill_name)
        if not skill:
            return fail("Skill not found")

        # Phase 1: baseline (no-skill) — runs in parallel
        async def run_baseline(task):
            session = Session(..., context={})  # no skill_content
            flow = self._create_flow(
                session=session, model=cmd.target_model,
                harness=cmd.target_harness, skill_content=None,
            )
            return await self._run_and_score(session, flow, task)

        baseline_scores = await asyncio.gather(*[
            run_baseline(t) for t in cmd.validation_tasks
        ])

        # Phase 2: with skill — runs in parallel
        skill_content = skill.export_best()
        async def run_transfer(task):
            session = Session(..., context={"skill_content": skill_content})
            flow = self._create_flow(
                session=session, model=cmd.target_model,
                harness=cmd.target_harness, skill_content=skill_content,
            )
            return await self._run_and_score(session, flow, task)

        transfer_scores = await asyncio.gather(*[
            run_transfer(t) for t in cmd.validation_tasks
        ])

        elapsed_s = time.monotonic() - t0
        avg_baseline = sum(baseline_scores) / len(baseline_scores) if baseline_scores else 0.0
        avg_transfer = sum(transfer_scores) / len(transfer_scores) if transfer_scores else 0.0
        delta = avg_transfer - avg_baseline

        # Store result
        key = f"{cmd.target_model}:{cmd.target_harness}"
        skill = skill.model_copy(update={
            "transfer_scores": {
                **skill.transfer_scores,
                key: TransferResult(
                    target_model=cmd.target_model,
                    target_harness=cmd.target_harness,
                    baseline_score=avg_baseline,
                    transfer_score=avg_transfer,
                    delta=delta,
                    n_tasks=len(cmd.validation_tasks),
                    latency_s=elapsed_s,
                ).model_dump()
            }
        })
        await self._skill_store.save(skill)

        return CommandResult.ok(data={
            "skill_name": cmd.skill_name,
            "target": f"{cmd.target_model}@{cmd.target_harness}",
            "baseline": avg_baseline,
            "transfer": avg_transfer,
            "delta": delta,
            "latency_s": elapsed_s,
            "n_tasks": len(cmd.validation_tasks),
        })
```

#### Files Created (4 new, 3 modified)

**New:**
```
application/cqrs/commands/transfer_commands.py   (+ValidateTransferCommand)
application/cqrs/handlers/transfer_handler.py     (+ValidateTransferHandler)
tests/unit/application/test_transfer_handler.py   (8 tests)
tests/integration/test_transfer_integration.py    (2 tests)
```

**Modified:**
```
domain/models/skill.py              (+TransferResult model, +transfer_scores field)
domain/models/event.py              (+TransferEvaluated DomainEvent)
cli/main.py                         (+skill transfer, skill transfer-all subcommands)
```

#### Estimated Effort: 2 days

| Day | Deliverable |
|-----|-------------|
| Day 1 | TransferResult model, handler, command, CLI subcommand |
| Day 2 | Tests, validation-task runner integration, integration smoke test |

---

## 4. Feature 3 — Plugin System (Phase 12)

### Objective

A plugin architecture that allows third-party tools, skills, and adapters to be loaded dynamically without modifying weebot core. Plugins are self-contained Python packages with a manifest. They can contribute: tools, skills, adapters, CLI commands, web routes, and flow states.

### Design Principles

1. **Clean Architecture compliant** — plugins are loaded in the infrastructure layer and registered through the DI container. Domain models never reference plugins.
2. **CQRS-wired** — plugin-provided commands go through the existing mediator, not a separate dispatch path.
3. **Safe by default** — plugins are sandboxed (import-level isolation, capability-based permissions, optional Docker execution). No `eval()` or dynamic imports without manifest opt-in.
4. **Discoverable** — plugin metadata is stored in the existing SQLite database alongside skills and trajectories.

### Plugin Manifest

Each plugin is a directory or zip with `plugin.toml` at the root:

```toml
[plugin]
name = "weebot-slack"
version = "1.0.0"
author = "Acme Corp"
description = "Slack integration for Weebot"
min_weebot_version = "2.8.0"

[capabilities]
tools = true            # plugin provides BaseTool subclasses
skills = true           # plugin provides skill documents
adapters = true         # plugin provides port adapters (LLM, state, etc.)
cli_commands = true     # plugin adds CLI subcommands
web_routes = true       # plugin adds FastAPI routes
flow_states = true      # plugin adds FlowState classes
events = false          # plugin listens to event bus
sandbox = "isolated"    # "shared" | "isolated" | "docker"

[sandbox]
allowed_imports = ["weebot.application.ports", "weebot.domain.models", "requests", "slack_sdk"]
network = true          # plugin can make network calls
filesystem = "ro"       # "none" | "ro" | "rw" (relative to plugin dir)
max_memory_mb = 256
timeout_seconds = 30

[commands]
# Plugin-provided CQRS commands (registered with mediator)
send_slack_message = "weebot_slack.commands.SendSlackMessageCommand"
post_slack_thread = "weebot_slack.commands.PostSlackThreadCommand"

[queries]
list_slack_channels = "weebot_slack.queries.ListSlackChannelsQuery"

[handlers]
send_slack_message_handler = "weebot_slack.handlers.SendSlackMessageHandler"

[routes]
# FastAPI router to mount under /api/plugins/slack/
router = "weebot_slack.web:router"

[tools]
# Tool classes to register with ToolRegistry
post_message = "weebot_slack.tools:PostMessageTool"
read_channel = "weebot_slack.tools:ReadChannelTool"

[skills]
# Skill documents to register with SkillRegistry
slack_usage = "weebot_slack/skills/slack_usage.md"
slack_security = "weebot_slack/skills/slack_security.md"

[cli]
# CLI subcommand group
command = "slack"
entry = "weebot_slack.cli:register_commands"
```

#### Plugin Signature Verification

For production trust, plugins distributed outside the core repository
can optionally declare a checksum and public key URL:

```toml
[signature]
method = "sha256"
checksum = "8d9e3f2a1b7c..."
public_key_url = "https://acme.com/weebot-plugins.pub"
```

`PluginManager.validate()` checks the checksum after loading the plugin
package but before importing any code.  Verification is **mandatory**
for `shared` sandbox plugins and **opt-in** for `isolated`/`docker`.

#### Observability — Plugin Lifecycle Events

New domain events emitted for auditability:

| Event | Fields | When emitted |
|-------|--------|-------------|
| `PluginDiscovered` | plugin_name, version, manifest_path | On scan finding a plugin.toml |
| `PluginEnabled` | plugin_name, version, capabilities, sandbox_level | After successful activation |
| `PluginDisabled` | plugin_name, version, reason | On deactivation or unload |
| `PluginLoadFailed` | plugin_name, error, sandbox_level | On validation or load failure |

These go through the existing `EventBusPort` → `EventStore` pipeline
with no new infrastructure needed.

```python
class PluginEnabled(DomainEvent):
    type: str = "plugin_enabled"
    plugin_name: str
    version: str
    capabilities: list[str]
    sandbox_level: str
```
```

### Plugin Lifecycle

```
1. DISCOVER    Scan plugin directories for plugin.toml
2. VALIDATE    Check min_weebot_version, capability conflicts, manifest schema
3. LOAD        Import the plugin package with capability-restricted import hooks
4. REGISTER    Register tools, skills, adapters, commands with the DI container
5. ACTIVATE    Plugin receives on_activate() callback
6. SERVE       Plugin is live — its tools are available, routes mounted, etc.
7. DEACTIVATE  Plugin receives on_deactivate() callback on shutdown
8. UNLOAD      (Optional) Hot-unload without restart
```

### New Components

| Component | Layer | Purpose |
|-----------|-------|---------|
| `PluginManager` | `infrastructure/plugins/manager.py` | Discovery, validation, loading, registration |
| `PluginManifest` | `infrastructure/plugins/manifest.py` | Pydantic model for plugin.toml |
| `PluginLoader` | `infrastructure/plugins/loader.py` | Capability-restricted import with sandbox |
| `PluginSandbox` | `infrastructure/plugins/sandbox.py` | Import-level isolation (allowed/disallowed imports) |
| `PluginLifecycle` | `infrastructure/plugins/lifecycle.py` | activate/deactivate callbacks |
| `PluginStore` | `infrastructure/persistence/plugin_store.py` | SQLite table for plugin metadata + state |
| `PluginPort` | `application/ports/plugin_port.py` | Abstract interface |
| `ListPluginsQuery` | `application/cqrs/queries.py` | Query→handler for plugin listing |
| `{Enable,Disable}PluginCommand` | `application/cqrs/commands.py` | Commands for lifecycle control |
| `plugin` CLI group | `cli/main.py` | `plugin list`, `plugin install`, `plugin enable`, `plugin disable` |
| `PluginRouter` | `interfaces/web/routers/plugin_router.py` | REST API for plugin management |
| Plugin directory structure | `plugins/` in project root | Default plugin search path |

### Sandbox Model

Three isolation levels:

| Level | Import Restriction | Network | Filesystem | Process |
|-------|-------------------|---------|------------|---------|
| `shared` | Full access to weebot internals | Yes | Plugin dir only | Same process |
| `isolated` | Allowlist-based import (manifest.allowed_imports) | Manifest opt-in | Read-only | Same process |
| `docker` | Container-based isolation | Manifest opt-in | Mounted volume | Separate container |

Default: `isolated`. Plugin authors opt into broader access by setting `sandbox = "shared"`.

### CLI Interface

```bash
# Install a plugin from PyPI
python -m cli.main plugin install weebot-slack

# Install from local directory
python -m cli.main plugin install ./my-custom-plugin

# List installed plugins
python -m cli.main plugin list
# Name              Version  Status    Capabilities
# weebot-slack      1.0.0    enabled   tools, skills, routes
# weebot-database   0.2.1    disabled  tools

# Enable/disable
python -m cli.main plugin enable weebot-slack
python -m cli.main plugin disable weebot-database

# Inspect a plugin
python -m cli.main plugin inspect weebot-slack
```

### Files Created (12 new, 3 modified)

**New:**
```
infrastructure/plugins/__init__.py
infrastructure/plugins/manager.py                 # PluginManager core
infrastructure/plugins/manifest.py                # PluginManifest Pydantic model
infrastructure/plugins/loader.py                  # PluginLoader + import sandbox
infrastructure/plugins/sandbox.py                 # PluginSandbox
infrastructure/plugins/lifecycle.py               # PluginLifecycle
infrastructure/persistence/plugin_store.py        # PluginStore
application/ports/plugin_port.py                  # PluginPort ABC
interfaces/web/routers/plugin_router.py           # REST plugin management
tests/unit/infrastructure/test_plugin_manager.py  # 12 tests
tests/unit/infrastructure/test_plugin_sandbox.py  # 6 tests
tests/integration/test_plugin_integration.py      # 2 tests (install→load→unload)
```

**Modified:**
```
application/cqrs/commands.py     (+EnablePluginCommand, DisablePluginCommand)
application/cqrs/queries.py      (+ListPluginsQuery)
application/di.py                (+configure_plugins, +register_plugin_adapters)
cli/main.py                      (+plugin subcommand group)
```

#### Estimated Effort: 6–8 days

| Phase | Days | Deliverable |
|-------|------|-------------|
| Manifest + validation | 1d | PluginManifest model, schema validation |
| Loader + sandbox | 2d | PluginLoader, import-level isolation, docker mode |
| PluginManager | 1d | Discovery, validation, registration, lifecycle callbacks |
| Store + CLI | 1d | PluginStore, CLI subcommands |
| Web API | 1d | PluginRouter REST endpoints |
| Tests + integration | 2d | 20+ tests, install→use→uninstall smoke test |

---

## 5. Feature 4 — Flat Module Classification (#10)

### Objective

Reclassify 41 flat modules in `weebot/*.py` into four buckets: DELETE (13 dead files), DEPRECATE (shim), PROMOTE (move into correct layer), or FREEZE (too coupled, mark as legacy). Every classification must be evidence-backed by static analysis of import references.

### Current State (from code_execution analysis)

#### Bucket A: DELETE — 13 files, 0 references

These can be removed immediately. They have zero imports from other weebot modules and are only ever imported by themselves.

```
agent_selection.py                 15,827 B
ai_providers.py                    22,137 B
automatic_template_adaptation.py   52,902 B
customized_suggestions.py          32,587 B
failure_recovery.py                17,862 B
gitnexus_config.py                  2,854 B
intelligent_template_suggestion.py 41,273 B
interface_customization.py         46,478 B
learning_from_executions.py        51,990 B
model_registry.py                  32,962 B
model_registry_detailed.py         44,725 B
rtk_provider.py                    13,338 B
state_coordinator.py                7,714 B
```

**Total:** 13 files · 384,649 bytes (~376 KB)

Before deleting, verify with `grep_files` across the ENTIRE workspace (including tests, docs, examples) that no file references these modules. One false positive here will break imports.

#### Bucket B: DEPRECATE — 5 files, add import shim + DeprecationWarning

These files have active callers but have direct replacements in the Clean Architecture layers.

| File | Active Callers | Replacement |
|------|---------------|-------------|
| `ai_router.py` | 5 callers (tests + state_coordinator + bash_security) | `ModelSelectionService` |
| `agent_core_v2.py` | 3 callers (cli/main, agent_factory, templates) | `AgentRunner` from `interfaces/cli/agent_runner.py` |
| `state_manager.py` | 10 callers (CLI + old tests + examples) | `SQLiteStateRepository` + `LegacyProjectAdapter` |
| `error_system_base.py` | 5 callers (docs + domain + handlers) | `domain/exceptions.py` + `core/exceptions.py` |
| `errors.py` | 2 callers (self-referential) | `domain/exceptions.py` |

**Strategy per file:**

```python
# In weebot/ai_router.py
import warnings
warnings.warn(
    "ai_router.py is deprecated. Use ModelSelectionService from "
    "weebot.application.services.model_selection instead.",
    DeprecationWarning,
    stacklevel=2,
)
from weebot.application.services.model_selection import (
    ModelSelectionService as ModelRouter,
    TaskType,
)
# Shim: keep old class name working
```

#### Bucket C: PROMOTE — 12 files, move into correct layer

| File | Move To | References | Why |
|------|---------|------------|-----|
| `activity_stream.py` | `core/` | 16 callers (examples + tests) | Already structured like a core utility |
| `nlp_understanding.py` | `application/services/` | 6 callers (agent_selection, suggestions, etc.) | NLP is an application service |
| `structured_logger.py` | `core/` | 3 callers (docs + tests) | Shared utility |
| `workflow_planner.py` | `application/flows/` | 7 callers (agent_selection, templates, etc.) | Flow planning is application logic |
| `information_synthesis.py` | `application/services/` | 2 callers | Research synthesis is a use case |
| `multi_source_research.py` | `application/services/` | 4 callers (customized, info_synth, etc.) | Research is a use case |
| `security_validators.py` | `infrastructure/security/` | 3 callers (docs + errors + file_editor) | Security validation is infrastructure |
| `user_profile_model.py` | `domain/models/` | 4 callers (suggestions, customization, etc.) | Domain model |
| `strategy_adaptation.py` | `application/services/` | 1 caller (complex_task_executor) | Learning/adaptation is application |
| `complex_task_executor.py` | `application/services/` | 1 caller | Task execution is application |
| `external_service_integration.py` | `infrastructure/` | 1 caller (multi_source_research) | Integration is infrastructure |
| `notifications.py` | `infrastructure/notifications/` | 2 callers (tests + windows_toast) | Already has adapters there |

**Migrating each file:**
1. Move the `.py` file to the target directory
2. Update all import paths in callers (do this atomically via `apply_patch`)
3. Add a `from weebot import <old_name>` shim in `__init__.py` for 1 release cycle
4. Delete the shim in v3.0

#### Bucket D: FREEZE — 11 files, mark as legacy only

These are too tightly coupled to the legacy track to move without breaking chains of dependencies among flat modules. Add a freeze header and leave them.

| File | References | Why not promote |
|------|-----------|-----------------|
| `cli_support.py` | 2 callers | Tightly coupled to old CLI infrastructure |
| `error_system_handler.py` | 2 callers | Circular with `error_system_base.py` |
| `error_system_user_messages.py` | 2 callers | Depends on `error_system_base.py` |
| `rtk_ai_router.py` | 1 caller (ai_router) | Legacy RTK integration, ai_router deprecated |
| `rtk_integration.py` | 1 caller (bash_tool) | Legacy RTK, no clean replacement |
| `gitnexus_provider.py` | 1 caller (test) | GitNexus is a separate product |
| `gitnexus_router.py` | 1 caller (test) | GitNexus is a separate product |
| `source_credibility_assessment.py` | 1 caller (info_synthesis) | Part of old research pipeline |
| `notifications_categorizer.py` | 1 caller (test) | Part of old notifications system |
| `tray.py` | 1 caller (test) | System tray, Windows-specific |
| `ai_router.py` | 5 callers (already in Bucket B) | Cross-listed |

**Freeze header:**

```python
"""
⚠️ LEGACY MODULE (Bucket D — Freeze)
Part of the pre-Clean-Architecture legacy track. Will not receive new features.
File issues against weebot.application.* for equivalent functionality.

Category: [explain why it's frozen, e.g., "Tightly coupled RTK integration"]
Last maintainer audit: 2026-05-28
Next review: v3.0 (proposed removal after shim period)
"""
```

### Implementation Order

| Step | Action | Files Affected | Reversible? |
|------|--------|---------------|-------------|
| 1 | Verify Bucket A with full workspace grep | 13 files | ✅ Delete is clean |
| 2 | Delete Bucket A files | 13 files | ✅ `git revert` |
| 3 | Add DeprecationWarning shims to Bucket B | 5 files | ✅ Revert + delete shim |
| 4 | Move Bucket C files to target layers | 12 files | ✅ Move back + revert imports |
| 5 | Update all import paths in callers | ~25 callers | ✅ Bulk revert via patch |
| 6 | Add backward-compat shim in `__init__.py` | 1 file | ✅ Delete shim block |
| 7 | Add freeze headers to Bucket D | 11 files | ✅ Revert headers |
| 8 | Architecture fitness test update | 1 file | ✅ Revert |
| 9 | Run full test suite | All tests | — |

### Files Modified (27 classified, ~25 caller updates)

**Migration pattern per file (example: `workflow_planner.py` → `application/flows/`):**

```bash
# 1. Move the file
git mv weebot/workflow_planner.py weebot/application/flows/workflow_planner.py

# 2. Update all callers (found 7)
# Edit: weebot/agent_selection.py
#   from weebot.workflow_planner import WorkflowPlanner
# → from weebot.application.flows.workflow_planner import WorkflowPlanner

# 3. Add shim to weebot/__init__.py for 1 release cycle
# from weebot.application.flows.workflow_planner import *  # shim — remove in v3.0
```

#### Estimated Effort: 3–4 days

| Phase | Days | Deliverable |
|-------|------|-------------|
| Full workspace verification of Bucket A | 0.5d | Confirmed dead files list |
| Delete Bucket A | 0.5d | 13 files removed |
| Bucket B deprecation shims | 0.5d | 5 files shimmed, tests pass |
| Bucket C promotion | 1.5d | 12 files moved, all callers updated |
| Bucket D freeze headers | 0.5d | 11 files marked |
| Update architecture fitness tests | 0.5d | `test_no_flat_modules_remaining` added |

---

## 6. Dependency Order & Sprint Schedule

### Dependency Graph

```
Plugin System (Phase 12)
  └─ depends on: Flat Module Classification (#10)
       └─ needs stable module paths before plugin sandbox can restrict imports

Chatbot
  └─ independent of everything (uses existing infrastructure)

Cross-Model Transfer (#8)
  └─ independent of everything (uses existing Skill infrastructure)
```

### Sprint Schedule — 6 Weeks

```
Week 1–2  │ Chatbot                             │ 4–5 days effort
          │  • ChatAgent + ChatFlow             │
          │  • REST + WebSocket endpoints       │
          │  • Web UI chat page                 │
          │  • 15+ tests                        │
          │                                     │
Week 3    │ Cross-Model Transfer (#8)           │ 2 days effort
          │  • TransferResult model             │
          │  • ValidateTransferHandler          │
          │  • CLI subcommand                   │
          │  • 10 tests                         │
          │                                     │
Week 4–5  │ Flat Module Classification (#10)    │ 3–4 days effort
          │  • Verify + delete Bucket A         │
          │  • Deprecate Bucket B               │
          │  • Promote Bucket C                 │
          │  • Freeze Bucket D                  │
          │                                     │
Week 6    │ Plugin System (Phase 12)            │ 6–8 days effort
          │  • PluginManifest + PluginLoader    │ (spans into Week 7 if needed)
          │  • PluginManager + lifecycles       │
          │  • Sandbox + security               │
          │  • CLI + web API                    │
          │  • 20+ tests                        │
```

**Total:** ~19 person-days across 6 weeks.

### Parallelization Opportunities

- **Weeks 1–2** (Chatbot) and **Week 3** (Transfer) can be developed in parallel by different team members — zero shared files between these features.
- **Week 4–5** (Classification) produces the stable module tree that **Week 6** (Plugin system) depends on. These must be sequential.

---

## 7. Risk Register

| Risk | Severity | Mitigation |
|------|----------|------------|
| Bucket A deletion breaks undocumented imports | **MEDIUM** | Full workspace grep before deletion. Any reference found → move to Bucket B instead |
| Bucket C promotion breaks callers using `from weebot import X` | **MEDIUM** | Add backward-compat shim in `__init__.py`, deprecation warning, delete in v3.0 |
| Plugin sandbox can't prevent escape via native code | **LOW** | Python import hooks are bypassable. `docker` mode exists for untrusted plugins |
| ChatFlow duplicates PlanActFlow logic | **LOW** | Designed to share `BaseFlow`, event bus, session persistence — only the state machine differs |
| 338-model registry import is slow at startup | **LOW** | Existing issue (136KB dict). Consider lazy-loading or moving to JSON config for v3.0 |

---

## 8. Architecture Compliance

This plan was audited against Weebot's architecture rules (2026-05-28).
All violations were resolved in-plan before any code was written.

### Rules

| # | Rule | Enforcement |
|---|------|-------------|
| R1 | Dependency direction: domain ← application ← infrastructure ← interfaces | CI fitness test |
| R2 | CQRS for writes: all state mutations through `mediator.send()` | Static analysis |
| R3 | Event-driven: events published via `EventBusPort` | Convention |
| R4 | Port/adapter: external deps behind ports in `application/ports/` | Convention |
| R5 | DI composition root: `application/di.py` is single wiring hub | CI fitness test |
| R6 | Immutable domain models: `model_copy(update=…)` | Convention |
| R7 | Domain imports nothing from outer layers | CI fitness test |

### Feature-by-feature pass/fail

| Feature | R1 | R2 | R3 | R4 | R5 | R6 | R7 | Verdict |
|---------|-----|-----|-----|-----|-----|-----|-----|---------|
| Chatbot | ✅ | ✅* | ✅ | n/a | ✅ | ✅ | ✅ | PASS |
| Cross-Model Transfer | ✅* | ✅ | n/a | n/a | ✅* | ✅ | ✅ | PASS |
| Plugin System | ✅ | ✅ | n/a | ✅ | ✅* | n/a | ✅ | PASS |
| Flat Module Classification | ✅ | n/a | n/a | n/a | n/a | n/a | ✅ | PASS |

\* Denotes a fix applied during the architecture audit before the plan was finalised.

### Fixes applied

| Issue | Severity | Resolution |
|-------|----------|------------|
| Chatbot data flow diagram was ambiguous about CQRS delegation | MEDIUM | Clarified in §2: `ProcessMessageHandler` owns the agent call, flow consumes from `CommandResult.data["events"]`. Falls back to direct-agent-call path when `mediator is None`. |
| Transfer handler pseudocode imported from `interfaces/` | HIGH | Changed to inject `flow_factory: Callable` via DI constructor. Handler no longer imports from the interfaces layer. |
| `application/di.py` missing from Chatbot modified-files list | LOW | Added `+configure_chat, +build_chat_flow` to Chatbot manifest. |
| `application/di.py` missing from Plugin System modified-files list | LOW | Added `+configure_plugins, +register_plugin_adapters` to Plugin manifest. |

### Post-implementation verification

After each feature is implemented, run the architecture fitness tests
to confirm no regressions:

```bash
pytest tests/unit/test_architecture_fitness.py -v
```

For the Chatbot feature, add an additional fitness test:

```python
def test_no_direct_chat_agent_calls_in_chat_message_state():
    """ChatMessageState must use mediator.send(), not direct ChatAgent calls."""
    ...
```

For the Transfer feature, add:

```python
def test_transfer_handler_does_not_import_from_interfaces():
    """ValidateTransferHandler must not import create_flow from interfaces/."""
    ...
```
