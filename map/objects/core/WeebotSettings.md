---
type: object
name: WeebotSettings
code: WeebotSettings
cluster: core
universe: live
status: verified
verified: 2026-10-31
commit: f238f23a
---

# WeebotSettings

The typed configuration object: API keys, gateway secrets, sandbox limits, guard and feature flags and tuning knobs, read from `.env` and the process environment. There is one shared instance: `get_settings()` (`weebot/config/settings.py:538-547`), also bound in the DI container as `WeebotSettings` (`weebot/application/di/__init__.py:141-146`).

## Why this shape
A pydantic `BaseSettings` so values are validated once at construction (`weebot/config/settings.py:37-50`). Source order puts constructor arguments first, then the repo-root `.env`, then the process environment, then a secrets directory (`weebot/config/settings.py:52-70`): the `.env` file deliberately wins over stale system variables, and explicit arguments win over both so tests can construct it directly.

## Shape
- Field groups: provider keys, Ollama and free-tier providers (`weebot/config/settings.py:72-101`); Reasoner, Berb and Scraper endpoints (`weebot/config/settings.py:103-116`); web auth and webhook (`weebot/config/settings.py:118-138`); Discord, Telegram/Slack notifications, Slack, WhatsApp, Stripe, Signal and email gateways (`weebot/config/settings.py:140-184`); budget (`weebot/config/settings.py:186-187`); skill indexes (`weebot/config/settings.py:189-197`); sandbox (`sandbox_mode`, isolation, timeouts, output cap, `sandbox_allow_network`) (`weebot/config/settings.py:199-210`); tool guard chain mode and intent-review timeout (`weebot/config/settings.py:244-266`); MCP client (`weebot/config/settings.py:319-349`); ponytail mode (`weebot/config/settings.py:351-367`); gateway sessions and auth (`weebot/config/settings.py:369-394`); context engine (`weebot/config/settings.py:396-409`); plan review and CoVe flags (`weebot/config/settings.py:411-427`); scalability (`llm_max_concurrent_requests`, `llm_pool_acquire_timeout_s`, `max_concurrent_flows`) (`weebot/config/settings.py:433-475`); financial and outbound tool patterns, secret redaction (`weebot/config/settings.py:477-509`).
- Browser CDP: `browser_cdp_url`, `browser_cdp_fallback`, `browser_cdp_connect_timeout_ms`, `browser_cdp_share_connection` and `browser_cdp_max_connections` (`weebot/config/settings.py:214-242`), read together by `CdpSettings.from_settings` (`weebot/infrastructure/browser/browser_launcher.py:46`); see `infrastructure/Browser.md`.
- Validators: guard mode in `observe`/`enforce`, budget above zero, timeouts above zero, sandbox mode in a fixed set (now including `modal`), output cap at least 1024, ponytail mode in `PONYTAIL_MODES` (`weebot/config/settings.py:268-317, 328-335`, set at `weebot/config/settings.py:33-34`). Shell default-ask is also validated (`off`/`observe`/`enforce`).
- `validate_at_least_one_key()` and `available_providers()` both read one `_PROVIDER_KEYS` table, which includes xai (`weebot/config/settings.py:511-535`).
- There is no `env_prefix` (`weebot/config/settings.py:45-50`), so a field is read from its bare upper-case name unless it has an alias; fields documented as `WEEBOT_*` take `validation_alias=AliasChoices("WEEBOT_X", "X")` (for example `weebot/config/settings.py:121, 129, 324, 342-343`). `tests/unit/config/test_weebot_env_names.py` fails on any documented `WEEBOT_*` name without a reader.
- Not part of the class: module constants `WORKSPACE_ROOT`, `LOGS_DIR`, `SESSIONS_DB`, `MEMORY_DIR`, `PROFILES_DIR`, read with `os.getenv` at import (`weebot/config/settings.py:19-30`). They stay import-time constants by decision (plan W2.4b option a), because tools read `WORKSPACE_ROOT` in class bodies. The entry points call `load_dotenv(override=True)` before importing (`run.py:17`, `cli/main.py:59-61`, `run_mcp.py:19-21`); other entry points were not checked.

Construction sites: none outside `config/settings.py` (grep 2026-10-24; the DI container registers `get_settings` itself, `weebot/application/di/__init__.py:145`). `scripts/lint_settings_construction.py` holds it at 0 (`tasks/quality/ceilings.toml:303-304`, run from `Makefile:164-166`). Read it with `get_settings()` or `Container.get(WeebotSettings)`; a changed `.env` takes effect on restart (`weebot/config/settings.py:538-547`).

Consequences (read from source, not run; `pydantic_settings` is not installed here):
- `run_mcp.py:102` calls `get_settings().validate_at_least_one_key()` on an instance; `tests/unit/fixes/test_f13_run_mcp_key_check.py` covers it.
- `financial_tools_always_ask` (`weebot/config/settings.py:477-479`) is read by the tool guard chain (`weebot/application/services/tool_guards.py:254`).
- `reasoner_dir`, `berb_dir` and `scraper_dir` default to None (`weebot/config/settings.py:106, 111, 116`); the tools refuse their CLI path by name when unset (`weebot/config/tool_config.py:92-95`, `require_setting`).
- The comment at `weebot/config/settings.py:412-414` says both `WEEBOT_PLAN_REVIEW_ENABLED` and `PLAN_REVIEW_ENABLED` are accepted for `plan_review_enabled`, which has only `alias="WEEBOT_PLAN_REVIEW_ENABLED"` (`weebot/config/settings.py:415-419`). Whether the bare name is read was not run.
- `.env.example` and `docs/CONFIGURATION.md` take field defaults from this class (`scripts/generate_config_reference.py:401`, `resolved_schema`). The `ToolConfig` the DI container binds is built from it (`weebot/config/tool_config.py:59-73`, `weebot/application/di/__init__.py:146`).

## Connected to
- **Built by** `get_settings()` only; resolved from the DI container as `WeebotSettings`.
- **Related:** `SecretAccessor` (the sanctioned way to read secrets, root `CLAUDE.md` rule 6), `weebot/config/model_refs.py` (model ids), `.env.example` and `docs/CONFIGURATION.md`.
- **Looks like but is not:** the module constants above (same concerns, read differently).

## If you change this
**Hits:** every `get_settings()` reader (34 files in `weebot/`, `cli/` and the root entry points, grep 2026-10-31); the lint gates `lint-env-access`, `lint-settings-construction` and `scripts/quality_ceilings.py`; the DI binding in `Container.configure_defaults()`; the generated config reference; tests `tests/unit/test_settings.py`, `tests/unit/test_settings_validation.py`, `tests/unit/test_sandbox_config.py`, `tests/unit/config/test_ponytail_settings.py`, `tests/unit/config/test_get_settings.py`, `tests/unit/config/test_weebot_env_names.py`, and the `_no_dotenv_settings` and `_fresh_settings_cache` fixtures (`tests/conftest.py:74, 100`).
**Does not hit:** the model catalog.

## Surfaces
`.env` and environment variables (operators); `python -m cli.main health` and `doctor`.

## See
`weebot/config/settings.py`
