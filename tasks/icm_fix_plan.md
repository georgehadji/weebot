# Plan: fix the findings recorded in the map cards

Status: IN PROGRESS. Written 2026-10-21 against commit `f00ea38`; Waves 0-2 and most of Wave 3 are done (results under each wave). The order for everything still open is in `tasks/remaining_fix_plan.md`.

Source of every finding: the `map/objects/` cards (each cites `path:line`). All findings were **read from source and not run**: `pydantic_settings` is missing here and `make` is not installed. So Wave 0 reproduces each one before anything is fixed. A finding that does not reproduce is a card error, and the card is corrected instead.

## 1. Rules this plan keeps

- Layering from `.importlinter` and `tests/unit/test_architecture_fitness.py` holds. No new `ignore_imports`; where a fix lets us delete one, it is deleted.
- Ceilings in `tasks/quality/ceilings.toml` never go up. New gates are ratchets with exact equality both ways (`scripts/quality_ceilings.py`).
- Agents return validated Pydantic output; `logger` not `print`; log inside every `except`; secrets through `SecretAccessor`; adapters registered in `weebot.application.di`.
- Fail closed stays the default for every security component.
- Smallest change that fully fixes the finding. A pattern is named only where it removes a real problem; otherwise the item says "no pattern, a one-line fix".
- One commit per task. Each task updates the card it touches (status, `verified`, `commit`) so the map stays true.
- Human gate after each wave.

## 2. Findings catalog

Severity: H = a security or correctness gap on a live path; M = wrong or misleading behaviour with a workaround; L = dead code, naming, docs. Confidence: all "read", upgraded to "repro" by Wave 0.

| ID | Finding | Card | Sev |
|---|---|---|---|
| F01 | `powershell` tool skips BashGuard and CommandSecurityAnalyzer; root `CLAUDE.md` rule 3 says all shell goes through BashGuard | BashGuard | H |
| F02 | Only BLOCKED stops `bash` and `python_execute`; DANGEROUS and SUSPICIOUS are logged; no code path asks a human | BashGuard, ExecApprovalPolicy | H |
| F03 | Analyzer SUSPICIOUS is logged only; the comment says the approval policy handles it, but the policy never sees the verdict | CommandSecurityAnalyzer | M |
| F04 | Chained-command override in `ExecApprovalPolicy.evaluate` returns before DENY rules, so `Format-Volume ...; rm x` is "ask", not "deny" | ExecApprovalPolicy | H |
| F05 | "Longest pattern string wins" is not specificity; `Set-Content`, `Copy-Item`, `Move-Item`, `Rename-Item` have no standalone rule | ExecApprovalPolicy | M |
| F06 | `finance` and `payment` categories have no live caller; setting `financial_tools_always_ask` has no reader | ExecApprovalPolicy, WeebotSettings | M |
| F07 | `ApprovalManager` has no runtime caller; `auto_approve_callback` / `auto_deny_callback` are sync but awaited, so they deny; `format_prompt` lacks `f` prefixes on two lines; BLOCKED can be approved when `auto_deny_blocked=False` | ApprovalManager | M |
| F08 | `EgressGuard.approve_recipient` has no caller; a blocked first-time host can only be allowed by hand-editing the allowlist file | EgressGuard | H |
| F09 | `python_execute` is not classified as egress; the sandbox does not contain it either (see F29); the MCP server calls tools directly (`weebot/mcp/server.py:355, 423, 449`) and `weebot/mcp` mentions no egress check (grep) | EgressGuard, Sandbox | H |
| F10 | Analyzer rule quality: entropy score inflated 1.2x "to match test expectations" (hex digests and long CamelCase tokens can reach DANGEROUS); layer 2 targets `\|`, `.`, `+x` unreachable; PowerShell allowlist uses `re.search`; unwired `_layer4_semantic_llm_analysis`; unused constants; docstring promises a timeout that does not exist | CommandSecurityAnalyzer | M |
| F11 | Override token is HMAC of the command only: no nonce, no expiry; secret read with bare `os.environ.get` | CommandSecurityAnalyzer | M |
| F12 | `post_bash_guard` hook payload marks `requires_approval` only for SUSPICIOUS, not DANGEROUS | BashGuard | L |
| F13 | `run_mcp.py:87` calls `WeebotSettings.validate_at_least_one_key()` on the class: `TypeError`, not caught by `except ValueError`; tests patch it away | WeebotSettings | H |
| F14 | `xai_api_key` is not counted by `validate_at_least_one_key` or `available_providers` | WeebotSettings | M |
| F15 | `reasoner_dir`, `berb_dir`, `scraper_dir` default to `E:\Documents\Vibe-Coding\...` | WeebotSettings | L |
| F16 | `WeebotSettings()` is built at 33 non-test sites, including once per inbound gateway message; module constants read `os.getenv` at import; `OSWorldSettings` shares the file | WeebotSettings | M |
| F17 | `plan_review_enabled` alias behaviour is unverified | WeebotSettings | L |
| F18 | `MODEL_CASCADE` does not drive `CascadeExecutor` (`model_refs.py` does); module docstring and root `CLAUDE.md` rule 4 say otherwise | ModelCascadeConfig, CascadeExecutor | M |
| F19 | Dead code in `model_cascade_config.py`: `get_model_for_task` in the docstring, `AGENT_ROLES`, the 128k loop, `very_long_context` | ModelCascadeConfig | L |
| F20 | Two classes named `ModelConfig`; model ids and prices live in three places | ModelCascadeConfig | M |
| F21 | `get_models_for_role_and_task` swallows every exception with `pass` (`model_refs.py:792-793`) | ModelCascadeConfig | L |
| F22 | `ops_router` passes queries to `Mediator.send` (HTTP 500 by reading) and builds a `Container` per request | Mediator | H |
| F23 | Cost views return no real data: handler ignores its repo and window, tracker is per executor, CLI `costs` is a placeholder, MCP gets no tracker, event store cost columns are never written, `get_cost_summary` and `EventLogger` have no caller | EventStore, Mediator | H |
| F24 | `ValkeyEventBus` publishes to Valkey but nothing reads the channels, so local subscribers get nothing when Valkey is reachable | EventBus | H |
| F25 | `PlanActFlow._executor` serves only the summarize fallback; the per-step executor built by `_executor_factory` gets container singletons only, not per-flow values (skill prompt, role, harness block, learner, middleware, trajectory config) | PlanActFlow, DIContainer | M |
| F26 | About 29 repository methods exist only on `SQLiteStateRepository` and are called by duck typing, including from `domain/services`; on another implementation they raise `AttributeError`, hidden by an `except` in the executor | SQLiteStateRepository | M |
| F27 | `list_opportunities`, `mark_opportunity_presented`, `accept_opportunity` have no caller | SQLiteStateRepository | L |
| F28 | `Container()` is built by hand at about 12 sites outside `di/`; `_maybe_get_str` swallows `KeyError`; `build_mediator` runs tool-less if the admin tool set fails | DIContainer | M |
| F29 | No production code builds a `SandboxConfig` with arguments, so every sandbox runs with network allowed, no memory limit, no mounts; `sandbox_allow_network` and `sandbox_max_output_bytes` settings have no reader | Sandbox, WeebotSettings | H |
| F30 | Network isolation is enforced by Docker only: WSL2 ignores `allow_network`, native sets dead proxy variables; Docker runs without `--cap-drop`, `--read-only`, `--user`, pid or CPU limits and, with no mounts, cannot see the workspace | Sandbox | M |
| F31 | `create_default_sandbox()` ignores the factory's Docker-first priority and skips the availability check | Sandbox | L |
| F32 | Registry autodiscovery reads `allowed_roles` with `getattr` on a Pydantic class and cannot take effect (inference); if it did, it would replace the role table and put exec tools in every role | RoleBasedToolRegistry | M |
| F33 | Registry shares mutable state: shallow copy of `DEFAULT_ROLE_MAPPINGS` mutated in place, class-level `_TOOL_TIERS` mutated by `set_tool_tier` | RoleBasedToolRegistry | M |
| F34 | Capability tiers (`get_tools_for_role_with_gate`, `get_tool_tier`) have no caller | RoleBasedToolRegistry | M |
| F35 | Registry builds a throwaway `Container()` per tool that needs one, inside silent `except Exception: pass`; discovery instantiates every tool with no arguments; unknown tool names are skipped with a warning | RoleBasedToolRegistry | M |
| F36 | The plan the user approves is not the plan that runs when DPPM planning is used. `PlanningState` replaces `context._plan` with the DPPM merge (`planning.py:256`) but emits no `PlanEvent`, and the resume restores the plan from the last `PlanEvent` (`Session.get_last_plan`, `plan_act_flow.py:634`). Seen in the real run of 2026-10-22: 8 DPPM steps were reviewed and approved, the 3 original steps ran. **Fixed 2026-10-22** (see the real-run check under Wave 3) | PlanActFlow | H |
| F37 | CLI `flow run` prints the `PlanReviewEvent` as a raw Python repr with `session_id=''`, then the plan again (observed in the real run, not traced) | PlanActFlow | L |
| F38 | MCP tools that write (Jira create/delete/transition, HubSpot batch create/update, Apify `call_actor`, Postiz uploads) did not ask: only `WEEBOT_OUTBOUND_TOOL_PATTERNS` names asked. **Fixed 89d20bd9**: MCP tools fail closed unless the name reads | IntegrationTools | H |
| F39 | An ASK a human approved was refused again by bash/powershell/python_execute (`requires_confirmation`), so no shell approval ever ran; python_execute had no ASK route at all. **Fixed 009cb41a** | ExecTools | H |
| F40 | `ToolCollection.teardown` never called `BaseTool.close()`; every browsing flow left Chromium running. **Fixed 138b033c** | Browser | H |
| F41 | Browser navigation is not egress: `EgressGuard` matches only submit/post actions; `advanced_browser` `goto`/`fill`/`click`/`evaluate`, `browser_inspector` `navigate` and `web_scraper` pass unchecked, even tainted. **Fixed d1b43463** | BrowserTools | H |
| F42 | A missing or misspelled skill `trust` loads as `trusted` (`skill_registry.py:129-131`), the only injection gate; imported ClawHub skills have no trust handling. **Fixed a409e2c9** | SkillRegistry | H |
| F43 | Gateway and `/api/webhook/run` flows are built with no mediator, so `PlanningState` errors and they cannot plan; same for sub-agent flows (`factories.py:333-341`). **Fixed 3abcb31e** | ChatGateways | H |
| F44 | `weebot` console script points at `cli.main:main`, which does not exist (`pyproject.toml:26`; entry is `_wrap_main`). **Fixed 900a1b6d** | CLI | H |
| F45 | The Next.js `/api` proxy makes every client loopback, and loopback skips auth; with no `WEEBOT_API_KEY` and the UI on `0.0.0.0:3000`, anyone reaching it can mutate. **Fixed 0dacf422** | WebUI | H |
| F46 | `apify_*` preset output is not untrusted: `trust_boundary.py:74` lists `apify_actor_tool`, the real names are `apify_web_scraper` etc., so scraped text is unfenced and not counted for egress. **Fixed 7cddbca6** | IntegrationTools | H |
| F47 | `product` tool is never built: it needs `repo`, which `tool_wiring` lacks; documentation and product_manager roles lose it. **Fixed d1fe8273** | IntegrationTools | M |
| F48 | Sub-agent tools (debate, swarm, dispatch, workflow, MoA) error in web, webhook and gateway flows: `build_tools` gets no `llm_port`, so no flow factory; MCP scoping rebuilds without one. **Fixed 086644c4** | OrchestrationTools | M |
| F49 | `dispatch_agents` and `workflow_orchestrator` call `state_repo.save_sync`, which exists nowhere, inside `except Exception: pass`. **Fixed 1b67da5d** | OrchestrationTools | M |
| F50 | `image_gen` (SVG, fallback, xAI base64), `video_ingest` export and `voice_output` write `output_path` without the workspace check. **Fixed ded2e53e** | MediaTools | M |
| F51 | `design_system` runs `npm install -g skillui` on failure without asking; output not fenced. **Fixed 3c1ca3f5** | IntegrationTools | M |
| F52 | Seven built-in skills ship only `manifest.json` and never load (incl. `multi_llm_orchestrator`, which root CLAUDE.md requires). **Fixed 8cc38eeb** | BuiltinSkills | M |
| F53 | Tools in no role that skills tell the agent to use: `youtube_download`, `desktop_a11y`; also roleless `detect_elements`, `screenshot_ocr`, `ocr_structured`, `web_scraper`; `browser_navigator` is in roles but not a `BaseTool`, so never built. **Fixed 5da0014b** | BrowserTools | M |
| F54 | Spending tools never ask: `apify_*` presets, `image_gen`, `video_gen`, `mixture_of_agents` match no outbound pattern. **Fixed ea833110** | IntegrationTools | M |
| F55 | The web process has two DI containers (lifespan `Container()` vs `shared_container()`); sub-agent events miss the WebSocket broadcaster. **Fixed ce4f82fd** | WebAPI | M |
| F56 | CLI, gateway and webhook flows run with no event bus (no domain events, no skill-gap subscription). **Fixed ce4f82fd, a4c81d54** | CLI | M |
| F57 | `/api/webhook/run` with a `session_id` runs any stored session with no ownership check. **Fixed be6044c5** | WebAPI | M |
| F58 | Reads with no tenant filter: `/api/sessions/search`, `/api/events/stream` (every event), `/api/dashboard/metrics`. **Fixed eb646fe3** | WebAPI | M |
| F59 | Behavior and ponytail mutations need no identity (`watch/start` watches any directory); behavior WebSockets accept any client when no key is set. **Fixed 606e5e0f** | WebAPI | M |
| F60 | `APIKeyMiddleware` exempts `/api/live` and `/api/prometheus` (real: `/api/health/...`), blocks platform webhooks under `/api/gateway/*`, and rejects store-mode principal keys. **Fixed 22b546e0** | WebAPI | M |
| F61 | Web UI: calls a missing `/api/behavior/settings`; behavior, `/ops` and `/debug` calls send no API key; event types out of sync (`error` vs `failed`, no `tool_approval`). **Fixed 935aee50** | WebUI | M |
| F62 | `run_mcp.py` passes no discovery, skills, routing or products, so every MCP resource is a stub and no dynamic tools register. **Fixed af06f447** | MCPServer | M |
| F63 | `search_images` URLs and `vane_search` sources go to `data`/metadata, which the model never sees. **Fixed edad6487** | WebTools | M |
| F64 | Executor middleware builds `ToolResult(..., is_error=...)`; `is_error` is a property, so it raises `TypeError` when middleware rewrites output. **Fixed 1d214b34** | BaseTool | M |
| F65 | `ocr` reads any path; without pytesseract it sends the raw bytes to the vision provider; in the webhook role. **Fixed c2265eeb** | WebTools | M |
| F66 | `spacescraper` can run `docker-compose up -d`, unguarded, and stays in the `webhook` role that drops exec tools. **Fixed 715a6d6b** | WebTools | M |
| F67 | `search_history` returns old content across all sessions, unfenced, in the webhook role. **Fixed 715a6d6b** | WebTools | M |
| F68 | The inbound-mail gate fact can be evicted by the 100-fact cap (oldest by insertion). **Fixed 843bd6c6** | Session | M |
| F69 | A step the evidence audit downgrades resumes as COMPLETED: the downgrade is not an event. **Fixed e28a5015** | Step | M |
| F70 | `Plan._heuristic_splits` is lost in `model_dump`/`model_validate`, so the misalignment signal never fires. **Fixed 45698189** | Plan | M |
| F71 | Built-in skills silently override project and user skills of the same name. **Fixed 531bb5b0** | SkillRegistry | M |
| F72 | DI `browser_pool` is never started or acquired; `/health` reports it healthy from an import flag. **Fixed f9f68bb7** | Browser | M |
| F73 | `PlaywrightAdapter.start()` has no lock or running check; two tools can each launch a browser. **Fixed 1daa3473** | Browser | M |
| F74 | `camofox_browser` redirect check misses hostnames that resolve private; DNS failure counts as public. **Fixed 84fe44ef** | BrowserTools | M |
| F75 | `computer_use` skips the `require_window` focus check silently when pygetwindow fails, then types. **Fixed 914e93d0** | BrowserTools | M |
| F76 | Gateway `extract_media` attaches any absolute `.json/.yaml/.md/.txt/.csv` path named in a reply; email gateway authorizes on the `From` header. **Fixed 0170e5ba (attachments), 9b94e943 (email sender authentication)** | ChatGateways | M |
| F77 | Dead CLI commands: `flow cancel`/`retry`/`undo` act on per-process state; `delete` deletes nothing; `cron_agent` overwrites an unreadable jobs file. **Fixed: `delete` 260e1b5c, cron_agent 2ac3672c; cancel/retry now say they act only in the running process (5c574b1b). Cross-process cancel 48bac27e** | CLI | M |
| F78 | Personas with YAML frontmatter get the name `---` and overwrite each other's registry entry. **Fixed 574d991e** | Personas | M |
| F79 | Low-severity notes (dead methods and ports, duplicated facts, swallowed exceptions, stale comments, timeout unit mismatch in `advanced_browser`, unclosed ApifyService sessions): listed in each card's Shape | (cards) | L |
| F80 | Edited plan file never ran: routing added the edited PlanEvent in memory only and the step handler reloads from the repo (STEP_NOT_FOUND). **Fixed d91d9f87** | FlowRouter | H |
| F81 | A run with failed steps re-ran CompletedState until max_iterations (session FAILED was not a loop exit). **Fixed 8185a796** | PlanActFlow | H |
| F82 | Egress taint reset every step (fresh executor per step), so fetched content could drive an ungated send to a known recipient in the next step. Now per session, in process. **Fixed cfb7d850** | EgressGuard | H |
| F83 | AgentRunner saved FAILED/cancelled sessions as WAITING, and republished events the flow had already emitted. **Fixed 630096da** | CLI | M |
| F84 | DI-built persistence adapter dropped the permanent-error filter. **Fixed b37950b4** | DIContainer | M |
| F85 | MCP results flagged `isError` reported success. **Fixed 85a0e8d1** | MCPServer | M |
| F86 | Events-json truncation could drop the only PlanEvent (NO_PLAN_FOUND). **Fixed 14fce2cd** | SQLiteStateRepository | M |
| F87 | A met termination condition never ran CompletedState. **Fixed 195e5653** | PlanActFlow | M |
| F88 | `flow run --model` never reached the cascade; now tried first, role models as fallbacks. **Fixed 02b5540b** | CascadeExecutor | M |
| F89 | A step executor with no role used the default cascade (premium fallback), not the executor cascade. **Fixed fd555cb5** | CascadeExecutor | L |
| F90 | One unset `${VAR}` in the MCP config disabled every server. **Fixed 5201a7d4** | MCPServer | L |
| F91 | Plan review stored its WaitForUserEvent twice. **Fixed ae6843ac** | FlowState | L |
| F92 | The model could set a tool's retry count via `_max_retries`. **Fixed bcfcd06e** | BaseTool | L |
| F93 | Low items from the process-card read, 2026-10-23. Fixed: publisher reads the current plan and the run span ends once (f4ee482d); dead letters in ~/.weebot/dead_letter, reported by doctor (fab99881); cascade fast-fail recorded and skipped, rescue by price, true tier labels (628a16bd); `MCPToolkitAdapter` expands `${VAR}` (d3c08166). Kept as is: a cancelled WAITING session keeps its marker, so one later resume of it stops at its first step (the marker is then consumed). | (process cards) | L |
| F94 | A local file:// page, a file_editor write and viewing the session's own file tainted the session, so a local form needed a human (F41 side effect, eval task 22). **Fixed e60aaa0e** | EgressGuard | M |
| F95 | Batch median rose to ~57 s: ~25 s per run fell outside the flow. 10 s was the exit drain waiting on a dream scan spawned after every completion and then abandoned; now at most once per 6 h (**Fixed b4f0bf4b**; task 5 39 -> 30 s, task 6 47 -> 33 s). The rest is startup: four MCP servers connect in sequence (~7.4 s: jira 3.4, apify 2.0, hubspot 1.3, postiz 0.7). Connecting them in parallel needs each server in its own task (anyio cancel scopes cannot cross tasks); not done. | MCPServer, FlowState | M |

## 3. Module, paradigm, pattern

| Module | Paradigm and pattern | Why this and not the alternative |
|---|---|---|
| Shell/tool guard stack (F01-F03, F07-F09, F12) | Chain of Responsibility over small `ToolGuard` strategies; each existing guard gets a thin **Adapter**; one **Decorator** (`GuardedTool`) applied at the composition root; verdicts are an immutable value object folded with "most restrictive wins" | Today three tools each hard-code a different gate order. One chain removes the divergence (powershell, MCP). Alternative rejected: gating only in `ToolExecutor`, because the MCP server calls tools directly. |
| Approval (F07, F08, F11) | **Port + Strategy**: `ApprovalPort` with Deny (default, today's behaviour), Console and Flow-pause implementations; `ApprovalManager` becomes a session-cache **Decorator** over a port; an approval is a single-use grant bound to a command hash | Reuses the code that already exists and keeps fail-closed. Alternative rejected: prompting inside tools, which blocks headless runs. |
| `ExecApprovalPolicy` (F04, F05) | **Pure function over immutable data**: split into segments with a quote-aware tokenizer, evaluate each, fold with DENY > ASK > ALLOW, then specificity | Removes the keyword override that causes F04. Property tests express the precedence directly. |
| Analyzer (F10) | **Rules as data** (`Rule(id, pattern, level, layer, rationale)`) plus a golden corpus of malicious and benign commands | Tuning by test expectation caused the 1.2x fudge. A corpus makes calibration a measured change. |
| Rollout of enforcement | **Dark launch**: `WEEBOT_SHELL_GUARD_MODE=observe\|enforce`, observe first | Enforcing DANGEROUS changes what agents can run today. Observe mode shows the blast radius first. |
| Settings (F13-F17) | One cached accessor (`get_settings()` with `lru_cache`), registered in the container; consumers take a narrow frozen slice (**Interface Segregation**); data-driven provider table | Matches pydantic-settings practice and the project's DI. Alternative rejected: pass the whole bag everywhere. A ratchet lint counts remaining `WeebotSettings(` sites. |
| Model config (F18-F21) | **Single source of truth**: the generated catalog owns prices and capabilities; the cascade table keeps ids only; rename the dataclass | `test_routed_models_exist.py` already guarantees the ids exist in the catalog, so the price fallback is unreachable for them. |
| Cost and events (F23) | **Event-sourced read model (CQRS projection)**: executors publish an `LLMCallCompleted` event with model, tokens, cost; `DurableEventBus` writes the cost columns; `get_cost_summary` is the query behind `GetCostSummaryQuery`, CLI `costs` and MCP | The append-only store and the unused query already exist. One home for the fact. The tracker stays as a last-N latency/circuit cache with no cost. |
| Valkey bus (F24) | **Bridge**: a reader task re-dispatches messages from the channels into the inner `AsyncEventBus`, tagged with an origin id to avoid echo. Interim: fail fast at DI if Valkey is configured | Smallest fix that makes the adapter honour the whole port. |
| Mediator and ops API (F22, F28) | Type-safe dispatch (`send` rejects a `Query`, `query` rejects a `Command`); tracer injected by constructor; FastAPI lifespan owns one container (`Depends`) | Removes a `Container()` built inside the Mediator and per request. |
| Persistence (F26, F27) | **Interface Segregation**: role ports (behavioral rules, corrections, commitments, plan templates, memory metadata, session constraints, opportunities) backed by the helper repos that already exist; the facade stays for compatibility; unused methods deleted | The helper repos are the natural adapters; no new storage code. Domain services depend on domain-level protocols, not on SQLite duck typing. |
| Flow vs step executor (F25) | **Parameter Object**: a typed `StepExecutionContext` carried by `ExecuteStepCommand`; rename `PlanActFlow._executor` to what it is | Needs an ADR first: it decides what per-session values a step should see. |
| DI hygiene (F28, F35) | Constructor injection at composition roots; ratchet lint on `Container()` sites | Service-locator calls are the cause of the hidden-wiring bugs already recorded in the source. |
| Sandbox (F29-F31) | **Builder from validated settings** (`SandboxConfig` built once from `WeebotSettings`, fail-closed defaults) plus **capability negotiation**: add `SandboxCapability.NETWORK_ISOLATION`, reported only by backends that enforce it; a request for no network on a backend without it is refused or warned per a strict flag | The port already has a capability enum; negotiation avoids the silent no-op that WSL2 and native give today. Alternative rejected: faking enforcement with proxy variables. |
| Tool registry (F32-F35) | **Data-driven wiring table** (`name -> factory(WiringContext)`) instead of the if/elif chains over name sets; immutable role tables (`MappingProxyType` of tuples) with per-instance copies; read `allowed_roles` from `model_fields`, or delete the discovery branch; collaborators passed in, not found in a new `Container()` | Removes the shared mutable state and the hidden containers. The tier gate is either wired into `ToolAssembler` or deleted. |

Placement, so no import-linter exemption is added: `ToolGuard` and `ApprovalPort` in `weebot/application/ports/` (one file per port, as today); adapters, `GuardChain`, `GuardedTool` in `weebot/tools/guards/` (tools already depend on core and on application ports); wiring in `weebot/application/di`. Core classes (`BashGuard`, `ExecApprovalPolicy`, `EgressGuard`) are unchanged by the adapter step.

## 4. Waves

Size: S under half a day, M a day or two, L longer. Every task starts with a failing test that shows the defect.

### Wave 0: environment and reproduction (no production code)
- W0.1 Install dependencies; get a green `pytest tests/ -v` and `make check` baseline (or run each `scripts/lint_*.py` by hand where `make` is missing). Record the numbers. S
  DONE 2026-10-22, Windows 11, Python 3.12.10, project `.venv` from `requirements.txt`, no `make`:
  - `pytest tests/` (repro tests excluded): 5289 passed, 5 failed, 120 skipped, 31 deselected (external), 3 xfailed, in 5:55. Three of the five call `grep` or `sleep` through `subprocess` and pass when pytest runs from Git Bash, where both are on PATH. Run the suite from Git Bash on Windows.
  - Two failures remain under Git Bash. Both come from the environment, not from a finding:
    - `tests/unit/test_output_path.py::TestOutputPath::test_relative_returns_absolute` asserts lowercase `weebot` in the path, but this checkout's folder is `Weebot`.
    - `tests/unit/test_behavior_ledger_git.py::test_a_git_failure_is_reported_not_swallowed_as_success` fails in teardown: `shutil.rmtree` gets `PermissionError` on read-only `.git/objects` files.
    Neither blocks Wave 1. Fix both in a small W1 task, or note them as the known baseline.
  - Lints by hand, all at their ceilings (equal, not over):
    - `silent_except_handlers` 129
    - `blocking_io_in_async` 29
    - `unregistered_di_keys` 0
    - `bare_env_reads` 71
    - `print_in_production` 105
  - Other gates pass: un-awaited coroutines none; ruleset consistency and entry twins match; import-linter 9 kept, 0 broken.
- W0.2 One strict-xfail test per finding in `tests/unit/fixes/` (named `test_f<NN>_...`). A test that unexpectedly passes means the card was wrong: correct the card, drop the finding. Order: F13, F22, F07, F24, F23, F04, F01, F10, F09. M
- W0.3 DONE (card review only): the Sandbox card shows `sandbox_allow_network` is never read and the default config allows network on every backend, so the sandbox does not contain Python egress; the MCP server calls `BashTool` and `PythonExecuteTool` directly. Wave 0 adds repro tests for F29 and F32.
Gate: you review the reproduction table.

W0.2 result, 2026-10-22: 22 strict-xfail tests in `tests/unit/fixes/` (13 files) plus 3 passing controls. Each was also run with `--runxfail` to confirm it fails for the stated reason, not for an unrelated error. All 15 findings below are now "repro"; none was wrong.

| ID | Test file | Observed failure |
|---|---|---|
| F01 | `test_f01_powershell_skips_bash_guard.py` | `curl ... \| bash` is BLOCKED by BashGuard (control) but reaches the powershell sandbox |
| F04 | `test_f04_f05_policy_ordering.py` | `Format-Volume -DriveLetter D; rm x` returns approved=True (ask); unchained it is denied (control) |
| F05 | same | Copy-Item, Move-Item, Rename-Item, Set-Content alone: requires_confirmation=False |
| F07 | `test_f07_approval_callbacks.py` | `auto_approve_callback` yields DENIED ("can't be used in 'await' expression"); prompt contains a literal `{'':` |
| F09 | `test_f09_python_egress.py` | `python_execute` posting `.env` to a host: is_egress=False |
| F10 | `test_f10_entropy_hex_digest.py` | `git checkout <40-hex sha>` and `docker pull ...@sha256:<64-hex>` are DANGEROUS (layer 3), so the bash tool refuses them. Worse than the card's "can reach": ordinary git use is blocked |
| F12 | `test_f12_hook_payload.py` | DANGEROUS hook payload has requires_approval=False |
| F13 | `test_f13_run_mcp_key_check.py` | `TypeError: ... missing 1 required positional argument: 'self'` at `run_mcp.py:87` with a key set |
| F14 | `test_f14_xai_key_counted.py` | xai key alone raises ValueError; not in `available_providers()` |
| F22 | `test_f22_ops_router_dispatch.py` | `/api/costs/summary` returns 500 with a working query handler registered |
| F23 | `test_f23_cost_summary_ignores_store.py` | handler returns a summary without touching its injected repository |
| F24 | `test_f24_valkey_drops_local_events.py` | with Valkey connected, a local subscriber receives nothing. Passes under decision 4 (raise) or a bridge (deliver) |
| F29 | `test_f29_sandbox_network_default.py` | setting says off (control), `SandboxConfig().allow_network` is True |
| F32 | `test_f32_f33_registry_state.py` | autodiscovery returns `{}` |
| F33 | same | a tool added to `coder` on one registry appears in a new one; `set_tool_tier` on one changes another |

Each fix task flips its test from xfail to a plain test in the same commit; strict xfail makes the old marker fail loudly if forgotten.

### Wave 1: small fixes (independent, one commit each)
- W1.1 F13: `WeebotSettings().validate_at_least_one_key()` in `run_mcp.py`; test runs `main()` with a key in the environment and no patching. No pattern. S
- W1.2 F07a: make `auto_approve_callback` / `auto_deny_callback` `async def`; add the missing `f` prefixes or delete `format_prompt` (no caller). S
- W1.3 F14: one table `_PROVIDER_KEYS = {"openrouter": "openrouter_api_key", ...}` used by both methods; add xai. S
- W1.4 F15: empty defaults; the Reasoner/Berb/Scraper clients raise a clear error when used unset. S
- W1.5 F19, F21, F18 docs: delete dead items, fix the docstring and root `CLAUDE.md` rule 4, log in the `except` at `model_refs.py:792`. S
- W1.6 F10 cleanup: delete `_layer4_semantic_llm_analysis`, `_DANGEROUS_OPERATORS`, the false timeout claim; remove the `.importlinter:62` exemption this frees. S
- W1.7 F12: set `requires_approval` for DANGEROUS in the hook payload. S
Gate: `make check` green, ceilings not raised.

W1 result, 2026-10-22 (no git repo here, so no per-task commits; each task is listed with what it touched):
- W1.1 F13 DONE: `run_mcp.py:87` calls the check on an instance. The test runs `main()` unpatched, with and without a key.
- W1.2 F07a DONE: both auto callbacks are `async def`; the two `format_prompt` lines have their `f`. `format_prompt` was kept rather than deleted because W3.4 rewires `ApprovalManager`.
- W1.3 F14 DONE: `_PROVIDER_KEYS` in `settings.py` feeds both methods, with xai added last so the existing provider order is kept. The error message lists every env var from the table.
- W1.4 F15 DONE: `reasoner_dir`, `berb_dir` and `scraper_dir` default to None in settings and in the three tools.
  - New `require_setting()` in `config/tool_config.py` raises a clear error naming the variable on each CLI and docker-compose path, so the existing fallbacks run. Before this, a `cwd=None` subprocess would have run in the current directory.
  - `tests/unit/test_{berb,reasoner,scraper}_tool.py` each gained an autouse fixture that sets the variable to `tmp_path`.
  - `docs/CONFIGURATION.md` was regenerated. That also added two rows that had drifted earlier: `LLM_POOL_ACQUIRE_TIMEOUT_S` and `MAX_CONCURRENT_FLOWS`.
- W1.5 F19, F21, F18 DONE:
  - The `model_cascade_config.py` docstring now names `model_refs.py` as the tier source.
  - Deleted with no reader in the tree: `AGENT_ROLES`, `very_long_context`, the medium-context block (it returned the same as the fall-through, so the 128k loop could not run), plus `get_model_for_context_size` and `get_model_stats`, also dead.
  - `model_refs.get_models_for_role_and_task` logs its fallback. That function itself has no caller; it is a W6.1 item.
  - Root `CLAUDE.md` rule 4 is corrected and the entry twins regenerated.
- W1.6 F10 cleanup DONE: deleted `_layer4_semantic_llm_analysis`, `_DANGEROUS_OPERATORS`, the timeout and graceful-degradation claims, and the unused import. The `.importlinter` exemption for `bash_security -> model_selection` is removed. The F10 repro test stays xfail until W3.6.
- W1.7 F12 DONE: the hook payload says `requires_approval` for SUSPICIOUS and DANGEROUS. This changes the payload only; DANGEROUS still runs until W3.7.
- Ceilings lowered, none raised:
  - `silent_except_handlers` 129 to 127
  - `bandit_b110` 67 to 65
  - `import_exemptions` 77 to 76
- Two of the lowered metrics (`bandit_b110`, `import_exemptions`) are checked only in CI (`.github/workflows/architecture.yml`), not by `make check`. `bandit` is now installed in the local `.venv` so the count could be measured.
- Repro tests now plain: F07 (W1.2 part), F12, F13, F14, plus new F15. Still xfail: F01, F04, F05, F09, F10, F22, F23, F24, F29, F32, F33.
- Gate: `pytest tests/` from Git Bash with `.venv/Scripts` on PATH: 5312 passed, 2 failed (the two known Windows baseline failures from W0.1), 118 skipped, 19 xfailed (16 repro plus 3 older), in 4:13.
  - With `lint-imports` and `ruff` on PATH, two architecture-fitness checks run instead of skipping.
  - All lints pass at their ceilings, CI-only ones included. Import-linter: 9 kept, 0 broken.

### Wave 2: settings
- W2.1 `get_settings()` accessor, container registration, `cache_clear` fixture beside `tests/conftest.py:58`. S
- W2.2 Ratchet lint `lint_settings_construction.py` counting `WeebotSettings(` outside the accessor; ceiling set to today's 33. S
- W2.3 Migrate in order: `gateways/base.py:87` (per message), `plan_review.py:57`, `verifying.py:62`, DI factories, web routers, CLI. Lower the ceiling with each batch. M
- W2.4 Fold the import-time constants into fields behind a compatibility shim; move `OSWorldSettings` next to `weebot/osworld`. M
Gate: you review the ceiling movement.

W2 result, 2026-10-22:
- W2.1 DONE: `get_settings()` (`lru_cache(maxsize=1)`) in `config/settings.py`, bound in `Container.configure_defaults()` as `WeebotSettings -> get_settings` and resolved by the `llm_pool` and `ProviderAccountPort` factories. Autouse `_fresh_settings_cache` in `tests/conftest.py` clears it before and after each test. Tests: `tests/unit/config/test_get_settings.py`. Behaviour change: a changed `.env` or environment now takes effect on restart, not on the next construction.
- W2.2 DONE: `scripts/lint_settings_construction.py` (AST; `config/settings.py` and tests excluded), key `settings_construction`, `make lint-settings-construction` (in `check`), a step in `.github/workflows/architecture.yml`, and both ratchet guard tests updated. Real count at the start was 43, not the card's 33.
- W2.3 DONE: all 41 remaining sites migrated in five batches (gateway/flow states, DI factories, web, CLI and entry scripts, services/core/adapters). Ceiling 41 -> 0, so it now bans new direct construction. Three CLI reads were dead (F841) and were deleted rather than migrated: `unused_locals` 31 -> 28. No code writes to the shared instance (grep). Tests that patch `weebot.config.settings.WeebotSettings` still work because `get_settings()` looks the name up at call time and the cache is empty per test.
- W2.4a DONE, but moved to `weebot/config/osworld_settings.py`, not next to `weebot/osworld`: its only reader is `infrastructure/sandbox/osworld.py`, and `weebot.osworld` is the leftover harness outside the layers. The class was moved byte-identical; both importers updated.
- W2.4b NOT DONE, needs a decision. Folding `WORKSPACE_ROOT`, `LOGS_DIR`, `SESSIONS_DB`, `MEMORY_DIR`, `PROFILES_DIR` into fields behind a lazy shim would still build and validate `WeebotSettings` at import time:
  - `powershell_tool.py:32, 77-78` uses `WORKSPACE_ROOT` in its class body, and `file_editor.py`, `voice_output_tool.py` and `security_validators.py` import it at module level.
  - The tools layer would come to depend on settings, which `test_no_settings_import_in_tools` forbids in spirit.
  - An invalid `.env` value would crash an import instead of being reported by `doctor`.
  - In tests, settings would be read at collection, before the `.env` fixture applies.
  Options: (a) keep them as import-time constants and document that, which needs no code; (b) add read-only `WeebotSettings` fields that default to the constants, giving one reader with no import-time validation; (c) pass the workspace into the tools through `ToolConfig`. Recommendation: (a) now, (c) when Wave 5 touches tool wiring. **DECIDED 2026-10-22: (a)** (user: "Proceed" on the recommended option). The comment above the constants in `settings.py` says why. Option (c) is added to W5.5.
- Gate: `pytest tests/` from Git Bash: 5317 passed, 2 failed (the two W0.1 Windows baseline failures), 19 xfailed.
  - All 13 lint gates pass at their ceilings when run one at a time; import-linter: 9 kept.
  - `bandit_b110` and `unused_locals` exit 1 if run while pytest is running, so run the lints serially.
- Ceilings moved down only:
  - `settings_construction` new at 41, then 0
  - `unused_locals` 31 to 28

### Wave 3: guard stack (highest value; staged)
- W3.1 Add `ToolGuard`, `GuardVerdict`, `GuardChain`, and adapters for BashGuard, analyzer, policy, egress. No behaviour change; `GuardedTool` records the verdict in observe mode. M
- W3.2 Apply `GuardedTool` to `powershell` (F01) and to the tools the MCP server registers (F09). Both start in observe mode. M
- W3.3 `ExecApprovalPolicy` as a pure fold over segments (F04, F05); property tests: DENY always beats ASK beats ALLOW; add standalone rules for the four verbs. M
- W3.4 [ADR-013 APPROVED 2026-10-22: `docs/adr/013-tool-call-approval.md`; MCP deny, 10-minute single-use grants, gateways flow-pause for the authorized sender, exact-argument fingerprint, sandbox network per approved call] ADR: how "ask" resolves for each channel (CLI console, web pause, headless deny). Then `ApprovalPort` + Deny/Console/Flow-pause; `ApprovalManager` as the session cache; grants are single-use, bound to a command hash, with expiry (F07, F08, F11). L
- W3.5 Wire `approve_recipient` through the same port (F08). Wire the `finance`/`payment` categories and `financial_tools_always_ask` into the chain, or delete both (F06). M
- W3.6 Analyzer rules as data with the golden corpus; remove the 1.2x multiplier; exclude pure-hex digests; fix or remove the unreachable layer 2 targets; full-match the PowerShell allowlist (F10). M
- W3.7 Observe-mode telemetry review (suggest two weeks), then flip `WEEBOT_SHELL_GUARD_MODE=enforce`: DANGEROUS becomes "ask", SUSPICIOUS stays logged and audited (F02, F03). S
- W3.8 Python egress (F09): the sandbox does not contain it (W0.3), so classify `python_execute` code that imports network libraries (`requests`, `httpx`, `urllib`, `socket`, `aiohttp`) as egress, escalate-only. S
- W3.9 Sandbox (F29-F31): build `SandboxConfig` from `WeebotSettings` in one place used by DI and the three tools' fallback; read `sandbox_allow_network` and `sandbox_max_output_bytes`; add `NETWORK_ISOLATION` capability (Docker only) and refuse or warn when the setting asks for isolation the backend cannot give; Docker flags `--cap-drop ALL`, `--read-only` with a tmpfs `/tmp`, `--user`, `--pids-limit`; mount the workspace read-write only when configured; make `create_default_sandbox()` follow the factory priority and check availability. Decision 7 made (network off by default); depends on W3.4 and W3.5 for the approval route. M
Gate after W3.2 (observe data), after W3.4 (ADR), and before W3.7 (flip).

W3.1-W3.2 result, 2026-10-22:
- Placement differs from section 3: everything is in one module, `weebot/application/services/tool_guards.py`, not split between `application/ports/` and `tools/guards/`.
  - `weebot.mcp` may not import `weebot.tools.*` without a new import-linter exemption, and `import_exemptions` may not rise.
  - A port class with no implementation in `infrastructure/` or `di/` fails `test_orphan_ports_flagged`, and nothing outside application implements `ToolGuard`.
- W3.1 DONE: `GuardAction` (ALLOW < ASK < DENY), `GuardVerdict`, `ToolGuard` protocol, and `GuardChain`. The chain folds verdicts with most-restrictive-wins; a guard that raises yields DENY.
  - Adapters, with the core classes unchanged:
    - BashGuard: BLOCKED->DENY, DANGEROUS->ASK, SUSPICIOUS noted
    - analyzer: DANGEROUS->DENY, SUSPICIOUS noted
    - ExecApprovalPolicy: deny->DENY, confirm->ASK
    - EgressGuard: approval->ASK
  - `GuardedTool` decorator, and `guard_tools()`.
  - New setting `shell_guard_mode` (env `WEEBOT_SHELL_GUARD_MODE`, `observe` | `enforce`, default `observe`).
  - Tests: `tests/unit/application/services/test_tool_guards.py` (18).
- W3.2 DONE: `RoleBasedToolRegistry.create_tool_collection_from_names` wraps `bash`, `powershell` and `python_execute`. That is every flow, cron and MCP-scope collection. The MCP server wraps its own `bash` and `python_execute` (`weebot/mcp/server.py:380`).
  - Observe mode logs the verdict at WARNING (non-ALLOW) or INFO (notes) on logger `weebot.application.services.tool_guards`, then runs the tool unchanged.
  - F01 repro reworked: the registry's powershell is guarded, and enforce refuses the blocked command (both plain tests). "Default mode refuses" stays strict-xfail until W3.7.
  - Tests: `tests/unit/mcp/test_mcp_tool_guards.py`. `tests/unit/tools/test_tool_registry.py` now reads `.inner._sandbox`.
- Observe data, needed for the gate before W3.7: run real tasks with the default mode, then search the logs for `tool guard [observe]`.
  - Each line names the most restrictive guard and every guard that spoke.
  - Expect analyzer DENY on commands with hex digests (F10) until W3.6, and policy ASK on `rm` and `Remove-Item`, which bash already refuses today.
- F17 resolved, no defect: `plan_review_enabled` accepts both `WEEBOT_PLAN_REVIEW_ENABLED` and `PLAN_REVIEW_ENABLED` (run 2026-10-22), and `shell_guard_mode` likewise. `docs/CONFIGURATION.md` lists only the field-name form.
- Gate: 5339 passed, 2 failed (W0.1 baseline), 19 xfailed. All lints at their ceilings (serial); import-linter 9 kept.

W3.3 result, 2026-10-22:
- DONE: `ExecApprovalPolicy.evaluate` is a pure fold. `split_segments()` splits on `; && || | &` outside quotes; newlines are not separators, so multi-line Python stays one segment.
  - Each segment is judged alone, and the strictest segment wins (DENY > ASK > AUTO_APPROVE).
  - Within a segment any matching DENY rule wins whatever its length. Otherwise the longest pattern decides, which keeps the Output\ carve-out above `remove-item`, but only for its own segment.
  - A destructive keyword with no matching rule still asks when the command is chained, as before.
- Not done: the section 2 note that longest-pattern is not true specificity still holds within one segment for non-DENY rules. Replacing it is W3.6 work (rules as data).
- F04 fixed. F05 fixed with four standalone ASK rules: `set-content`, `copy-item`, `move-item`, `rename-item` (word-boundary regex).
  - **Behaviour change:** these four cmdlets alone were auto-approved and now ask. Until W3.4 gives ASK an approval route, `bash` and `powershell` refuse them, exactly as they already refuse `Remove-Item`.
  - Keyword-only ASK for unchained `shutdown`, `Restart-Computer` and `Clear-Content` was not added, because `python_execute` passes Python code through this policy and `executor.shutdown()` would be refused.
- Tests: `tests/unit/fixes/test_f04_f05_policy_ordering.py`.
  - Plain tests: F04, F05, the carve-out.
  - Hypothesis properties: the chain verdict equals the strictest segment for any mix of separators, any DENY segment denies, and splitting returns the segments.
  - Quote cases.
  - `.hypothesis/` added to `.gitignore`.
- W3.4 and W3.5 result (2026-10-22): ADR-013 implemented, with enforce still off (`shell_guard_mode=observe`).
  - **Grant store:** `core/approval.py` `ApprovalManager` is the grant store. Grants are single use, 10 minutes, session-scoped, and keyed by `call_fingerprint(tool, args)`, a SHA-256 over canonical JSON. The old request/cache API (session-wide approval, approval by raw command string, `auto_deny_blocked`) is deleted, which closes the rest of F07.
  - **Port and strategies:** `application/ports/approval_port.py` (`ApprovalPort`, `ToolCallApproval`, `ApprovalOutcome`). `application/services/tool_approval.py` holds `DenyApproval` (default), `ConsoleApproval` and `FlowPauseApproval`, plus ContextVar scope (`set_process_approval`, `approval_scope`).
  - **Channels:**
    - CLI `flow` commands use Console when stdin is a TTY.
    - The web process (UI and gateways) uses Flow pause.
    - Cron (`cron_agent_runner.run`) and webhooks (`webhook_run`) are scoped to Deny.
    - The MCP server keeps Deny.
  - **Enforce path:** `GuardedTool` sends ASK to the channel; DENY is never approvable.
  - **Flow pause, end to end:**
    1. `pending_result` carries `approval_required`.
    2. `ExecutorAgent` (`_base.py`) emits `ToolApprovalEvent`, which gained `fingerprint` and `allow_always`.
    3. `ExecutingState` records gate `tool_approval` (`mark_tool_approval_pending`).
    4. `FlowRouter` turns "yes" into a grant (`record_flow_reply`), and the re-run step consumes it.
  - **W3.5 egress:** `ToolExecutor`'s egress gate (enforcing by default, as before) routes its ASK to the same channel. Deny returns exactly the old blocked result.
    - "Always" (offered only when the sole reason is a first-time host) calls `EgressGuard.approve_recipient`, its first caller (F08).
    - The registry chain no longer includes `EgressAdapter`, so one call is never asked about twice. A call approved at the egress gate carries `approved_call`, so `GuardedTool` does not re-ask. The MCP chain keeps all four guards.
  - **F11:** the `security_override` HMAC token is removed from `BashTool` (parameter schema, `contracts/bash.yaml`, `_verify_override_token`), along with `WEEBOT_ADMIN_SECRET` (`.env.example`, config-reference schema).
  - **Tests:** `tests/unit/application/services/test_tool_approval.py` (25) covers the store, strategies, scope, `GuardedTool` enforce, egress routing and the FlowRouter round trip. The F07 test was reworked; the override tests in `tests/unit/test_audit_findings.py` were replaced. `known_orphans` in `test_architecture_fitness.py` lists the three port names, following the AuditPort precedent.
  - **Not done:** `approval_granted`, `approval_denied` and `approval_expired` are logged, not journaled. Only `approval_requested` reaches the event store, as `ToolApprovalEvent` through `DurableEventBus`. The `_base.py` `approval_required` branch has no direct unit test; it mirrors the `awaiting_human` branch beside it. `weebot-ui` has no renderer for `tool_approval`, so after `ToolApprovalEvent` the executor also yields `WaitForUserEvent(question=<approval prompt>)`, which the UI, CLI and SSE already render and the composer resumes from. A human round trip in a browser was not run.
  - **Gate:** 5428 passed, 2 failed (W0.1 baseline), 12 xfailed. All lints at ceilings; import-linter 9 kept.
- W3.8 result (2026-10-22): F09 fixed.
  - `EgressGuard` classifies `python_execute` code that imports a network library as egress: `requests`, `httpx`, `urllib`, `aiohttp`, `socket`, `http.client`, `ftplib`, `smtplib`, `websockets`, `paramiko`, `boto3`, `pycurl`, `grpc`, or a matching `__import__`.
  - The recipient is the first URL host in the code; with none, the host is unknown and the call asks.
  - Since `ToolExecutor`'s egress gate already enforces, such code now asks in the web UI and an interactive CLI, and is refused in headless runs, unless the host is allowlisted with nothing sensitive in the payload.
  - Repro: `tests/unit/fixes/test_f09_python_egress.py` is now plain, plus cases.
- W3.9 result (2026-10-22): F29 fixed; F30 and F31 partly.
  - **Config from settings:** `create_default_sandbox()` builds its config with `build_sandbox_config(settings)`, which reads `sandbox_allow_network` (default false) and `sandbox_max_output_bytes`. `SandboxConfig()` itself now defaults to `allow_network=False`.
  - **Per-call network:** a ContextVar in `application/ports/sandbox_port.py` (`network_cleared_for_call`, `network_allowed`). `ToolExecutor` sets it only for a call that is cleared: egress that passed (allowlisted, approved, or detect-only), or network use (`EgressGuard.network_use`: curl, wget, iwr, pip, npm, git remotes, docker pull) to a known host or with a human's approval. "Always" allowlists the host.
  - **Backends:** native Windows lifts its dead-proxy block, and Docker drops `--network none`, only inside a cleared call.
  - **Capability and hardening:** `SandboxCapability.NETWORK_ISOLATION` is reported by Docker only. A one-time warning says network-off is best effort on native Windows and WSL2. Docker also gains `--cap-drop ALL`, `--security-opt no-new-privileges` and `--pids-limit 256`.
  - **Behaviour change:** with the default `SANDBOX_ALLOW_NETWORK=false`, sandboxed code has no network unless the call is cleared. The first `pip install` or `git clone` to a host asks, or is refused in cron, webhooks and MCP. `SANDBOX_ALLOW_NETWORK=true` restores the old behaviour.
  - **MCP:** the MCP server calls tools without `ToolExecutor`, so its sandboxed calls never get per-call network. MCP users who need it set `SANDBOX_ALLOW_NETWORK=true`.
  - **Not done:**
    - `--read-only` and `--user` for Docker: with no workspace mount, installs and writes need the rootfs.
    - Making `create_default_sandbox()` follow the factory's Docker-first priority: on a Windows machine with Docker Desktop it would move every shell call into a container that cannot see the workspace. Both need a workspace-mount design first.
    - A strict mode that refuses, rather than warns, on a backend without isolation.
  - **Tests:** `tests/unit/infrastructure/sandbox/test_sandbox_network.py` (11). The F29 repro is now plain.
  - **Gate:** 5456 passed, 2 failed (W0.1 baseline), 10 xfailed. All lints at ceilings; import-linter 9 kept.
- W3.6 result (2026-10-22), recorded here because W3.6 follows W3.3. DONE: `weebot/tools/bash_security.py` holds its rules as data.
  - **Rule tables:** `Rule(id, pattern, level, layer, rationale)`; `LAYER1_RULES`, `LAYER2_RULES` and `LAYER2_COMBINATIONS` are module tuples, and the thresholds are named constants.
  - **Layer 3, rewritten:**
    - E1: a base64 run of 16+ chars that strictly decodes to mostly printable text with a shell keyword (word-bounded) is DANGEROUS. UTF-16LE (PowerShell `-EncodedCommand`) is decoded too.
    - E2: a run of 40+ chars with raw entropy over 4.0 is DANGEROUS, unless it is pure hex, has no digit or `+/=` (identifier), or is a path whose `/` parts are all under 16 chars.
    - The 1.2x multiplier is removed.
  - **Two new layer 1 rules:** PowerShell `-EncodedCommand`/`-enc`/`-ec`, and `-e` after `powershell`/`pwsh`. The old analyzer caught a UTF-16LE encoded command only because the fudge lifted its 3.84 bits to 4.61. The rewrite exposed this; it is now an explicit rule, not a regression.
  - **Layer 2:** the unreachable targets (`|`, `.`, `+x`) and the mixed-case indicators are removed or lower-cased, so `Invoke-WebRequest` now matches.
  - **Layer 4:** the safe-PowerShell allowlist matches from the start of the command, and only when there is no `;` or `&`.
- F10 fixed. Its repro tests are plain tests now.
- `test_high_entropy_base64` asserted more than 5.0 bits for a 35-char string, which is impossible (max log2(35) = 5.13). It now asserts the raw value (4.31) is above 4.0 and above English.
- Golden corpus: `tests/unit/tools/data/command_corpus.json` (16 malicious, 23 benign, 2 suspicious), checked by `tests/unit/tools/test_command_corpus.py`, along with rule-id, compile and reachability invariants.
- Ceilings lowered:
  - `silent_except_handlers` 127 to 126
  - `bandit_b110` 65 to 64
  - `unused_locals` 28 to 27
- Gate: 5400 passed, 2 failed (W0.1 baseline), 12 xfailed. All lints at ceilings (serial); import-linter 9 kept.
- Gate (W3.3): 5351 passed, 3 failed (the 2 W0.1 baseline failures plus `test_pool_close_reaches_every_connection`, which passes 3 of 3 when run alone: flaky under full-suite load, unrelated), 14 xfailed. Lints at ceilings; import-linter 9 kept.
- Real-run check (2026-10-22), CLI `flow run` on Windows with the default `observe` mode. Task: `rm` a missing file, `pip download cowsay`, and `urllib` GET example.com. Session `d2b3ef47-d830-43c1-bc99-9d0e91876f2f`, 497 s.
  - **Observe lines:** `tool guard [observe] powershell: ASK by exec_approval_policy` for `Remove-Item`, and the same for `bash` on `rm`. Both tools then refused on their own gates, as expected until W3.7.
  - **Console approval:** `pip download` asked as `sandbox_network` (pypi.org), and the `urllib` call asked as `egress_guard` (example.com, `first_time_recipient`). "a" allowlisted both hosts. In steps 2 and 3 the same calls ran with no prompt, so "always" persisted. Both hosts are now in `weebot_egress_allowlist.json`.
  - **Network:** the cleared `pip download` and the `urllib` call both reached the network on the native sandbox. The W3.9 best-effort warning printed once.
  - **Concurrency:** the executor runs a turn's tool calls with `asyncio.gather` (`_tool_executor.py:243`), so two prompts were in flight together. They did not interleave, because CPython serializes `input()` across threads on a TTY, and `ConsoleApproval` is installed only on a TTY. A log line from the first answer printed inside the second prompt (cosmetic).
  - **Found:** F36 (H) and F37 (L), above.
  - **F36 fixed:** `PlanningState` now emits `PlanEvent(status=UPDATED)` for the DPPM plan, then adopts and yields it (`planning.py`). Emitting first keeps memory and the store in step if the emit fails. The resume therefore restores the plan that was reviewed, and the CLI and UI see it.
    - Repro: `tests/unit/fixes/test_f36_dppm_plan_persisted.py`. It failed before the fix (`['step-1'] != ['dppm-1', 'dppm-2']`) and passes after.
    - Gate: 5456 passed, 4 failed, 10 xfailed. Lints at ceilings; import-linter 9 kept.
      - Two failures are the W0.1 baseline.
      - `test_no_secret_with_dev_opt_in_allowed` (Stripe) fails because the repo now has a `.env`. `WeebotSettings` ranks `.env` above the environment (`settings.py:71-76`), so the test's `monkeypatch.setenv` loses to `STRIPE_ALLOW_UNSIGNED_WEBHOOKS=false`. This is a test-isolation gap: tests read the developer's real `.env`.
      - `test_concurrent_appends_are_all_committed` is flaky on Windows: 1 of 3 passed alone. It is unrelated to this change.
  - **Test isolation from `.env` fixed** (same day):
    - The suite already had `_no_dotenv_settings` (`tests/conftest.py`), but it patched `WeebotSettings.model_config`. The Stripe test deletes `weebot.config.settings` from `sys.modules`, and the re-imported class read `.env` again.
    - The fixture now wraps pydantic-settings' `BaseSettings.__init__` so `_env_file` defaults to `None`. That survives re-imports, covers `OSWorldSettings` and any other settings class, and still honours an explicit `_env_file`.
    - Checks: the Stripe test passes with the developer `.env` present. `tests/unit/config/test_dotenv_isolation.py` checks the fixture on any machine.
    - Gate: 5460 passed, 2 failed (the W0.1 baseline), 10 xfailed.
    - Not fixed: the Stripe test's `sys.modules` deletion is never undone. Tests that run after it, and imported `get_settings` at module level, hold a second copy of the module. In suite order no test is affected; run before `tests/unit/config/`, it fails two `test_get_settings` cases. Its reload is redundant now that `get_settings.cache_clear` runs per test.
    - Not fixed, same class: `PremortemState` adds its risk notes to `context._plan.message` without an event, so a resumed run loses them. Steps are unchanged there, so the approved steps still run.
  - **Noise, not errors:** `IntentReviewService` times out at its 5 s `_TIMEOUT` on a thinking model and logs an empty message. `CatalogValidator` ran about 25 times (F28/F35). `Trajectory analysis LLM call failed: Expecting value` (an empty reply parsed as JSON).
  - Planning took 166 s: the first plan took 38 s, then DPPM generated 2 candidates and merged them.

### Wave 4: cost, events
- W4.1 `LLMCallCompleted` event; publish from the executor's success hook; `DurableEventBus` passes cost, model and tokens to `log_event` (F23). M
- W4.2 `GetCostSummaryHandler` reads `EventStorePort.get_cost_summary(window_hours)`; CLI `costs` and MCP `build_costs_json` use the same query; delete `EventLogger` and its example if still unused. M
- W4.3 Valkey: DI fails fast when a Valkey URL is set (decision 4). The bridge reader with an origin tag and a fake-pubsub test (F24) waits until more than one process needs shared events. S
Gate.

### Wave 5: persistence, DI, flow
- W5.1 Role ports over the helper repos; migrate callers one role at a time, `domain/services` first; delete F27 methods (F26). L
- W5.2 Mediator: reject wrong dispatch kind; inject the tracer; log and surface the tool-less fallback (F28). S
- W5.3 Ratchet lint on `Container()` construction sites; migrate the roots in `interfaces/factories.py` first. M
- W5.4 ADR for `StepExecutionContext`, then implement and rename `PlanActFlow._executor` (F25). L
- W5.5 Tool registry (F32-F35): repro tests first (does autodiscovery return an empty table; does `add_tool_to_role` on one instance change another); immutable role tables copied per instance; tier table per instance; delete the dead discovery branch or fix it via `model_fields`; replace the name-set if/elif chains with a wiring table; pass collaborators in instead of building containers; wire the tier gate into `ToolAssembler` or delete it and its tests; pass the workspace root to `file_editor`, `powershell`, `voice_output` and `security_validators` through `ToolConfig` instead of the import-time `WORKSPACE_ROOT` (W2.4b option c). L
Gate.

### Wave 6: model config
- W6.1 Rename the dataclass; reduce `MODEL_CASCADE` to ids per task; make `estimate_cost` a facade over the catalog; keep `test_routed_models_exist.py` green (F18-F20). M

### Wave 7: ops API (go-ahead given, decision 5)
- W7.1 `ops_router` uses `mediator.query`; one lifespan-owned container via `Depends` (F22). After W4.2. S

## 5. Decisions needed

Decisions 1-6 were taken on the recommendations, at the user's request ("suggest the optimal decisions and proceed", 2026-10-22).

1. Enforce "ask" for DANGEROUS commands after the observe period: **DECIDED 2026-10-22: yes.** Headless runs (web, cron, MCP) deny; the CLI asks on the console. SUSPICIOUS stays logged and audited (W3.7).
2. `ApprovalManager`: **DECIDED 2026-10-22: rewire as the session cache** behind `ApprovalPort` (W3.4). Grants are single-use, bound to a command hash, with expiry.
3. `financial_tools_always_ask`: **DECIDED 2026-10-22: wire into the chain** with the `finance`/`payment` categories (W3.5).
4. Valkey: **DECIDED 2026-10-22: keep it off and fail fast.** DI raises at start-up when a Valkey URL is set (W4.3 first half). The bridge is built only when more than one process must share events; until then W4.3 stops after the fail-fast.
5. Wave 7: **DECIDED 2026-10-22: go ahead, after W4.2**, so `ops_router` uses the same cost query as the CLI and MCP. Supersedes the earlier "leave it for now".
6. Jev: **DECIDED 2026-10-22: skip for now.** Revisit as a shadow evaluation (appendix) after Waves 3 and 4, when the guard verdicts and the cost events give a labelled set to score it against.
7. Sandbox network default: **DECIDED 2026-10-22: network off by default, with egress approval for the first host.** `sandbox_allow_network=False` becomes the effective default (W3.9). Code that needs the network gets it only after the egress approval path (W3.4, W3.5) grants the host. Until that path exists, W3.9 must not ship on its own: network-off with no approval route would make every package install or web fetch from code fail. So W3.9 lands after W3.5, or behind a flag that stays off until then. The mechanism for "approve a host, then allow it" (per-host allowlist inside the sandbox versus per-run network on) is still open; it goes into the W3.4 ADR.

## 6. Not covered

Every cluster has a card since Wave G (2026-10-23), which added F38-F79. Each new card that finds a defect adds a row to section 2 and a task here.

---

## Appendix: Jev for fast decisions

Source: the four pages you listed, fetched 2026-10-21. Jev is a "System One" model from TypeSafe AI: it does not write text. You send a state plus typed questions and get typed answers with probabilities. Question types: Choice (option probabilities and confidence), Score (ordered levels), Noul (probability that a statement is true). Questions in one request run in parallel. Vendor claims: 70 to 500 ms end to end, $0.042 per million input tokens, output free, up to 255 choices. The company's own page says the figures come from laptop tests, pricing may be subsidised, the service is hosted only, access is by early-access waitlist, and demos are text only. The docs pages fetched give no auth details, SDK signatures or rate limits. LangChain ships `ModelRouterMiddleware` and `AutoModeMiddleware` (tool-call risk check) for `create_agent`; Weebot does not use that framework, so the middleware does not apply directly.

Where it fits, as seams that already exist (card citations; seam contracts not yet read):

| Seam | Today | Jev question | Value | Rule |
|---|---|---|---|---|
| Cascade pre-routing | `CascadeExecutor` Phase 1 probes every candidate at once and bills them all (`_cascade.py:450-509`) | Choice: tier free / budget / premium for this step | Fewer billed probes; Phase 1 becomes one call | Fall back to today's parallel probe on any error or low confidence |
| Guard second opinion | Analyzer layer 4 LLM check was written and never wired (`bash_security.py:191-263`) | Noul: "downloads and runs remote code", "deletes outside the workspace", "sends data off the machine" | Catches what regexes miss, fast enough to run synchronously | Escalate only: may turn allow into ask, never ask/deny into allow. Sends the command to a third party, so review data egress first (strip secrets; `EgressGuard` itself would classify this call). |
| Python egress | `python_execute` not classified (F09) | Noul: "this code sends data over the network" | Covers the gap in W3.8 if the sandbox does not | Same escalate-only rule; code may contain secrets |
| Verification skipping | CoVe in `VerifyingState`, plan critic, step evaluator | Score or Noul with confidence; skip the expensive check when confidence is high | Lower cost per turn | Needs your own labelled set to prove the calibration before any skip |
| Intent and routing | `ContinuationDetector`, chat vs plan start state, `PersonaRouter` keyword scoring | Choice over a fixed set with confidence | Replaces keyword scoring; ambiguity becomes an explicit low-confidence "ask the user" | `FlowRouter`'s deterministic priority table stays authoritative |
| Inbound-mail triage | The gate pauses on all fetched mail | Noul: "contains instructions addressed to the agent" | Prioritise what the user reviews first | Never remove the pause |
| Tool and skill selection | Scoped MCP retrieval, `SkillRegistry` lookup | Choice over candidate tools (cardinality is fine) | Smaller prompts | Retrieval stays the first stage |

How to integrate if you want it: implement the existing ports (`JudgePort`, `StepEvaluatorPort`, `PlanCriticPort`, `IntentReviewPort`, `ScoringPort`, `TaskRouterPort` exist under `weebot/application/ports/`) with one infrastructure adapter, register it in DI, wrap it in the same retry/circuit-breaker layer as the LLM adapters, and call the HTTP or Python SDK directly, not the LangChain middleware. Read the port contracts first.

Risks to settle before building: vendor numbers are unverified; hosted-only means an external dependency and data leaving the machine; the classifier input is attacker-controlled text, so it can itself be targeted; "calibrated" and "cannot hallucinate" are claims, not measurements. Run a two-week shadow evaluation on your own traffic (log Jev's answer next to the existing decision, act on neither) before any seam depends on it.
