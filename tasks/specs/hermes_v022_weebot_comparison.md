---
status: open
date: 2026-11-03
note: Hermes ~v0.22 vs Weebot; 43-dimension matrix; phased parity backlog H1-H40
---

# Hermes-Agent v0.22 → Weebot: capability audit, comparison and parity plan

**Source A.** `NousResearch/hermes-agent`, zip export at `C:\Users\tesse\Downloads\hermes-agent-main\hermes-agent-main`. Files are dated 2026-11-03; there is no `.git`. `hermes_cli/__init__.py:5` sets `__release_date__ = "2026.9.24"`. Catalog entries require `>=0.22.0` (`plugin-catalog/mcp-serve.yaml`), so this is **v0.22.x**. The exact minor version is a HYPOTHESIS.

**Source B.** Weebot at `b4ee83bb`, branch `chore/openrouter-catalog-refresh-2026-11-03`. It has 775 production `.py` files and 686 test files. 747 commits have landed since the v0.19 study.

**Method.** Five read-only deep-dives ran in parallel:
- Hermes agent core;
- Hermes tools;
- Hermes interfaces and gateway;
- Hermes extensibility and ops;
- a Weebot inventory and status check.

The lead reviewer then re-read the load-bearing claims (Appendix A). Nothing in the Hermes tree was executed or imported.

**Evidence convention** (same as the v0.19 study):
- FACT: read in code, cited as `file:line`.
- HYPOTHESIS: labelled as such.
- Absence: means "not found in the searched surface".
- Paths: Hermes paths are relative to its root; Weebot paths start with `weebot/`.

### Relationship to prior work

This study builds on the v0.17 audit (`hermes_agent_deep_audit_report.md`) and the v0.19 study (`hermes_v019_weebot_architecture_study.md`). It does not replace either.

The v0.19 study's main finding was that "a large fraction of what WeeBot has already built does not execute". That finding is **mostly resolved** (status per item in §6.1). The posture therefore changes from "make it run" to "close the gaps, then extend at the edges". The v0.19 rejection list still stands (§8).

---

## 1. Executive summary

### 1.1 What Hermes is

Hermes is Nous Research's single-user personal agent. One agent core runs behind every surface:
- a CLI and an Ink TUI;
- an Electron desktop app and a web dashboard;
- an OpenAI-compatible API server;
- an ACP adapter for IDEs;
- a messaging gateway with 27 plugin adapters.

**Core loop.** A flat ReAct tool loop with no `Plan` object. Two axioms drive it (`AGENTS.md:20-27`):
1. Per-conversation prompt caching is sacred.
2. The core is a narrow waist; capability lives at the edges.

**Learning.** Hermes learns across sessions in three ways:
- frozen-snapshot memory;
- a background self-review fork;
- an archive-only skill curator.

**Work it does.** It delegates to subagents, runs cron and kanban automations, and drives a terminal on six backends, a browser, and the desktop.

**Extension.** Mostly through:
- **plugins**: a 977-entry, SHA-pinned catalog;
- **skills**: 44 bundled and 149 optional, installed from a hub that pulls from several registries.

### 1.2 What changed since v0.19 (the delta that matters)

| Area | v0.19 (2026-07) | v0.22 (2026-09/11) | Evidence |
|---|---|---|---|
| God-files | `gateway/run.py` 23,279 lines; `cli.py` 16,250 | 5,224 and 1,793. Each is now a facade plus `<stem>_<topic>.py` siblings, under a per-unit complexity ratchet | `AGENTS.md:101-117`, `scripts/code_health/config.py:19-28` |
| In-place compaction | default False | **default True** | `hermes_cli/config_defaults.py:672` |
| Error classes | 23 | 30 `FailoverReason` values | `agent/error_classifier.py:34-67` |
| Core tools | 52 | 41. Browser tools collapsed into `browser_exec`; Home Assistant left core | `toolsets.py:11-45` |
| Platform adapters | 20 | 27 plugin directories, plus api_server, webhook, msgraph and Relay | `plugins/platforms/` |
| Plugins | 23 hooks | ~45 hooks, 4 middleware stages, host-process isolation, capability consent, 977-entry catalog | `hermes_cli/plugins.py:109-201`, `middleware.py:20-24`, `plugin_capabilities.py:25-43` |
| Skills | 78 bundled / 104 optional | 44 / 149. Adds skill locks, a mutation ledger with rollback, and an AST audit | `skills/AGENTS.md:64-81` |
| New subsystems | — | Listed below this table | §2 |
| Tests | 2,244 files | 7,259 files; 57 CI workflows | `tests/`, `.github/workflows` |

New subsystems since v0.19 (details in §2):
- **Coding and verification:** LSP delta diagnostics; a verification evidence ledger with verify-on-stop.
- **Secrets and egress:** iron-proxy egress credential swap; secret sources (Bitwarden, 1Password); a model-blind vault.
- **Execution:** persistent `execute_code` kernels; cross-OS `computer_use`; Bot Screen.
- **Delegation:** durable async delegation; delegation route plugins.
- **Session commands:** `/goal` judge; `/btw`; MoA loop.
- **Operations:** OTLP health events; release channels; a transactional updater; profile distributions; managed scope.

### 1.3 Scorecard

The full 43-dimension matrix is in §4.

- **Weebot ahead (9):**
  - planning FSM;
  - verification and critique;
  - evals and harness optimization;
  - observability;
  - architecture enforcement;
  - cost cascade;
  - taint tracking;
  - Windows-native sandboxing;
  - multi-agent patterns: swarm, debate, MoA, workflow.
- **Parity (8):**
  - web search;
  - image and video generation;
  - vision;
  - learning-loop shape;
  - approvals overall;
  - core cron;
  - MCP serving;
  - multi-user web.
- **Hermes ahead (26):** these are mostly gaps in depth and breadth, not missing concepts. The biggest:
  - prompt caching;
  - compression;
  - the error-recovery ladder;
  - the file-edit pipeline;
  - the plugin system;
  - MCP client depth;
  - the messaging gateway;
  - delegation control;
  - secrets and egress.

### 1.4 Recommendation

Weebot can **equal or exceed Hermes on every dimension that matters to its users within about five phases**. Most Hermes advantages fall into two groups:
- cheap single-module ports into ports Weebot already has;
- v0.19 carry-overs that never landed.

Match pure *breadth* items selectively, not to parity. These are:
- 27 chat platforms;
- 17 locales;
- the Electron desktop;
- the TUI;
- the 977-entry catalog.

For those, build the *mechanism* (a plugin adapter contract, a catalog format) and let breadth accrue.

Do the five correctness and security carry-overs first (§7, Phase 0). They are small, and two of them are live security debt.

---

## 2. How Hermes works

### 2.1 Turn loop

- `run_agent.py` is a 1,565-line facade. `AIAgent` is assembled from 14 mixins (`run_agent.py:214`).
- `agent/conversation_loop.py:1745` is a single `while` loop. It runs while `api_call_count < max_iterations` and `budget.remaining > 0`, or a grace call remains.
- Each iteration chains phases, and each phase returns break, continue or return:
  1. `begin_iteration`
  2. `prepare_iteration`
  3. `assemble_api_request`
  4. `run_preflight_gate`
  5. `_run_api_retry_loop`
  6. `normalize_model_response`
  7. `run_tool_round` or `finish_text_response`

**Guardrails:**
- **`IterationBudget`:** 500 for the parent, 50 for children. `execute_code` refunds iterations.
- **`tool_guardrails.py`:**
  - a notice after 3 identical calls;
  - detection of A-B-A-B cycles up to period 4;
  - duplicate results replaced by reference stubs;
  - caps of 50 web searches and 50 subagents per turn.
- **Wall-clock budget:** a wrap-up note is added at 80% of the budget.
- **Liveness watchdog** (`turn_liveness.py`).
- **Empty and thinking-only response ladder** (`empty_response_guard.py`): it stops after 2 deterministic empty responses, and cuts the retry budget when one empty attempt costs more than $0.25.
- **Repetition guard.**
- **Auto-recover after exhaustion** (`turn_recovery_autorecover.py`): 5 cycles, waiting 15/30/60/60/60 s.

**Planning:**
- the `todo_list` tool (≤ 256 items, re-injected after compaction);
- prompt-only `/plan`, which writes to `.hermes/plans/*.md`;
- `/goal`, a persistent goal checked by an auxiliary `goal_judge` model (`hermes_cli/goals.py`).

There is still no `Plan` object and no FSM.

### 2.2 Prompt and cache discipline

- **System prompt.** Built once per session in three tiers: stable, context, volatile (`agent/system_prompt.py:1-8`). It is stored by hash, and `sessions.tool_names` pins `tools[]`.
- **Mid-conversation injections ride user messages or tool results, never the system prompt** (`agent/AGENTS.md:55-67`). This covers plugin context, memory recall, gateway notes and `/steer`.
- **Anthropic caching** uses:
  - 4 cache breakpoints;
  - stable prefixes declared by the prompt builders;
  - a `prompt_cache_key` scoped to the compression lineage root, so it survives session rotation;
  - `cache_ttl: auto`: 1 h on human-paced surfaces, 5 min elsewhere (`config_defaults.py:685-688`).
- **Operator rebuild** goes through an epoch (`hermes sessions refresh-prompts`).
- **CI lane `prompt-surface-diff.yml`** posts the system-prompt and `tools[]` diff on every PR.

### 2.3 Context compression

**Triggers.** Gateway hygiene compresses at 85% of the window. The agent compressor triggers at 50%, or 75% for windows under 512 K.

**Tail.** Token-budgeted: `target_ratio` 0.20, `protect_last_n` 20, `protect_first_n` 3.

**Order of operations:**
1. Prune old tool results, with no LLM call.
2. Pick the compaction boundaries.
3. Write a structured summary with the auxiliary `compression` model.
4. On failure, use the fallback chain, then a deterministic summary.

**In-place by default.** The session id stays the same. Old rows are soft-archived and remain searchable.

**Opt-in extras:**
- `prepare_ahead`: summarize in the background ahead of need;
- `micro_compaction`;
- native OpenAI Responses compaction;
- idle compaction;
- `checkpoint_required`: fails closed unless the memory provider has a checkpoint.

**`ContextEngine` ABC.** Adds `select_context`, for engines that do retrieval or branch-switching (`agent/context_engine.py:121`).

### 2.4 Memory and learning

**Memory:**
- `MEMORY.md` (2,200 chars) and `USER.md` (1,375 chars) are injected as a **frozen snapshot**. Writes go to disk only (`tools/memory_tool.py:1-5`).
- The snapshot is scanned for promptware when it is taken.
- The `MemoryProvider` ABC has 22 hooks, including:
  - `on_pre_compress`, with a checkpoint API;
  - `on_delegation`;
  - `on_session_switch`.
- External memory backends (Honcho, mem0, supermemory, hindsight) are catalog plugins.

**Background review** (`agent/background_review.py:173-182,370-440`):
- **Trigger:** about every 10 turns (`memory.nudge_interval`, `skills.creation_nudge_interval`).
- **Fork:** inherits the cached prefix and uses a whitelist of tools enforced at dispatch.
- **Limits:** 16 iterations; input capped at 75% of context or 600 K tokens.
- **Effect:** it creates or patches memory and skills. Its prompts say "ground in the conversation, one store per fact, class-level skills".

**Curator** (`agent/curator.py`):
- Runs on inactivity: every 7 d, after 2 h idle.
- Marks skills stale at 14 d and archives them at 30 d.
- Archives only, never deletes. Pinned skills are exempt.
- LLM consolidation is still off (`agent/curator.py:35`).

**Skill governance:**
- `skill_lock.py`: a user lock blocks every agent write path.
- `skill_ledger.py`: a JSONL ledger of mutations, with content-addressed backups and single-edit rollback.
- `skill_provenance.py`: separates foreground writes from background writes.

**Session search** (`tools/session_search_tool.py`):
- 4 modes, no LLM calls.
- 3 FTS5 indexes: unicode61, trigram (tool rows excluded) and CJK bigram (`hermes_state_fts.py:47`).

### 2.5 Providers

- **Provider profiles.** 39 `ProviderProfile` plugins (`plugins/model-providers/`), with hooks `prepare_messages`, `build_extra_body`, `supported_reasoning_efforts` and `fetch_models`.
- **Model catalog.** models.dev, offline-first with ETag refresh, plus 43 Hermes overlays.
- **Five `api_mode`s**, behind a `ProviderTransport` ABC:
  - `chat_completions`
  - `codex_responses`
  - `anthropic_messages`
  - `bedrock_converse`
  - `codex_app_server`
- **Credential pool** (`agent/credential_pool.py`):
  - strategies fill_first, round_robin, random and least_used;
  - 429 cooldowns scoped per model.
- **Fallback.** `upstream_rate_limit` falls back to a *different model*, not only another key.
- **Auxiliary models.** At least 16 task slots, such as compression, approval, vision, review, title, goal_judge and curator.
- **Credit tracking.** `plan_limits.py` and `credits_tracker.py` read provider credit headers.

### 2.6 Tools

**Registry:**
- `discover_builtin_tools()` filters modules by AST before importing them, and caches verdicts on disk.
- `check_fn` gating uses a TTL plus a grace window after a recent success.
- Secrets are read only through `agent.secret_scope.get_secret`.

**Dispatch pipeline** (`model_tools.py:886`):
1. Argument coercion, schema-guided: `"42"` becomes an int, JSON strings become arrays.
2. Alias map.
3. tool_search bridge.
4. Connector routing.
5. Request middleware.
6. `pre_tool_call` hooks, which can block or rewrite the call.
7. Execution, wrapped by execution middleware.
8. `post_tool_call`.
9. `transform_tool_result`.

**Progressive disclosure:**
- MCP tools, plugin tools and listed core tools hide behind `tool_search`, `tool_describe` and `tool_call`.
- The manifest degrades in steps: full, then names-only, then the bare bridge (`config_defaults.py:1976-2010`).

**Output hygiene:**
- per-tool caps;
- head/tail split at 40/60;
- **spillover**: full output is written to `$HERMES_HOME/cache/spillover/`, and the model gets a preview plus the path;
- a per-turn output budget (`tools/tool_result_storage.py:1-8`).

**File editing:**
- `patch` tries a chain of 9 fuzzy strategies (`tools/fuzzy_match.py:289-298`).
- V4A patch format.
- Escape-drift autocorrect.
- Refuses to overwrite a stale file.
- A cross-agent `FileStateRegistry` tracks file reads across agents.
- Auto-lint after writes.
- **LSP delta diagnostics** from 28 language servers. Non-blocking and gated on workspace trust (`agent/lsp/`).
- **Shadow-git checkpoints**, taken once per turn before a mutation, with rollback (`tools/checkpoint_manager.py`).

**Code execution** (`tools/code_kernel.py:1-18`):
- A **Python kernel that persists for the session**, with an LRU cap of 4 kernels.
- It exposes 7 tools over a Unix socket, or loopback TCP on Windows.
- Only stdout returns to the model.

**Terminal:**
- Backends: local, docker, ssh (ControlMaster), modal, daytona, vercel_sandbox, plus plugins (`terminal_tool_backends.py:46`).
- Docker runs with `--cap-drop ALL`, PID limits and **iron-proxy egress enforced by default** (`tools/environments/docker_egress.py`).
- `process_manage` runs background jobs with notify patterns and handoff.

**Browser:**
- **`browser_exec`:** model-written Python run over CDP, with helper functions.
- **Companion tools:**
  - `browser_cdp`;
  - `browser_dialog`, backed by a dialog supervisor;
  - `browser_vault`: autofill the model never sees.
- **Endpoint ladder:** env CDP, then override, then hybrid local sidecar, then cloud (browser_use, browserbase, firecrawl), then the real user profile, then Lightpanda, then bundled Chromium.
- **URL floor:** blocks the cloud metadata endpoint (IMDS) and private IPs.

**Computer use:**
- `computer_use` is driven by cua-driver over MCP. It runs on macOS (AX), Windows (UIA) and Linux (AT-SPI).
- Input is delivered in the background first.
- Dangerous keys and typed patterns are hard-blocked before the approval prompt.
- **Bot Screen:** a per-profile Xvnc desktop. A control lease decides whether the human or the agent drives, enforced by filtering RFB input bytes.

**MCP client:**
- **Transports:** stdio, Streamable HTTP and SSE, with mTLS.
- **OAuth:** DCR plus PKCE, and device flow.
- **Sampling:** on, capped by requests per minute, tokens and allowed models.
- **Elicitation:** routed through the approval surface.
- **Trust:** a `trust: untrusted` server needs approval for its write tools. Declared per-tool costs feed a per-chat `spend_limit`.
- **Supply chain:** an OSV malware check runs before spawning `npx`/`uvx`.
- **Other:** a lazy schema cache, and 66 catalog manifests.

**Delegation** (`delegate_task`):
- Actions: spawn, list, steer, stop.
- Limits (`tools/delegate_tool_config.py:19-23`, `delegate_tool_toolsets.py:14-21`):
  - `MAX_DEPTH = 1`; deeper needs `max_spawn_depth`;
  - 10 concurrent children;
  - blocked in children: delegate_task, clarify, memory, send_message, cronjob.
- `output_schema` validation with one retry.
- An optional git worktree per child.
- `background=true` is backed by a **durable SQLite ledger**, and `recover_abandoned_delegations()` resumes it.
- Route-provider plugins choose the model, provider and profile per task.

### 2.7 Safety

**Stance.** "The only security boundary against an adversarial LLM is the operating system" (`SECURITY.md:58-60`). In-process defences are labelled defence-in-depth.

**Approval order** (`tools/approval.py:1184+`):
1. Floors, which run before YOLO or `mode: off`:
   - about 12 hardline patterns;
   - `sudo -S` stdin piping;
   - user deny globs, matched against deobfuscated variants.
2. YOLO bypass.
3. Permanent allowlist.
4. 102 `DANGEROUS_PATTERNS`.
5. Human decision.

**Approval modes:**
- **Smart mode:** a guardian auxiliary LLM returns approve, deny or escalate. An approval covers one command only.
- **Approval scopes:** once, session, always. The prompt times out after 300 s, and a denial circuit breaker runs per session.
- **Unattended contexts** default to deny: cron, `-q`, and platforms with no human.

**Write guards:**
- sensitive paths are denied;
- writes to agent-instruction files always ask;
- memory and skill writes can be staged for approval;
- a guard on git writes to Hermes's own repo;
- `runtime_self_protection.py` blocks deleting the venv, even under YOLO.

**Egress.** iron-proxy is a default-deny proxy that intercepts TLS. The sandbox holds opaque tokens; the proxy swaps them for real keys on the way out. Docker backend only.

**Secrets:**
- pluggable secret sources: Bitwarden (`bws`), 1Password (`op://`), a command helper;
- a per-profile `secret_scope` that fails closed;
- a scrubbed environment for every subprocess (`build_subprocess_env`);
- 133 redaction patterns.

**Gateway:**
- allowlists, default deny;
- DM pairing: 8-character codes, 1 h TTL, 10 min rate limit, lockout after 5 failures;
- separate admin and user slash-command tiers (`gateway/slash_access.py`).

**Supply chain:**
- `hermes security audit` checks against OSV;
- pinned dependencies;
- catalog plugins pinned by SHA;
- a `removed.yaml` kill list;
- an install scanner.

### 2.8 Surfaces and runtime

**Gateway runtime:**
- One process serves **all profiles** by default.
- Session key: `ns:platform:chat_type:chat:thread:user`.
- Streams by editing the sent message.
- Busy modes: interrupt, queue, steer.
- A crash-safe, at-least-once **delivery ledger**.
- Voice memos transcribed on the way in; optional TTS on the way out.
- A bot-loop guard.
- Per-channel model and prompt overrides.
- Webhook ingress with HMAC and idempotency.
- **Relay**: the gateway dials out to a connector and holds no platform tokens.
- A2A v1.0.

**Platforms.** 27 plugin adapters:
- a2a, bluebubbles, buzz, dingtalk, discord, email;
- feishu, google_chat, irc, line, matrix (with E2EE), mattermost;
- ntfy, photon, qqbot, raft, signal, simplex;
- slack, sms, teams, telegram, wecom, weixin;
- whatsapp, whatsapp_cloud, yuanbao.

Also `api_server`, `webhook` and `msgraph_webhook`.

**Cron:**
- Schedules: natural language ("every monday 9am"), 5-field cron, ISO one-shots, "in 30m".
- Delivery: `platform:chat`, the home channel, the origin, or all.
- **Monitor mode:** skips the run when the source hash is unchanged.
- A per-job notepad.
- Skill **blueprints**: a schedule declared in `SKILL.md` frontmatter.
- Catch-up, an idle watchdog, and the `chronos` scale-to-zero provider.

**Kanban:**
- SQLite boards with columns triage, todo, scheduled, ready, running, blocked, review, done.
- A dispatcher and a review loop.
- PR acceptance via `gh`.
- A swarm topology and worker lanes.

**API server** (`gateway/platforms/api_server.py:62-81,1555-1592`):
- `/v1/chat/completions`, `/v1/responses`, `/v1/models`;
- `/v1/runs`, with events, approval, steer and stop;
- REST for sessions and cron.

**TUI:**
- Ink over typed JSON-RPC, with TypeScript generated from Pydantic.
- List, tail, steer and interrupt subagents.
- Compose in `$EDITOR`.
- 104 slash commands (`hermes_cli/commands.py:81-348`), each with its own `busy_policy`.

**Desktop app (Electron):**
- chat panes;
- git review and worktrees;
- a memory graph;
- Bot Mode: group rooms of 2 to 6 bots, plus bot-to-bot messaging;
- Bot Screen;
- connections to local, URL, SSH and cloud gateways at once;
- a Webapp mode.

**Web dashboard:**
- 19 pages.
- The chat page embeds the real TUI over a PTY.
- Auth is forced on for any non-loopback bind.

**ACP.** Runs as a viewer of the gateway. Works from VS Code, Zed and JetBrains.

**i18n.** 17 locales.

**Distribution:**
- installers: `install.sh`, `install.ps1`, MSIX;
- packages: Termux APT, Nix, Docker with s6;
- a transactional fleet updater with a downgrade guard;
- release channels: preview, stable, canary, source-branch;
- a `pm/` lockfile with a SHA-256 per target.

### 2.9 Quality apparatus

**Tests:**
- 7,259 test files.
- Each test file runs in its own process (`scripts/run_tests.sh`).
- Hermetic: credentials unset, `TZ` set to UTC, `HERMES_HOME` pointed at a temp directory.
- Tests are behaviour contracts only.

**Code-health ratchet** (master switch read from `main`):
- cyclomatic complexity ≤ 20;
- ≤ 300 lines per unit;
- nesting ≤ 6;
- files ≤ 2,000 lines.

**Lint and CI:**
- HX001-HX013 lint rules;
- CI lanes for live-provider canaries and prompt-surface-diff.

**Evals.** `evals/` holds about 156 files of A/B probes: compaction recall, tool_search, prompt footprint, provider wire. **No task-quality benchmarks** were found in the searched surface.

---

## 3. Weebot today

Inventory at HEAD `b4ee83bb`. Tags:
- **[LIVE]**: wired into the production path.
- **[FLAG-OFF]**: wired, but off by default.

**Loop:**
- `PlanActFlow` runs 15 state classes [LIVE]: idle, chat_message, planning, plan_review, premortem, critiquing, product_gate, executing, reviewing, updating, verifying, meta_analysis, summarizing, completed.
- Around it:
  - `FlowRouter` chooses the plan flow or the chat flow;
  - a CQRS mediator;
  - an AUTO mode that skips human pauses.
- **Executor iteration guard** (`weebot/application/agents/executor/_iteration_guard.py`):
  - 24 tool calls per step;
  - a repeated-signature limit of 4;
  - a repeated-assistant limit of 2.
- **Plan-level undo stack** (`weebot/application/flows/plan_act_flow.py:578`).

**LLM [LIVE]:**
- **Providers:** `AdapterFactory` supports openai, anthropic, deepseek, moonshot, minimax, xai, openrouter, ollama and free tiers (`weebot/infrastructure/adapters/llm/adapter_factory.py:248-358`).
- **Resilience:** `ResilientLLMAdapter`.
- **Cascade:** `CascadeExecutor` runs FREE, then BUDGET, then PREMIUM:
  - per-model circuit breakers;
  - hedged probes;
  - free tiers excluded after untrusted content.
- **Catalog:** generated, refreshed 2026-11-03.

**Caching: PARTIAL.**
- OpenRouter top-level `cache_control` is sent for `anthropic/*` when tools are present (`openai_adapter.py:218-230`).
- `_CACHING_MODEL_MARKERS` cannot match Claude 5.x names (`caching_llm_adapter.py:26-30`).
- `LLM_ENABLE_CACHING` defaults to False.
- Per-step BM25 skill text is rebuilt into the system prompt.

**Compression [LIVE].** `ConversationCompressor` keeps the first 3 and last 6 messages and summarizes the middle. Both counts are in messages, not tokens.

**Memory:**
- `persistent_memory` (AGENT.md / USER.md) [LIVE]. It is re-read every step, not frozen.
- MemoryLifecycle hot/warm/cold sweep [LIVE].
- Knowledge graph [FLAG-OFF].
- Episodic memory [FLAG-OFF].
- User model [LIVE-ish].
- Behavioral learner [LIVE].
- FTS5 event search [LIVE].

**Learning:**
- skill distiller, review gate and materializer, all on by default;
- daily skill curator;
- skill_opt and harness_opt flows;
- CoVe promotion gate [FLAG-OFF].

**Skills:**
- 26 built-in skills.
- Importers:
  - ClawHub, which forces quarantine;
  - awesome-agent-skills;
  - a GitHub index.
- Retrieval: BM25, plus semantic search, plus a reranker.

**Tools:**
- about 50 tools across 12 roles (`weebot/application/services/tool_registry.py`);
- scoped tool retrieval (ADR-008);
- `tool_call_repair`;
- output truncated at 20 K characters.

**Execution:**
- Sandbox backends: native_windows, wsl2, docker_linux, modal.
- Only Docker enforces network-off.
- `python_execute` runs one-shot. No code-to-tool RPC was found.

**Browser:**
- Playwright, through `BrowserPort`;
- a SoM renderer;
- CDP, including Lightpanda, which fails closed;
- camofox.

**Desktop:**
- `computer_use`, `desktop_a11y` and a Windows desktop adapter. All lean toward Windows.
- An OSWorld benchmark harness.

**MCP:**
- **Client [LIVE].** Transports: stdio, http, sse, streamable-http. Outbound tools always ask.
- **Env leak.** Each MCP subprocess gets `env={**os.environ, **env}`, the full environment (`weebot/infrastructure/mcp/mcp_client_manager.py:163`).
- **Missing.** No sampling, elicitation or OAuth was found in the searched surface.
- **Server.** Exposes bash, python and file tools, with Bearer auth.

**Delegation:**
- Patterns:
  - `dispatch_parallel_tasks`;
  - `workflow_orchestrator`;
  - `swarm`;
  - `debate`;
  - `mixture_of_agents`;
  - `hyper_agent`;
  - `SubAgentFactory`.
- All link child cost to the parent.
- **No depth cap.**
- Sub-agents get the `admin` role (`weebot/application/di/__init__.py:683-688`).

**Gateways:**
- Telegram, Slack, Discord, WhatsApp, Signal, Email.
- Allowlist only. `weebot/core/gateway_auth.py:4` claims DM pairing, which is not implemented.

**Cron:**
- APScheduler, with persistence and catch-up;
- a `schedule` tool;
- a cron CLI;
- a delivery service.

**Web UI and API:**
- **Next.js `weebot-ui`:**
  - pages: sessions, behavior, models, ops, settings, debug;
  - a plan checklist and a command palette;
  - SSE and WebSocket.
- **FastAPI:**
  - binds to loopback by default;
  - Host and Origin guard;
  - rate limit per principal;
  - session ownership checks.
- **No OpenAI-compatible endpoint.**

**Security:**
- `bash_guard` with 4 tiers, plus the 4-layer `CommandSecurityAnalyzer`;
- `ExecApprovalPolicy`: single-use, journaled approvals (ADR-013);
- `EgressGuard`;
- **D5 taint:** after an untrusted read, anything that is not a read asks;
- `write_target` path policy;
- `SecretAccessor`, plus redaction;
- sandbox env scrub.

**Observability:**
- structlog;
- Prometheus;
- an OTel sink [FLAG-OFF];
- a session cost meter that asks before exceeding the budget.

**Evals:**
- an eval runner and judges;
- harness suites;
- a regression gate;
- OSWorld.

**Architecture enforcement:**
- 10 import-linter contracts;
- fitness tests;
- exact-equality ceilings;
- the ICM `map/`.

**Persistence:**
- SQLite in WAL mode;
- optional Postgres (alembic migrations);
- a durable event journal;
- an optional Valkey bus;
- resume;
- a cross-process cancel marker.

**Distribution and other:**
- Distribution is Docker and compose only.
- `ProfileManager` exists, but there is no per-profile secret scope.
- No i18n.
- No entry-point plugins. Extension today is hooks, personas, skills and MCP.

---

## 4. Side-by-side matrix

Verdict key:
- **W**: Weebot ahead.
- **=**: parity.
- **H**: Hermes ahead. The gap id refers to §7.

| # | Dimension | Hermes v0.22 | Weebot | Verdict |
|---|---|---|---|---|
| 1 | Planning | ReAct, todo, prompt-only `/plan`, `/goal` judge | 15-state FSM: critique, premortem, product gate, verify, replan | **W** (take the `/goal` judge: H27) |
| 2 | Loop guardrails | Cycles up to period 4, duplicate stubs, cost-aware empty retry, repetition, liveness, auto-recover | Signature repeat, assistant repeat, per-step cap | **H** (H11) |
| 3 | Prompt caching | An invariant: 3-tier stable prompt, `tools[]` pinned, injections in user messages, 4 breakpoints, TTL auto, CI diff | OpenRouter `cache_control` only; markers stale; skills rebuilt into system prompt | **H** (H2, H10) |
| 4 | Compression | No-LLM prune, token-budget tail, aux summary, fallback; in place; prepared ahead; checkpoint gate | Message-count summary: head 3, tail 6 | **H** (H9) |
| 5 | Error recovery | 30 reasons, ladder of ≥ 21 stages, falls back to another model rather than another key | Classify, fail fast, next cascade tier; no compress-on-overflow | **H** (H3) |
| 6 | Providers | 39 profiles, 5 api_modes, models.dev, credential pools, ≥ 16 aux slots | 8 providers plus free tiers plus OpenRouter (300+ models); tiered cost cascade | **=/W** on cost; **H** on pools and aux (H13, H25) |
| 7 | Memory | Frozen snapshot, 22-hook provider ABC, catalog providers, pre-compress checkpoint | Richer kinds (KG, episodic, user model, behavioral), re-read every step; KG and episodic off | **=** concepts; **H** discipline (H10, H24) |
| 8 | Learning loop | Background fork about every 10 turns; shares cache; tool whitelist | Distiller, review gate, materializer, daily curator | **=** (H24 for provenance) |
| 9 | Skill governance | Trust tiers, guard, AST audit, locks, ledger with rollback, hub over several registries, 193 skills | Quarantine on ClawHub import; scanner on the CLI path only; 26 skills | **H** (H14) |
| 10 | Session search | 3 FTS indexes (unicode61, trigram, CJK), 4 modes, no LLM | FTS5 over events, called directly | **H** (H15) |
| 11 | Tool registry and dispatch | AST discovery, `check_fn` TTL, arg coercion, middleware, transform hooks | Role scoping (ADR-008), `tool_call_repair`, `guard_tools` | **=** (H16: coercion and middleware) |
| 12 | Progressive disclosure | tool_search bridge, degrading manifest | ADR-008 scoped retrieval and composite tools | **=** (different designs, both valid) |
| 13 | Output hygiene | Caps, head/tail split, spillover to disk, per-turn budget | Truncation at 20 K | **H** (H7) |
| 14 | File editing | 9-strategy fuzzy patch, V4A, stale-overwrite guard, file-state registry, lint | `file_editor` | **H** (H6) |
| 15 | LSP diagnostics | 28 servers, delta only, deferred, trust-gated | None found | **H** (H20) |
| 16 | File checkpoints and undo | Shadow-git per turn with rollback; `/undo`, `/retry`, `/branch` | Plan undo only | **H** (H5, H21) |
| 17 | Code execution | Persistent kernel with tool RPC; stdout only | One-shot `python_execute` in the sandbox | **H** (H17) |
| 18 | Execution backends | local, docker, ssh, modal, daytona, vercel, plus plugins | native_windows, wsl2, docker, modal | **H** breadth; **W** on Windows (H22) |
| 19 | Approvals | Floors before YOLO, guardian LLM, once/session/always, unattended deny, circuit breaker | 4-tier guard, analyzer, single-use journaled approvals, D5 taint | **=** (W on taint; H18 for guardian and scopes) |
| 20 | Egress | iron-proxy token swap, default deny | `EgressGuard` allowlist; Docker network off | **H** (H23) |
| 21 | Secrets | Secret sources, model-blind vault, scope that fails closed, subprocess scrub | `SecretAccessor`, redaction, sandbox scrub; **MCP env leak** | **H** (H1, H19) |
| 22 | Browser | `browser_exec` over CDP, endpoint ladder, cloud, vault, dialog supervisor | Playwright, SoM, CDP, Lightpanda, camofox | **=** (H19 vault, H31 cloud) |
| 23 | Computer use | Cross-OS, background delivery, control lease, Bot Screen | Windows-leaning; OSWorld harness | **=/H** (H32) |
| 24 | MCP client | OAuth, sampling, elicitation, trust and spend gates, OSV preflight, schema cache, 66 manifests | 4 transports, asks on outbound; no sampling, elicitation or OAuth | **H** (H1, H12) |
| 25 | MCP server | Plugin; serves conversations and approvals; no exec by default | Exposes bash, python and file tools; Bearer auth | **=** (H34: harden) |
| 26 | Delegation control | Depth cap, blocked tools, steer/stop, `output_schema`, worktree, durable async, routes | Rich patterns, cost linkage; no cap; children are admin | **W** patterns; **H** control (H4, H26) |
| 27 | Kanban board | Full board, dispatcher, review loop, PR acceptance | `workflow_orchestrator` | **H** (H36, optional) |
| 28 | Messaging breadth | 27 adapters, webhook, Relay, A2A | 6 adapters | **H** (H28: build the mechanism) |
| 29 | Gateway runtime | Streaming edits, busy modes, delivery ledger, voice memos, home channel, mirror, loop guard | Allowlist; approvals through flow pause | **H** (H8, H29) |
| 30 | Gateway auth | Default deny, pairing, admin/user tiers | Allowlist; false pairing claim | **H** (H8) |
| 31 | Cron | Natural-language schedules, monitor mode, notepad, blueprints, delivery targets | APScheduler, catch-up, `schedule` tool, delivery | **=** (H30) |
| 32 | API server | OpenAI-compatible `/v1/*`, plus runs, steer, stop | Custom FastAPI | **H** (H12b) |
| 33 | TUI, desktop, IDE | Ink TUI, Electron, Bot Mode, ACP | Next.js web UI and CLI | **H** (H37, H38) |
| 34 | Web dashboard | 19 pages; chat over a PTY; auth forced off loopback | 6 page groups, plan checklist, behavior | **=** (H35: more pages) |
| 35 | Verification | Evidence ledger, verify-on-stop (opt-in), `hermes verify` | Verifying state, CoVe, reviewing, product gate | **W** (H20b: evidence ledger) |
| 36 | Plugins | ~45 hooks, middleware, host isolation, capability consent, SHA catalog, kill list | Hooks, personas, skills, MCP; no entry points | **H** (H33) |
| 37 | Profiles and tenancy | Profile islands, one gateway for all profiles, secret scope that fails closed, distributions | `ProfileManager`; basic multi-user web | **H** (H39) |
| 38 | Voice | 11 TTS, 10 STT, wake word, streaming, Discord voice | Whisper; pyttsx3 or OpenRouter TTS | **H** (H40) |
| 39 | Observability | Content-free OTLP health events | structlog, Prometheus, OTel sink, cost meter | **W** (turn OTel on) |
| 40 | Evals | A/B probes, live canaries, prompt-surface diff | Eval runner, judges, harness opt, regression gate, OSWorld | **W** (take the prompt-surface diff: H10) |
| 41 | Training data | `batch_runner`, trajectory compressor | Exporter only | **H** (low priority) |
| 42 | Architecture and code health | Per-unit complexity ratchet, HX rules | 10 import contracts, fitness tests, ceilings, ICM map | **W** (take the per-unit ratchet) |
| 43 | Ops, distribution, i18n | Installers, transactional updater, release channels, OSV audit, 17 locales | Docker, doctor, upgrade CLI; no i18n | **H** (H25 OSV audit; rest optional) |

---

## 5. Where Weebot already excels (keep these; do not flatten them)

1. **Explicit planning FSM.** Critique, premortem, product gate and verification states. Hermes still has no plan object. Weebot's answer to the `/goal` judge is a state, not a prompt.
2. **Cost cascade.** FREE, then BUDGET, then PREMIUM, with breakers and hedged probes. Free tiers are dropped after untrusted content. Hermes has fallback, but no cost-first routing.
3. **Taint tracking (D5).** After an untrusted read, every action that is not a read needs approval. Hermes treats prompt injection as out of scope.
4. **Evaluation and self-optimization.** Harness opt, skill opt, a regression gate and OSWorld. Hermes's `evals/` are infrastructure probes only.
5. **Architecture enforcement.** Hexagonal layers, import-linter, fitness tests and the ICM map. Hermes relies on review culture plus complexity ratchets.
6. **Observability.** structlog, Prometheus and OTel. Hermes has added only content-free OTLP health events.
7. **Windows-native sandboxing.** native_windows and wsl2 backends, plus a Windows desktop adapter.
8. **Multi-agent patterns.** Swarm, debate, MoA, workflow orchestrator and hyper-agent.

---

## 6. Status of earlier recommendations

### 6.1 v0.19 study items (checked against code at `b4ee83bb`)

| Item | Status | Evidence |
|---|---|---|
| AgentWasp jobs never load | LANDED | `31079361`; `weebot/scheduling/default_jobs.py:383`; started at `weebot/interfaces/web/main.py:251-253` |
| `_create_if_absent` not awaited | LANDED | `5e4cf017`, `afdb6447` |
| Sub-agent `state_repo=None` | LANDED | `122456a8`; `di/__init__.py:703-708` |
| Dead CoVe service | LANDED (flag off) | `78bcc65f`; `SKILL_PROMOTION_GATE_ENABLED` defaults to False |
| God methods | LANDED | `9ef23ae7` |
| One model catalog (B10) | LANDED | `85bce52d`; refreshed in `73f82e04` |
| Delete the lying `delegate_task` (B5) | LANDED | `a77775d4` |
| KG wired | PARTIAL (flag off) | `feature_flags.py:102-104` |
| Prompt caching (G1/B9) | PARTIAL | Markers stale at `caching_llm_adapter.py:26-30` (re-read) |
| Recovery ladder (G2/B13) | NOT DONE | `should_compact` and `should_fallback_model` have zero callers (re-grepped) |
| MCP env allowlist (G6/B16) | NOT DONE | `mcp_client_manager.py:163` (re-read) |
| Gateway pairing (G5/B17) | NOT DONE | Allowlist only; the docstring claim is at `weebot/core/gateway_auth.py:4` |
| Delegation depth cap (G7/B18) | NOT DONE | No depth term in the delegation modules (re-grepped) |
| Skills supply chain (G3/B19) | PARTIAL | Quarantine on import only |
| FTS trigram (B20) | NOT DONE | — |
| MCP sampling and elicitation (B21) | NOT DONE | — |
| Trajectory flywheel (B22) | NOT DONE | — |
| Execution backends (B23) | PARTIAL | Modal landed in `85229df2`; no SSH |
| DI fitness test asserts | NOT DONE | `tests/unit/test_architecture_fitness.py:295-303`; the lint scripts compensate |

### 6.2 `weebot_unified_implementation_plan.md` P1-P4

The plugin platform, Environment port, ACP bridge and credential pool are all still pending (`tasks/_index.md:30`). This study folds them into H33, H22, H38 and H13.

---

## 7. Parity backlog: what to integrate, in order

Each item names:
- the Hermes mechanism to port;
- where it lands in Weebot;
- a rough size;
- why it matters.

Sizes: S ≤ 1 day; M ≤ 1 week; L > 1 week.

Repo rules apply to every item:
- Use ports plus DI, never ad-hoc construction.
- Use `SecretAccessor`, never bare `os.environ`.
- A new flag defaults to off only where the risk is real.
- Lower a ceiling when the debt is paid.

### Phase 0: carry-over correctness and security (≈ 1 week; do first)

| ID | Integrate | Weebot landing | Size | Why |
|---|---|---|---|---|
| **H1** | Env allowlist for MCP stdio servers, as in Hermes `build_subprocess_env` (`tools/AGENTS.md:114-124`). Pass only `PATH`, locale, `HOME`/`USERPROFILE`, `SYSTEMROOT` and the server's declared `env` | `weebot/infrastructure/mcp/mcp_client_manager.py:163`; reuse the sandbox env-scrub helper | S | **Live leak:** every MCP server receives every provider key |
| **H2** | Fix cache gating. Replace substring markers with a family check (`claude-`, excluding `claude-2` and `instant`). Default `LLM_ENABLE_CACHING` to on for Anthropic routes | `caching_llm_adapter.py:26-30`, `adapter_factory.py:104` | S | Caching is off on every current Claude model |
| **H3** | Error-recovery ladder:<br>• context overflow → compress, then retry once (wire `should_compact`);<br>• upstream 429 → next model, not the same one (wire `should_fallback_model`);<br>• add a `FailoverReason`-style enum with payload-too-large and multimodal-unsupported | `weebot/core/error_classifier.py:135,145`, wired into `executor/_cascade.py` and `resilient_adapter.py` | M | Today a context overflow is retried byte-identically |
| **H4** | Delegation policy:<br>• depth cap: default 1, configurable to 2;<br>• max concurrent children and a child timeout;<br>• children get a non-admin role: no `dispatch_*`, `swarm`, `ask_human`, `schedule`, or `persistent_memory` writes | New `DelegationPolicy` in `application/services`, applied in `SubAgentFactory` and `di/__init__.py:683-688` | M | Recursion and spend are unbounded; children run as admin |
| **H5** | Shadow-git file checkpoints. Snapshot the workdir once per turn, before the first mutating tool call. Add `weebot rollback <n>` and a UI button | New `CheckpointPort` and adapter: git plumbing, store under `data/checkpoints`. Call it from `guard_tools` before execution | M | Weebot can undo a plan but not a file edit |

### Phase 1: token economics and context (≈ 2-3 weeks)

| ID | Integrate | Weebot landing | Size | Why |
|---|---|---|---|---|
| **H9** | Compression v2:<br>1. no-LLM pruning of old tool results first;<br>2. token-budgeted tail (`target_ratio` 0.20, `protect_last_n`), keeping each tool call with its result;<br>3. trigger at 50%, or 75% for windows under 512 K;<br>4. deterministic fallback summary;<br>5. re-inject the todo list and plan summary after compaction | `weebot/application/services/conversation_compressor.py`, `executor/_context_compressor.py` | M | Count-based tails undercount tool-heavy turns |
| **H10** | Prompt-prefix invariant:<br>• a `PromptPrefixStore` that keeps one hashed, stable system prompt per step;<br>• move BM25 skill text, memory recall and taint notes into the user/context message;<br>• a fitness test that the system-prompt hash stays stable across iterations of a step;<br>• a CI job that diffs the rendered system prompt and tool schemas on every PR, as Hermes `prompt-surface-diff.yml` does | `executor/_prompt_builder.py`; a new port in `domain/ports`; a script in `scripts/` plus a workflow | M | Caching only pays when the prefix is byte-stable |
| **H7** | Tool-output spillover:<br>• above the cap, write the full output to `data/spillover/<session>/<call>.txt`;<br>• return a head/tail preview plus the path;<br>• enforce a per-turn output budget | `weebot/tools/base.py`, at the truncation guard | S | Keeps output the model may need; `file_editor` can page through it |
| **H11** | Loop guardrails:<br>• A-B-A-B cycle detection, period ≤ 4;<br>• reference stubs for duplicate results;<br>• a cost-aware cutoff for empty-response retries;<br>• a repetition guard;<br>• a wrap-up note at 80% of the wall-clock budget | `executor/_iteration_guard.py` | S-M | Cheap; cuts wasted iterations |
| **H15** | FTS trigram and search modes:<br>• add an `events_fts_trigram` table that excludes tool rows;<br>• route `search_history` through `SessionSearchService`;<br>• add discover, scroll and read modes | `weebot/tools/search_history.py:49`, plus a persistence migration | S | Recall for substrings and non-Latin text; v0.19 B20 |
| **H16** | Two dispatch upgrades:<br>• schema-guided arg coercion (`"42"` → int, JSON-string arrays, scalar → array) ahead of `tool_call_repair`;<br>• a middleware chain on `ToolCollection.execute`: `pre_tool_call`, `post_tool_call`, `transform_tool_result` | `weebot/application/services/tool_call_repair.py`, `tool_collection.py` | S | Fewer failed tool calls on cheap models, which the cascade depends on |

### Phase 2: tool depth (≈ 3-4 weeks)

| ID | Integrate | Weebot landing | Size | Why |
|---|---|---|---|---|
| **H6** | Edit pipeline:<br>• a fuzzy `patch` chain: exact → trimmed lines → whitespace → indentation → escape → unicode → block anchor;<br>• refuse stale overwrites, using a registry of read stamps;<br>• auto syntax-lint after every write | `weebot/tools/file_editor.py`, plus a `file_state` service | M | Edit-failure loops are the top waste on coding tasks |
| **H17** | Persistent Python kernel with tool RPC:<br>• one kernel per session inside the sandbox, LRU cap of 4;<br>• a stub module calls `web_search`, `file_*` and `bash` over loopback TCP with a session token;<br>• only stdout returns to the model;<br>• iterations used inside it are refunded | `weebot/tools/python_execute` and `SandboxPort`; use TCP on Windows | L | Collapses N tool calls into one turn; Hermes's best cost lever |
| **H20** | LSP delta diagnostics (opt-in):<br>• compare diagnostics before and after each write;<br>• report only what the edit introduced;<br>• non-blocking, with late results delivered later;<br>• start with pyright, typescript-language-server and ruff-lsp | New `LspPort` and infrastructure adapter; hook after `file_editor` writes | M | Catches breakage before the verify state |
| **H20b** | Verification evidence ledger:<br>• record which build and test commands actually ran in each session;<br>• the `verifying` state requires fresh evidence after edits | `flows/states/verifying.py`, plus persistence | S | Turns "claims it tested" into "did test" |
| **H18** | Approval upgrades:<br>(a) floors that AUTO mode cannot bypass, plus user deny globs matched against deobfuscated variants;<br>(b) once, session and always scopes on top of single-use;<br>(c) a guardian LLM that returns approve, deny or escalate, for the SUSPICIOUS tier only, one command per approval;<br>(d) a per-session denial circuit breaker;<br>(e) unattended contexts (cron, gateways with no human) default to deny | `weebot/core/bash_guard.py`, `ExecApprovalPolicy`, `CommandSecurityAnalyzer` | M | Fewer prompts, without weakening D5 |
| **H21** | Conversation `/undo`, `/retry` and `/branch`:<br>• rewind session events to a boundary;<br>• re-run the last turn;<br>• fork a session at a message | Session repository, web UI, gateway commands | M | Basic UX that Hermes users expect |

### Phase 3: MCP, secrets, egress (≈ 3 weeks)

| ID | Integrate | Weebot landing | Size | Why |
|---|---|---|---|---|
| **H12** | MCP client depth:<br>• wire the existing `MCPSamplingHandler`, with rpm, token and model caps;<br>• route elicitation through `ask_human`;<br>• OAuth 2.1 (DCR + PKCE), tokens stored through `SecretAccessor`;<br>• per-server `trust: untrusted`, so write tools ask;<br>• a lazy schema cache;<br>• an OSV check before spawning `npx` or `uvx` | `weebot/infrastructure/mcp/` | M-L | Remote MCP servers need OAuth; v0.19 B21 |
| **H12b** | OpenAI-compatible API:<br>• `/v1/chat/completions` with streaming, and `/v1/models`;<br>• `/v1/runs/{id}/events`, `/approval` and `/stop`;<br>• `API_SERVER_KEY` auth and idempotency keys | New router in `weebot/interfaces/web`, on top of `CommandMediator` | M | Open WebUI and any OpenAI client become Weebot front-ends for free |
| **H19** | Secrets:<br>• a `SecretSourcePort` behind `SecretAccessor`, with 1Password (`op://`) and Bitwarden (`bws`) resolvers: read-only, resolved at startup, with a timeout and provenance;<br>• a browser vault the model never sees: it gets opaque handles, and the adapter fills fields over CDP | `weebot/core` (`SecretAccessor`), `BrowserPort` | M | Keeps passwords out of transcripts and credentials out of `.env` |
| **H23** | Egress credential swap on the Docker backend:<br>• the sandbox holds only opaque tokens;<br>• an L7 proxy swaps them for real keys, on allowlisted hosts only;<br>• start from the same open-source proxy approach as Hermes's iron-proxy, pinned by SHA | Sandbox docker backend, `EgressGuard` | L | A prompt-injected sandbox cannot exfiltrate keys |
| **H13** | Credential pools:<br>• N keys per provider;<br>• fill_first, round_robin and least_used strategies;<br>• 429 cooldowns scoped per model;<br>• integrated with the breakers in `CascadeExecutor` | `adapter_factory.py`, `_cascade.py` | M | Unified plan P4; more throughput on free tiers |

### Phase 4: gateway and automation (≈ 3-4 weeks)

| ID | Integrate | Weebot landing | Size | Why |
|---|---|---|---|---|
| **H8** | Gateway auth:<br>• default deny;<br>• DM pairing: 8-character `secrets` code, 1 h TTL, 10 min rate limit per user, lockout after 5 failures, stored per profile;<br>• admin and user command tiers, plus `/whoami`;<br>• fix the false docstring | `weebot/core/gateway_auth.py`, plus a new `GatewayPairingService` | M | v0.19 B17; the docstring currently claims pairing that does not exist |
| **H29** | Gateway runtime:<br>• streaming by editing the sent message;<br>• busy-input modes: interrupt, queue, steer;<br>• a crash-safe, at-least-once delivery ledger;<br>• voice memos transcribed in, optional TTS out;<br>• home channel and `/sethome`;<br>• a bot-loop guard;<br>• per-channel model and prompt overrides;<br>• one shared slash set: `/new /stop /model /status /approve /deny /undo /retry /compress /usage` | A shared base under `weebot/interfaces/gateways/*` | L | This is what makes Hermes feel "alive" in chat |
| **H28** | Platform adapter contract:<br>• one plugin interface: connect, receive, send, edit, typing, attachments, capabilities;<br>• an entry-point registry;<br>• first adapters, chosen by user demand: Matrix, Microsoft Teams, Google Chat, a generic webhook (HMAC + idempotency), ntfy (push), SMS (Twilio);<br>• leave the China-only platforms to plugins | `weebot/interfaces/gateways`, plus entry points in `pyproject` | M, plus S per adapter | Breadth comes from the mechanism, not from growing the core |
| **H30** | Cron upgrades:<br>• natural-language schedules ("every monday 9am", "in 30m");<br>• delivery targets: `platform:chat`, home, origin, all;<br>• **monitor mode**: skip the agent run when the source hash is unchanged;<br>• a per-job notepad;<br>• skill **blueprints**: a schedule declared in `SKILL.md` frontmatter | `weebot/scheduling/`, `cron_delivery_service`, the skills loader | M | Cheaper, more useful unattended jobs |
| **H27** | Persistent goal and `/btw`:<br>• a session goal; after each completion, a cheap judge model decides continue or stop;<br>• `/btw`: a side question that runs in a fork, shares the cached prefix, and has tools denied | `flows/states/completed.py` or `meta_analysis`; a new mediator command | S-M | Long-horizon autonomy, without flattening the FSM |

### Phase 5: extensibility and supply chain (≈ 4 weeks)

| ID | Integrate | Weebot landing | Size | Why |
|---|---|---|---|---|
| **H33** | Plugin platform:<br>• Python entry points plus a `plugin.yaml` manifest that declares kind and capabilities;<br>• a `PluginContext` exposing `register_tool`, `register_hook`, `register_middleware`, `register_command`, `register_platform`, `register_memory_provider` and `register_secret_source`;<br>• **capability consent**, stored with a hash;<br>• a behavioural compatibility promise;<br>• optional child-process isolation, later | New `application/plugins` plus a port. Supersedes unified plan P1 | L | Lets breadth grow without touching the core |
| **H14** | Skills supply chain:<br>• trust tiers (builtin, trusted, community, agent-created) with an install-policy matrix;<br>• `SkillSecurityScanner` on **every** install path;<br>• a lockfile recording source and SHA;<br>• a mutation ledger with content-addressed backups and single-edit rollback;<br>• user locks on skills;<br>• provenance: foreground write vs background write | Importers under `weebot/application/skills/`, plus `SkillRegistry` | M | v0.19 G3: agent-written skills are a supply chain |
| **H24** | Memory discipline:<br>• freeze AGENT.md and USER.md into a per-session snapshot; writes go to disk and are read next session; this keeps the prefix stable;<br>• a `MemoryProvider` port with `on_pre_compress`, `on_delegation` and `on_session_switch`;<br>• turn on KG and episodic memory after a cost check | `weebot/tools/persistent_memory.py`, `domain/ports` | M | Supports H10, and makes external memory backends pluggable |
| **H25** | `weebot security audit`:<br>• check the venv, MCP server pins and skill requirements against OSV.dev;<br>• doctor advisories, dismissed with `--ack` | `cli/` and `doctor` | S | Cheap supply-chain hygiene |
| **H26** | Delegation control:<br>• steer, stop and list running children;<br>• `output_schema` validation with one retry;<br>• optional git worktree per child;<br>• a durable async-delegation ledger, with `recover_abandoned()` at boot;<br>• routing per task (model, profile) | `SubAgentFactory`, `dispatch_agents.py`, persistence | M-L | Brings Weebot's delegation patterns up to Hermes's level of control |

### Phase 6 and later: selective breadth (open-ended; build only with demand)

| ID | Integrate | Note |
|---|---|---|
| H22 | SSH backend (ControlMaster; file sync by mtime and size), then Daytona | Unified plan P2: Environment port |
| H31 | Cloud browser providers (Browserbase, Browser Use), with hybrid routing: public URLs go to the cloud, LAN URLs stay local | New `BrowserPort` adapters |
| H32 | Cross-OS `computer_use` through an MCP desktop driver, with background delivery and a human/agent control lease | Keep the OSWorld harness as the gate |
| H34 | Harden the Weebot MCP server: exec tools off by default; expose conversations and approvals instead | `weebot/mcp/server.py` |
| H35 | Dashboard pages: cron, MCP servers, skills, plugins, pairing, logs, env/config | `weebot-ui` |
| H36 | Kanban board with dispatcher, review loop and PR acceptance | Only if multi-agent backlog work becomes a use case |
| H37 | Terminal UI (Textual) | Optional; the CLI and web UI already cover most of it |
| H38 | ACP adapter for VS Code, Zed and JetBrains | Unified plan P3 |
| H39 | Per-profile secret scope that fails closed, plus one gateway process per host serving all profiles | Needed before shared hosting |
| H40 | Voice breadth: Edge TTS (free) and faster-whisper by default, streaming TTS, wake word | |
| — | i18n (UI string catalogs), installers (`install.ps1`), transactional updater, release channels, trajectory batch runner | Low value for current users |

### Dependency notes

- **H10 needs H24 and H2.** It depends on H24's frozen memory snapshot and on H2's cache fix. Without both, caching gains stay small.
- **H17 needs loopback networking in `SandboxPort`.** Docker must allow loopback only. This stays within the network-off rule if the RPC socket is mounted rather than exposed over TCP.
- **H29 and H28 should share one gateway base class.** Either build H28's contract first, or move the six existing gateways onto it as part of H29.
- **H33 enables three other items.** Plugins are how H28 gets breadth, how H24 adds memory providers, and how H19 adds secret sources. If Phase 5 moves earlier, those items land as plugins rather than in core.

---

## 8. Do not import

These all stand from v0.19:
- **Pure ReAct with no plan object.**
- **"The OS is the only boundary."** Weebot's taint, approval and egress layers are a product advantage for a multi-user web UI plus gateways.
- **Wiring through a god-object with no DI.** Hermes split its god-files, but it still has no container.
- **Third-party products in the core.** Hermes itself moved Home Assistant, Spotify, Singularity and the memory providers out to its catalog.
- **Chasing 27 platforms or 977 catalog entries in core.**

---

## 9. Caveats

- **"NEW since v0.19"** rests on grepping the two earlier study files. Some features may predate v0.19 and simply were not covered by those studies.
- **Counts** come from directory listings and greps, not from running the code: 41 core tools, 39 providers, 28 LSP servers, ~45 hooks, 193 skills.
- **Platform count.** The interfaces deep-dive counted 31 platform directories. A direct `ls plugins/platforms` shows **27**.
- **Nothing was run.** Neither app was started, and Weebot's CI green state is unverified.
- **Large Hermes files were read only in part.** For `context_compressor.py`, `credential_pool.py` and `kanban_db.py`, only the docstrings and key regions were read.

## Appendix A: claims re-read by the lead reviewer

- `weebot/infrastructure/mcp/mcp_client_manager.py:163`: `env={**os.environ, **env}`.
- `weebot/infrastructure/adapters/llm/caching_llm_adapter.py:26-30`: the markers are `claude-3-5`, `claude-3-opus` and `claude-4`.
- `should_compact` and `should_fallback_model`: zero callers other than their definitions in `weebot/`.
- No `max_depth`, `spawn_depth` or `MAX_DEPTH` in `weebot/application` or `weebot/tools`.
- No code-execution RPC module in `weebot/`.
- Plan-level undo is at `weebot/application/flows/plan_act_flow.py:578`.
- Hermes `hermes_cli/__init__.py:5`: release date 2026.9.24.
- Hermes `hermes_cli/config_defaults.py:672`: `"in_place": True`.
- Hermes `tools/delegate_tool_config.py:19,23`: 10 concurrent children and `MAX_DEPTH = 1`.
- Hermes `plugins/platforms/` holds 27 adapter directories.
