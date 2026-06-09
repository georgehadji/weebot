# Weebot — Enterprise AI Agent Framework

[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](.python-version)
[![Version](https://img.shields.io/badge/version-4.0-blue)]
[![Tests](https://img.shields.io/badge/tests-19%20arch%20%2B%20114%20unit%2Fintegration-passing-brightgreen)]
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Architecture](https://img.shields.io/badge/architecture-Clean%20Hexagonal%20%7C%20CQRS%20%7C%20Middleware-8A2BE2)]
[![State](https://img.shields.io/badge/meta--state-HEALTHY-brightgreen)]

**A production-grade framework for autonomous AI agents** built on Clean Architecture with middleware-based orchestration, multi-model cost cascading, secure sandboxed execution, autonomous ideation pipeline, and self-evolving skills.

→ [Quick Start](#quick-start) · [Capabilities](#capabilities) · [Architecture](#architecture) · [CLI Reference](#cli-reference) · [Security](#security-model) · [Skills](#built-in-skills) · [Testing](#testing)

---

## Why Weebot

| Concern | Weebot | Raw LangChain / DIY |
|---------|--------|---------------------|
| **Architecture degrades** | 19 fitness tests enforce Clean Architecture + middleware boundaries in CI | No structural enforcement |
| **LLM costs spiral** | FREE → Budget → Premium cascade with circuit breakers, per-role model configs, task-preset tiers | One model for everything |
| **Agents don't learn** | SkillOpt optimizer improves skills from execution trajectories | No improvement mechanism |
| **Can't audit agents** | CQRS event stream (19 types) with SQLite audit trail + Parquet export + OTel traces | Ad-hoc logging |
| **Shell execution is risky** | 4-layer defense: 40+ patterns, entropy analysis, behavioral detection, semantic validation | `subprocess.run()` |
| **No code review** | Per-step LLM code review with approve/revise/reject routing, TrustReport, cross-step trajectory detection | Manual PR review |
| **No proactive ideation** | DreamerAgent surfaces ideas from failure signals, IdeaGate filters through IntentReview → MainReview | Reactive only |
| **Tool sprawl** | BackendPort unifies 39 tool files into 7 I/O methods; FilesystemPermission gates path-level access | Each tool invents its own execution path |

---

## Capabilities

### Autonomous Agent Loop
Plan → Critique → Pre-mortem → Execute (parallel tools) → Review → Verify → Summarize. Every state is a typed `FlowState`, every tool call is traced, and every failure triggers Tree-of-Thoughts revision.

### Code Review Agent
Per-step LLM code review between execution and the next step. Uses cross-lab models (Critic ≠ Executor). Verdicts: approve, revise (retry with hint), reject (trigger replanning). Integrated with TrustReport for evidence-based trust scoring.

### DreamerAgent + IdeaGate Pipeline
Autonomous ideation from opportunity proposals, failed-step events, and audit violations. DreamerAgent surfaces up to 5 `IdeaContract`s. IdeaGate chains `IntentReview` (coherence/safety) → `MainReview` (risk scoring). Only `APPROVED_FOR_CODER` contracts reach execution. Background scan on every session completion.

### TrustReport & Retention
`TrustReport` (pure computation, zero LLM) compares code review verdicts against CoVe fact-checking to produce clean/watch/investigate bands. `RetentionAgent` reviews completed sessions and recommends keep/improve/park/prune. Both fire non-blocking in `CompletedState`.

### Middleware Architecture
Agent middleware stack — each concern (tool dispatch, trajectory monitoring, step validation, sub-agent dispatch) is a composable `Middleware` with `before_request` / `after_response` / `after_tool_call` lifecycle hooks. `SubAgentMiddleware` exposes sub-agents as a single `task` tool.

### BackendProtocol — Unified Tool I/O
All filesystem and execution operations through one `BackendPort` ABC: `ls`, `read`, `write`, `edit`, `glob`, `grep`, `execute`. `SandboxBackendAdapter` delegates to `SandboxPort`. `FilesystemPermission` (allow/deny/interrupt) gates path-level access declaratively.

### Declarative Task Presets
Three cost/quality tiers (`simple`/`standard`/`complex`) control pre-mortem, step validation, critique thresholds, and max steps. Injected at `PlanActFlowConfig` construction — no flow logic changes.

### Image Generation
Multi-model image cascade: Ideogram (text/logos, $0.03/img) → Recraft (vectors) → Flux.2 Pro (photorealistic) → Sourceful Riverflow (free) → SVG template fallback. OpenRouter + direct APIs (xAI, Ideogram). OG cards, hero banners, icons, logos.

### Tool Result Cache
Session-scoped LRU cache for idempotent tool calls. SHA-256 keyed. Per-tool TTLs. Write-path tracking invalidates `read_file` caches. 500-entry cap with LRU eviction.

### Self-Evolving Skills
12 built-in skills including `seo_optimizer` (technical audit + structured data generation + keyword research), `reify_skill` (YouTube video → transcript → summary → actionable rules in persistent memory), `architecture_design`, `tdd_app_dev`, `orchestration_guide`, `git-best-practices`, `design-taste-frontend`, `web_research`, `competitive_analysis`, `reasoner`, `multi_llm_orchestrator`. SkillOpt optimizer iteratively improves skills from execution trajectories.

---

## Quick Start

```bash
git clone https://github.com/georgehadji/weebot.git
cd weebot
pip install -r requirements.txt
cp .env.example .env   # Add your API keys

# Verify
python -m cli.main health

# Run a task
python -m cli.main flow run "Analyze the codebase for security issues"

# Interactive mode (HITL loop)
python run.py --interactive

# With a skill loaded
python run.py --interactive --skill seo_optimizer
```

### Configuration

```bash
# .env — minimum
OPENROUTER_API_KEY=sk-or-v1-...

# Direct APIs (bypass OpenRouter, lower latency)
XAI_API_KEY=...          # Grok image gen + coding models
IDEOGRAM_API_KEY=...     # Ideogram image gen ($0.03/img)
KIMI_API_KEY=...         # Kimi K2.6 direct
DEEPSEEK_API_KEY=...     # DeepSeek V4 Flash direct

# Optional
WEEBOT_MCP_API_KEY=...   # MCP server auth
WEEBOT_SESSIONS_DB=...   # Custom DB path
```

---

## CLI Reference

### Flow
```bash
python -m cli.main flow run "task"            # Execute PlanActFlow
python -m cli.main flow list                   # List sessions
python -m cli.main flow resume <id> "answer"  # Resume paused session
python -m cli.main flow cancel <id>            # Cancel session
python -m cli.main flow export <id>            # Export to JSONL
```

### Dream Pipeline
```bash
python -m cli.main dream scan                  # DreamerAgent + IdeaGate cycle
python -m cli.main dream list                  # Pending idea contracts
python -m cli.main dream build <id>            # Execute approved contract
```

### Skills
```bash
python -m cli.main skills list                 # List installed skills
python -m cli.main flow skillopt <name>        # Optimize a skill
```

### Agents
```bash
python -m cli.main agents list                 # List personas
python -m cli.main agents route "task"         # Route to best persona
```

### Diagnostics
```bash
python -m cli.main health                      # Component health
python -m cli.main doctor --fix                # Auto-repair
```

### Security
```bash
python -m cli.main guard check -c "rm -rf /"   # Evaluate command safety
```

---

## Architecture

```
weebot/
├── domain/models/          # Pure Pydantic — no outer deps
│   ├── plan.py, session.py, event.py     # Core entities
│   ├── code_review.py                    # CodeReviewResult
│   ├── idea_contract.py                  # IdeaContract, IdeaSource
│   ├── intent_review.py, main_review.py  # Gate review models
│   ├── trust_report.py                   # VerificationDelta, TrustReport
│   ├── retention_review.py               # RetentionVerdict
│   ├── backend_results.py                # LsResult, ReadResult, etc.
│   ├── fs_permission.py                  # FilesystemPermission
│   ├── task_preset.py, role_profile.py  # Config models
│   └── ...
├── application/            # Use cases + orchestration
│   ├── di/                  # Container + 5 mixins (single composition root)
│   ├── ports/               # 47 ABC port interfaces
│   ├── flows/states/        # 12 state classes (Planning→Critiquing→Premortem→Executing→Reviewing→Updating→Verifying→Summarizing→Completed)
│   ├── agents/              # 12 agent implementations (Executor, Planner, Dreamer, Retention, etc.)
│   ├── middleware/          # Middleware ABC + SubAgentMiddleware
│   ├── cqrs/                # Mediator, 17 commands, 12 queries
│   ├── services/            # 65+ application services
│   └── skills/              # Registry + format converters
├── infrastructure/          # Adapters (LLM, persistence, sandbox, events)
├── interfaces/              # CLI, Web (FastAPI), Discord, Slack, Telegram
├── tools/                   # 39 agent-callable tools (port-based)
├── skills/builtin/          # 12 skills (SKILL.md manifests)
├── mcp/                     # MCP server
└── config/                  # Settings, model registry, prompts, constants
```

**Layer rule:** `Domain ← Application ← Infrastructure ← Interfaces` — enforced by 19 automated CI tests.

---

## Operational Flow

```
User Prompt
    │
    ▼
PlanningState (generate plan)
    │
    ▼
CritiquingState (LLM validates plan — confidence thresholds)
    │
    ▼
PremortmState (imagine failure, inject risks)
    │
    ▼
ExecutingState (execute steps with parallel tool calls)
    │   │
    │   ├── StepResultValidator (quality gate, retry once)
    │   ├── CodeReviewerService (per-step LLM review: approve/revise/reject)
    │   └── TrajectoryMonitor (cross-step pattern detection)
    │
    ▼
UpdatingState (Tree-of-Thoughts revision on failure)
    │
    ▼
VerifyingState (CoVe fact-checking)
    │
    ▼
SummarizingState → CompletedState
    │
    ├── TrustReport (clean/watch/investigate)
    ├── RetentionAgent (keep/improve/park/prune)
    └── DreamerAgent auto-scan (surface new ideas)
```

---

## Built-in Skills

| Skill | Trigger | What it does |
|-------|---------|-------------|
| `seo_optimizer` | "SEO audit", "improve rankings" | Technical audit → keyword research → structured data → sitemap |
| `reify_skill` | "reify", "learn from video" | YouTube transcript → summary → actionable rules in persistent memory |
| `architecture_design` | "design architecture", "plan system" | Pattern selection, layer boundaries, ADR generation |
| `tdd_app_dev` | "build feature", "implement" | Red-Green-Refactor cycle for Python/JS/TS |
| `orchestration_guide` | "parallel tasks", "dispatch agents" | When to parallelize, file partitioning, synthesis strategy |
| `git-best-practices` | "commit", "branch" | Conventional commits, branching, secrets safety |
| `design-taste-frontend` | "redesign", "landing page" | Anti-slop design, visual quality enforcement |
| `web_research` | "research", "find information" | Multi-engine search + browser research |
| `competitive_analysis` | "competitor", "landscape" | Swarm-based clustering + whitespace identification |
| `reasoner` | "reason through", "debate" | 24 reasoning methods, 46 presets |
| `multi_llm_orchestrator` | "orchestrate", "multi-agent" | Delegates full-stack dev to multi-LLM pipeline |
| `berb-research` | "academic paper", "literature" | 23-stage autonomous research pipeline |

---

## Security Model

4-layer defense-in-depth for command execution:

```
User Command
    │
    ▼
BashGuard (40+ regex, 6 categories: rm, curl|sh, fork bomb, encoded, chmod, reverse shell)
    │
    ▼
CommandSecurityAnalyzer
    ├── Layer 1: Syntax Patterns (bash + PowerShell)
    ├── Layer 2: Behavioral Analysis (download+execute chains)
    ├── Layer 3: Entropy Analysis (Shannon entropy on base64-like strings)
    └── Layer 4: Semantic Validation (chain length, URL detection)
    │
    ▼
FilesystemPermission (declarative allow/deny/interrupt on paths)
    │
    ▼
ExecApprovalPolicy (DENY / ALWAYS_ASK / AUTO_APPROVE)
    │
    ▼
SandboxPort (timeout, output limits, network gating)
    │
    ▼
Execution
```

---

## Testing

```bash
pytest tests/unit/ -v                          # Unit tests (114 passing)
pytest tests/unit/test_architecture_fitness.py # Architecture gates (19 passing)
```

---

## License

MIT — see [LICENSE](LICENSE).

---

*Weebot v4.0 · Architecture fitness-verified · Middleware-based · Self-evolving skills · Ideogram + OpenRouter image cascade · Meta-state: HEALTHY*
