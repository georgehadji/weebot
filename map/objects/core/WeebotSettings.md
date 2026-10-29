---
type: object
name: WeebotSettings
code: WeebotSettings
cluster: core
universe: live
status: verified
verified: 2026-10-29
commit: 9e524c75
---

# WeebotSettings

The typed configuration object: API keys, gateway secrets, sandbox limits, guard and feature flags and tuning knobs, read from `.env` and the process environment. There is one shared instance: `get_settings()` (`weebot/config/settings.py:498-507`), also bound in the DI container as `WeebotSettings` (`weebot/application/di/__init__.py:141-146`).

## Why this shape
A pydantic `BaseSettings` so values are validated once at construction (`weebot/config/settings.py:37-50`). Source order puts constructor arguments first, then the repo-root `.env`, then the process environment, then a secrets directory (`:49-67`): the `.env` file deliberately wins over stale system variables, and explicit arguments win over both so tests can construct it directly.

## Shape
- Field groups: provider keys (`:69-77`); Reasoner, Berb and Scraper endpoints (`:79-92`); web auth and webhook (`:94-114`); Discord, Telegram/Slack notifications, Slack, WhatsApp, Stripe, Signal and email gateways (`:116-159`); budget (`:161-162`); skill indexes (`:164-172`); sandbox (`sandbox_mode`, isolation, timeouts, output cap, `sandbox_allow_network`) (`:174-185`); tool guard chain mode and intent-review timeout (`:187-201`); MCP client (`:246-276`); ponytail mode (`:278-294`); gateway sessions and auth (`:296-321`); context engine (`:323-336`); plan review and CoVe flags (`:338-354`); scalability (`llm_max_concurrent_requests`, `llm_pool_acquire_timeout_s`, `max_concurrent_flows`) (`:360-385`); financial and outbound tool patterns, secret redaction (`:386-418`).
- Validators: guard mode in `observe`/`enforce`, budget above zero, timeouts above zero, sandbox mode in a fixed set, output cap at least 1024, ponytail mode in `PONYTAIL_MODES` (`:203-244, 287-294`, set at `:30-31`).
- `validate_at_least_one_key()` and `available_providers()` both read one `_PROVIDER_KEYS` table, which includes xai (`:420-444`).
- There is no `env_prefix` (`:42-47`), so a field is read from its bare upper-case name unless it has an alias; fields documented as `WEEBOT_*` take `validation_alias=AliasChoices("WEEBOT_X", "X")` (for example `:96-114, 282-283, 313-314`). `tests/unit/config/test_weebot_env_names.py` fails on any documented `WEEBOT_*` name without a reader.
- Not part of the class: module constants `WORKSPACE_ROOT`, `LOGS_DIR`, `SESSIONS_DB`, `MEMORY_DIR`, `PROFILES_DIR`, read with `os.getenv` at import (`:16-27`). They stay import-time constants by decision (plan W2.4b option a), because tools read `WORKSPACE_ROOT` in class bodies. The entry points call `load_dotenv(override=True)` before importing (`run.py:17`, `cli/main.py:59-61`, `run_mcp.py:19-21`); other entry points were not checked.

Construction sites: none outside `config/settings.py` (grep 2026-10-24; the DI container registers `get_settings` itself, `di/__init__.py:145`). `scripts/lint_settings_construction.py` holds it at 0 (`tasks/quality/ceilings.toml:299-300`, run from `Makefile:124`). Read it with `get_settings()` or `Container.get(WeebotSettings)`; a changed `.env` takes effect on restart (`settings.py:500-506`).

Consequences (read from source, not run; `pydantic_settings` is not installed here):
- `run_mcp.py:102` calls `get_settings().validate_at_least_one_key()` on an instance; `tests/unit/fixes/test_f13_run_mcp_key_check.py` covers it.
- `financial_tools_always_ask` (`settings.py:437-439`) is read by the tool guard chain (`weebot/application/services/tool_guards.py:247`).
- `reasoner_dir`, `berb_dir` and `scraper_dir` default to None (`settings.py:99, 104, 92`); the tools refuse their CLI path by name when unset (`weebot/config/tool_config.py:92`, `require_setting`).
- The comment at `settings.py:372-374` says both `WEEBOT_PLAN_REVIEW_ENABLED` and `PLAN_REVIEW_ENABLED` are accepted for `plan_review_enabled`, which has only `alias="WEEBOT_PLAN_REVIEW_ENABLED"` (`:342-346`). Whether the bare name is read was not run.
- `.env.example` and `docs/CONFIGURATION.md` take field defaults from this class (`scripts/generate_config_reference.py:382`, `resolved_schema`). The `ToolConfig` the DI container binds is built from it (`weebot/config/tool_config.py:59`, `di/__init__.py:146`).

## Connected to
- **Built by** `get_settings()` only; resolved from the DI container as `WeebotSettings`.
- **Related:** `SecretAccessor` (the sanctioned way to read secrets, root `CLAUDE.md` rule 6), `weebot/config/model_refs.py` (model ids), `.env.example` and `docs/CONFIGURATION.md`.
- **Looks like but is not:** the module constants above (same concerns, read differently).

## If you change this
**Hits:** every `get_settings()` reader (32 modules in `weebot/`, `cli/` and the root entry points, grep 2026-10-24); the lint gates `lint-env-access`, `lint-settings-construction` and `scripts/quality_ceilings.py`; the DI binding in `Container.configure_defaults()`; the generated config reference; tests `tests/unit/test_settings.py`, `tests/unit/test_settings_validation.py`, `tests/unit/test_sandbox_config.py`, `tests/unit/config/test_ponytail_settings.py`, `tests/unit/config/test_get_settings.py`, `tests/unit/config/test_weebot_env_names.py`, and the `_no_dotenv_settings` and `_fresh_settings_cache` fixtures (`tests/conftest.py:57, 83`).
**Does not hit:** the model catalog.

## Surfaces
`.env` and environment variables (operators); `python -m cli.main health` and `doctor`.

## See
`weebot/config/settings.py`
