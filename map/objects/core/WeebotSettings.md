---
type: object
name: WeebotSettings
code: WeebotSettings, OSWorldSettings
cluster: core
universe: live
status: verified
verified: 2026-10-21
commit: f00ea38
---

# WeebotSettings

The typed configuration object: API keys, gateway secrets, sandbox limits, feature flags and tuning knobs, read from `.env` and the process environment. Since 2026-10-22 (W2) there is one shared instance: `get_settings()` in `config/settings.py`, also bound in the DI container as `WeebotSettings`. Line numbers below are from `f00ea38`.

## Why this shape
A pydantic `BaseSettings` so values are validated once at construction (`weebot/config/settings.py:36-49`). Source order puts constructor arguments first, then the repo-root `.env`, then the process environment, then a secrets directory (`:51-69`): the `.env` file deliberately wins over stale system variables, and explicit arguments win over both so tests can construct it directly.

## Shape
- Field groups (`:71-444`): provider keys; Reasoner, Berb and Scraper endpoints; web auth; Discord, Telegram, Slack, WhatsApp, Stripe, Signal and email gateways; budget; skill indexes; sandbox (`sandbox_mode`, timeouts, output cap, network); drift monitoring; HTTP client; MCP client; ponytail mode; gateway sessions; context engine; cron; plan review and CoVe flags; scalability (`llm_max_concurrent_requests`, `max_concurrent_flows`); security flags.
- Validators: budget above zero, timeouts above zero, sandbox mode in a fixed set, output cap at least 1024, ponytail mode in a fixed set (`:176-209, 304-311`).
- `validate_at_least_one_key()` and `available_providers()` (`:445-475`).
- Not part of the class: module constants `WORKSPACE_ROOT`, `LOGS_DIR`, `SESSIONS_DB`, `MEMORY_DIR`, `PROFILES_DIR`, read with `os.getenv` at import (`:8-20`). The entry points call `load_dotenv(override=True)` before importing (`run.py:14-17`, `cli/main.py:59-61`, `run_mcp.py:20-22`); other entry points were not checked.
- `OSWorldSettings` moved to `weebot/config/osworld_settings.py` (W2.4); its only reader is `infrastructure/sandbox/osworld.py`.

Construction sites: none outside `config/settings.py` since W2.3 (2026-10-22); there were 43 at the start of Wave 2. `scripts/lint_settings_construction.py` holds it at 0 (ceiling `settings_construction`). Read it with `get_settings()` or `Container.get(WeebotSettings)`; a changed `.env` takes effect on restart.

Consequences (read from source, not run; `pydantic_settings` is not installed here):
- Fixed 2026-10-22 (W1.1): `run_mcp.py:87` called `validate_at_least_one_key()` on the class and raised `TypeError`. It now builds an instance; `tests/unit/fixes/test_f13_run_mcp_key_check.py` runs `main()` unpatched.
- `financial_tools_always_ask` (`:435`) has no reader anywhere in the repo. It matches the `finance` and `payment` approval categories that have no live caller (see the ExecApprovalPolicy card).
- Fixed 2026-10-22 (W1.3, W1.4): both key methods read one `_PROVIDER_KEYS` table, which includes xai. `reasoner_dir`, `berb_dir` and `scraper_dir` default to None; the tools refuse their CLI path by name when unset (`config/tool_config.py: require_setting`).
- The comment at `:376-379` says both `WEEBOT_PLAN_REVIEW_ENABLED` and `PLAN_REVIEW_ENABLED` are accepted for `plan_review_enabled`, which has an alias. Unverified: needs a run with `pydantic_settings` installed.
- Fixed 2026-10-23 (SSOT audit row 1): there is no `env_prefix`, so a field is read from its bare upper-case name unless it has an alias. Eight fields documented as `WEEBOT_*` (web auth, webhook key and exec tools, gateway auth and session limits, MCP composite tools, ponytail mode) read nothing under that name; they now take `validation_alias=AliasChoices("WEEBOT_X", "X")`. `tests/unit/config/test_weebot_env_names.py` fails on any documented `WEEBOT_*` name without a reader. `.env.example` and `docs/CONFIGURATION.md` take field defaults from this class (`scripts/generate_config_reference.py: resolved_schema`). The `ToolConfig` the DI container binds is built from this class (`config/tool_config.py: tool_config_from_settings`).
- Fixed 2026-10-22 (W2): every caller used to build its own `WeebotSettings()`, re-reading `.env` each time. The module constants (`WORKSPACE_ROOT` and the rest) are still read with `os.getenv` at import; they stay import-time constants by decision (plan W2.4b option a), because tools read `WORKSPACE_ROOT` in class bodies.

## Connected to
- **Built by** `get_settings()` only; resolved from the DI container as `WeebotSettings`.
- **Related:** `SecretAccessor` (the sanctioned way to read secrets, root `CLAUDE.md` rule 6), `weebot/config/model_refs.py` (model ids), `.env.example` and `docs/CONFIGURATION.md`.
- **Looks like but is not:** the module constants above (same names of concern, read differently); `OSWorldSettings` (same file, other subsystem).

## If you change this
**Hits:** every `get_settings()` reader (about 40 modules); the lint gates `lint-env-access`, `lint-settings-construction` and `scripts/quality_ceilings.py`; the DI binding in `Container.configure_defaults()`; tests `tests/unit/test_settings.py`, `tests/unit/test_settings_validation.py`, `tests/unit/test_sandbox_config.py`, `tests/unit/config/test_ponytail_settings.py`, `tests/unit/config/test_get_settings.py`, and the `_no_dotenv_settings` and `_fresh_settings_cache` fixtures in `tests/conftest.py`.
**Does not hit:** the model catalog.

## Surfaces
`.env` and environment variables (operators); `python -m cli.main health` and `doctor`.

## See
`weebot/config/settings.py`
