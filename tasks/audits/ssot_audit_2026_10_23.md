# Single-source-of-truth audit, 2026-10-23

User request: "Make sure the ssot principal holds in the project".

Read-only sweep of `weebot/`, `cli/`, entry scripts, config and docs. One row per fact that lives in two or more places. **Drift** means the copies already disagree, or a knob silently does nothing. **Dup** means they agree today but nothing keeps them in step.

Status values: `open`, `done (<where>)`, `deferred (<why>)`.

| # | Fact | Where (canonical first) | Drift | Status |
|---|---|---|---|---|
| 0 | Model routing and prices | `config/model_refs.py` (ids), `config/model_catalog.py` (facts) vs a second role table, `core/model_cascade_config.py` prices, `AGENT_CAPABILITIES.preferred_models`, docstring prices | yes | done (W6.1, `tests/unit/fixes/test_w61_model_ssot.py`) |
| 1 | `WEEBOT_*` env names that settings never read: `WEBHOOK_API_KEY`, `WEB_REQUIRE_AUTH`, `WEBHOOK_ALLOW_EXEC_TOOLS`, `GATEWAY_AUTH_ENABLED`, `GATEWAY_SESSION_TTL_SECONDS`, `GATEWAY_MAX_SESSIONS_PER_PLATFORM`, `MCP_COMPOSITE_TOOLS_ENABLED`, `PONYTAIL_MODE` | `config/settings.py` fields vs `.env.example`, error texts in `web/main.py`, `gateways/base.py` | yes, security knobs | done (`AliasChoices`; `tests/unit/config/test_weebot_env_names.py`) |
| 2 | `BASH_TIMEOUT` / `PYTHON_TIMEOUT` | `settings.py:184` vs `config/tool_config.py`, `tools/bash_tool.py:87`, `tools/python_tool.py:115`; nothing builds `ToolConfig` from settings | yes (env vars dead) | done (DI binds `ToolConfig` from settings; the three tool-collection callers pass it; `test_ssot_tool_config_wiring.py`) |
| 3 | Config reference generated from a hand-written schema | `scripts/generate_config_reference.py` `CONFIG_SCHEMA` vs `WeebotSettings`; second generator `scripts/generate_config_ref.py` writes the same doc | yes, root of 1, 4, 5, 6 | done (`resolved_schema` reads settings defaults; dead vars removed; `scripts/generate_config_ref.py` deleted; `tests/unit/scripts/test_generate_config_reference.py`) |
| 4 | Gateway session TTL and per-platform cap | `settings.py:354,358` (604800, 100) vs `.env.example` (3600, 50), `docs/CONFIGURATION.md` | yes | done (via 3) |
| 5 | Email gateway defaults (poll, IMAP, SMTP hosts) | `settings.py:155-161` vs `.env.example`, docs | yes | done (via 3) |
| 6 | GitNexus defaults, own `os.getenv` | `config/gitnexus_config.py` vs `.env.example`, docs | yes | done (nothing imported `GitNexusConfig`: module and its 11 vars deleted) |
| 7 | Token prices in the cost ledger | catalog vs `utils/cost_ledger.py:52-61` `PRICING` | yes (Opus 3x, DeepSeek 8x) | done (catalog rates; `test_ssot_cost_ledger_prices.py`) |
| 8 | Step-category model table | `model_refs` vs `services/task_model_router.py:31-39`, `routing/adaptive_capability_router.py:130` | yes | done (`CATEGORY_ROLE` over `ROLE_MODEL_CONFIG`; ACR pool filtered to the catalog; `PREMIUM_MODELS`) |
| 9 | Other hard-coded model ids and context windows | `model_refs` / catalog vs `settings.py:27`, `product_gate_analyzer.py:58`, `adapter_factory.py:66,68`, `mixture_of_agents.py:122`, `osworld/*`, `core/model_cascade_tracker.py:78`, `resilient_adapter.py:103`, `_multimodal.py:29-36`, `core/memory.py:26-37` | yes | done for live code (zero model-id literals outside `model_refs`, pinned by `test_w61_model_ssot.py`); deferred: `_multimodal` vision markers and `core/memory.py` context table, which have no production caller |
| 10 | Sessions DB path | `settings.SESSIONS_DB` vs about 15 literal `"./weebot_sessions.db"` defaults; dashboard resolves its own | yes when `WEEBOT_SESSIONS_DB` is set | done (every default is `DB_SESSIONS_PATH`; `test_ssot_sessions_db_path.py`) |
| 11 | Provider to API-key table | `settings._PROVIDER_KEYS` vs `adapter_factory._SETTINGS_FIELD_MAP` and adapter `os.getenv` calls | yes | done (`kimi_api_key` also reads `MOONSHOT_API_KEY`; `test_ssot_provider_keys.py` checks both tables agree) |
| 12 | `WEEBOT_API_KEY` read two ways | `settings.weebot_api_key` vs `web/auth.py:41` `os.environ` | latent | deferred (agree at runtime: the web app loads `.env` into `os.environ` with override before either reads) |
| 13 | `WEEBOT_AUTO_APPROVE` format | `cli/ui.py:121` (`== "1"`) vs docs (bool) | yes | done (doc now says set to 1; code unchanged, fails closed) |
| 14 | Browser headless and timeout defaults | settings, `browser_tool.py`, `di/_factories.py:490`, `playwright_adapter.py`, `browser_inspector.py` | yes | deferred (the tools differ on purpose: inspector headless, browser tool visible; aligning changes behaviour) |
| 15 | Application version | `VERSION` vs `health.py:505`, `behavior_tracker.py:432`, `mcp/server.py:571` | yes | done (`weebot.__version__` everywhere; `test_ssot_version.py`) |
| 16 | Role to tools registries | `tool_registry.DEFAULT_ROLE_MAPPINGS` vs `expert_profile.BUILTIN_EXPERTS`, `image_search.allowed_roles` | yes | done for the dead copy (`expert_profile.py` and `get_profile_for_role` had no caller, deleted); `image_search.allowed_roles` against `DEFAULT_ROLE_MAPPINGS` waits for the registry autodiscovery fix (F32, W5.5) |
| 17 | Shell/exec tool name sets | `tool_guards.SHELL_TOOLS` vs `step_evidence_auditor`, `tool_registry._sandbox_port_tools`, `code_reviewer_service.WRITE_TOOLS` | yes (`shell_exec`) | done for the shell set (`test_ssot_shell_tool_names.py`); the write-tool sets mean different things |
| 18 | Two error families | `domain/exceptions.py` vs `core/error_system_base.py`, `web/error_codes.py` | yes | done (the `core` family had no importer outside itself: four modules, about 1,000 lines, deleted; `test_ssot_error_family.py`) |
| 19 | `NotificationLevel` twice | `ports/notification_port.py` vs `infrastructure/notifications/notifications.py` | yes | done (`test_ssot_notification_level.py`) |
| 20 | `TaskCategory` names two concepts | `task_model_router.py:16` vs `domain/models/task_route.py:18` | yes | deferred (two concepts, not one fact; recorded as a name collision in `map/CONTEXT.md`) |
| 21 | Feature-flag defaults vs their docs; dead `VS_ENABLE_*` constants | `feature_flags.py:3,81,90`, `constants.py:226-240` | yes | done (docs now match the defaults; dead `VS_ENABLE_*` deleted). Open decision for the user: `WEEBOT_VISION_REFLECTION` is on by default and doubles image tokens |
| 22 | Dead settings and constants that look canonical | `settings.py` `http_*`, `drift_*`, `skills_hub_catalog_url`, `gateway_allowed_platforms`; unused `constants.py` entries | yes | done (36 unread settings fields and `drift_monitoring.yaml` deleted); `slack_webhook_url`, `stripe_webhook_secret`, `daily_ai_budget` stay: read by env name elsewhere |
| 23 | Log file and memory dir | `settings.LOG_FILE`, `MEMORY_DIR` vs `utils/logger.py:9`, `filesystem_memory.py:23` | yes when env set | done (`LOG_FILE`, `MEMORY_DIR` from settings) |
| 24 | Port and URL defaults; UI backend URL in 8 files | settings vs `scraper.py`, `signal.py`, `reasoner.py`, `berb.py`, `weebot-ui/src/**` | yes (port clashes, WS path) | done for the UI (`weebot-ui/src/lib/endpoints.ts`; fixed the behavior socket, which never reached `/api/behavior/ws`); deferred: external services' default ports |
| 25 | Ponytail modes and mode-file path | `ponytail_skill_prompt.py` vs 4 copies | dup | done for the mode set (`PONYTAIL_MODES`); the mode-file path stays in two places (read at import in the CLI, at call time in the service) |
| 26 | Docs restating code counts | `ARCHITECTURE.md:53,61,63,225,226`; `CLAUDE.md` ceiling location | yes | done (counts replaced by pointers; `CLAUDE.md` names `tasks/quality/ceilings.toml`; twins regenerated) |
| 27 | CLI command name in docs | `docs/ENTRY_POINTS.md:15` `skills list` vs `skill list` | yes | done |
| 28 | Provider base URLs | `config/api_endpoints.py` vs about 15 literals | dup | done (`test_ssot_api_endpoints.py`) |
| 29 | Small repeated literals (`_LOOPBACK`, `"mcp__"`, harness version default, PowerShell keywords, `MAX_RETRIES`) | first-named file | dup | done (`_LOOPBACK`, `mcp__`, `DEFAULT_HARNESS_VERSION`; unread settings copy of the PowerShell keywords deleted); `MAX_RETRIES` in `core/agent.py` left (ADR-009 sunset) |
| 30 | Stale citation | `map/CONTEXT.md:24` cites the deleted second `ModelConfig` | yes | done |

Not checked: `drift_monitoring.yaml` against the `drift_*` fields (both dead), prompt and template text, the rest of `weebot-ui`, and which entry points call `load_dotenv`.

