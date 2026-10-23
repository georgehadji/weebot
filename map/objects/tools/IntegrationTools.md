---
type: object
name: Integration tools
code: AtomicMailTool, ApifyActorTool, ApifyService, ProductTool, DesignSystemTool, MCPToolAdapter
cluster: tools
universe: live
status: verified
verified: 2026-10-23
commit: 2be1ab8a
---

# Integration tools

Tools that talk to an outside service: the agent-owned mail inbox (`atomic_mail`), Apify actors (`apify_*`), the product backlog (`product`), design-token extraction (`design_system`), and the external MCP servers (Postiz, Jira, HubSpot) whose tools join the tool set as `mcp__<server>__<tool>`.

## Why this shape
Native integrations are `BaseTool`s in the role table. Apify and MCP tools are generated at runtime (one tool per preset or per remote tool), so the registry cannot build them by name; `build_tools` appends them after the registry collection and wraps the result in the guard chain again (`weebot/interfaces/factories.py:370-421`). Publish/send actions on those remote tools are recognised by name only (`weebot/application/services/tool_guards.py:239-252`).

## Shape
- `atomic_mail`: `AtomicMailTool` `weebot/tools/atomic_mail_tool.py:55`, actions `register`, `jmap_request`, `help` (`:45`); runs the vendored client's `handle_tool_call` in a thread with a 60 s timeout (`:48-52, 151-193`) behind a module circuit breaker (3 failures, 60 s, `:42`). `WEEBOT_ENABLE_ATOMIC_MAIL` is read only in `health_check` (`:256-258`). Roles: automation, admin, webhook (`weebot/tools/tool_registry.py:56-67, 70-113, 114-155`).
- `apify_*`: ten presets in `weebot/tools/apify_presets.py:23-220` (`apify_web_scraper`, `apify_google_search`, `apify_google_images`, `apify_youtube_transcript`, `apify_linkedin_jobs`, `apify_twitter_scraper`, `apify_reddit_scraper`, `apify_website_to_markdown`, `apify_email_finder`, `apify_bing_search`), each an `ApifyActorTool` (`weebot/tools/apify_actor_tool.py:30`) bound to one `actor_id`; `execute` forwards `run_input` or, if absent, the remaining kwargs (`:39-55`). `ApifyService` reads `APIFY_API_KEY` (`weebot/infrastructure/adapters/apify/apify_service.py:62-63`) and opens two `aiohttp` sessions in `initialize` (`:79-88`). Added only by `build_tools` when `APIFY_API_KEY` is set (`factories.py:394-412`); in no role.
- `product`: `ProductTool` `weebot/tools/product_tool.py:24`, needs `repo: ToolRepositoryPort` positionally (`:91-95`). Roles: documentation, product_manager, admin, webhook.
- `design_system`: `DesignSystemTool` `weebot/tools/design_system_tool.py:14`, runs `npx skillui` with `subprocess.run` in a temp dir (`:66-76, 124-138`). Roles: admin, webhook.
- External MCP: `config/mcp_servers.json` names `postiz` (streamable-http, `POSTIZ_API_KEY`), `jira` (`uvx mcp-atlassian`) and `hubspot` (`npx -y @hubspot/mcp-server`). `_create_mcp_client` returns an empty manager unless `WEEBOT_ENABLE_X_MCP` is on, then loads `mcp_servers_config_path` and expands `${VAR}`s, letting `ConfigError` propagate (`application/di/_factories.py:300-340`). `_configured_mcp_tools` connects once per process and caches the `MCPToolkitAdapter` (`factories.py:109-141`); each remote tool becomes an `MCPToolAdapter` named by `build_namespaced_name` (`weebot/infrastructure/mcp/mcp_toolkit_adapter.py:11-50`, `mcp_client_manager.py:200-210`). A `mcp_config` argument to `build_tools` builds a separate adapter instead (`factories.py:378-387`).

Approval, read from source:
- `guard_tools` wraps a tool if its name is a shell tool, matches `WEEBOT_FINANCIAL_TOOL_PATTERNS` or matches `WEEBOT_OUTBOUND_TOOL_PATTERNS` (`tool_guards.py:429-450`). Outbound default: `*schedulepost*,*deletepost*,*publish*,*send_email*,*send_mail*,*send_reply*,*send_message*,*tweet*,*generate*,*clipping*` (`weebot/config/settings.py:394-404`); a match always asks, even in observe mode unless `WEEBOT_OUTBOUND_ASK_IN_OBSERVE=false` (`tool_guards.py:255-275`, `settings.py:405-409`). Postiz post tools match; `SECURITY_MODEL.md:17` names `mcp__postiz__schedulePostTool`.
- `atomic_mail` matches no pattern; its sends are gated by `EgressGuard` instead: a `jmap_request` that is not a dry run and not the `list_inbox` preset, or inline `ops` containing `EmailSubmission`, is egress to `vars.TO` or to an unknown recipient (`weebot/core/egress_guard.py:186-191, 400-417`). Fetched mail is fenced as untrusted (`weebot/core/trust_boundary.py:85`) and the next step pauses for review (`application/flows/states/executing.py:107-120, 287-296, 493-496`; category `inbound_mail` `weebot/core/approval_policy.py:592-594`).

Consequences (read from source, not run):
- `product` is never built by the registry: it is not in `wiring()["collaborators"]` (`application/di/_factories.py:449-457`), so it falls to the bare `tool_cls()` branch, whose `TypeError` is logged at debug and skipped (`tool_registry.py:487-497`). No `ProductTool(` call exists outside tests. The docstring's sqlite fallback (`product_tool.py:3-4`) is gone.
- Apify output is neither fenced nor egress-tainting: the trust list names `apify_actor_tool` (`trust_boundary.py:74`), but the tools are named `apify_web_scraper` and so on, and `is_untrusted_tool` matches exact names or the `mcp__` prefix only (`trust_boundary.py:140-152`).
- `design_system` output (pages and repos it scrapes) is not in `UNTRUSTED_OUTPUT_TOOLS` (`trust_boundary.py:49-93`). On a "not found" failure it runs `npm install -g skillui` unasked (`design_system_tool.py:86-98`); token-file parse errors are swallowed with `except Exception: pass` (`:172-181`).
- Apify actors spend credits and `apify_email_finder` harvests addresses (`apify_presets.py:186-188`), but no `apify_*` name matches the outbound patterns, so they never ask.
- Jira and HubSpot write tools ask only if their remote names contain a listed pattern; the defaults have no `*create*` or `*update*` (inferred: the remote tool names are not in this repo).
- Each `build_tools` call with `APIFY_API_KEY` set builds and initialises a new `ApifyService` (`factories.py:406-408`); nothing calls its `shutdown` (`apify_service.py:90-96`), so its two `aiohttp` sessions stay open. `ApifyActorRegistry` (`adapters/apify/actor_registry.py:33`) is exported (`adapters/apify/__init__.py:4`) and used nowhere.
- `.weebot/skills/apify-scraper/SKILL.md` lists exactly the ten preset names and `APIFY_API_KEY` (`:5-6, 17-28`), matching `apify_presets.py` and `factories.py:399`. Its `requires_env` key is not read by `SkillRegistry`, which takes `env` from `metadata` (`application/skills/skill_registry.py:144`), so the skill counts as ready without the key.

## Connected to
- **Built by** `build_tools` (`factories.py:348`), callers `interfaces/cli/agent_runner.py:71`, `interfaces/web/routers/sessions.py:291`, `interfaces/web/routers/webhook.py:124`, the gateways (`interfaces/gateways/*.py`), `application/use_cases/dispatch_session_input.py:83, 106`. Native ones also by `RoleBasedToolRegistry` (card `tools/RoleBasedToolRegistry.md`).
- **Gated by** `EgressGuard`, the guard chain (`GuardedTool`), the trust boundary; cards `core/EgressGuard.md`, `core/ExecApprovalPolicy.md`.
- **Looks like but is not:** `MCPToolRegistryBridge` (`application/services/mcp_tool_registry_bridge.py`), which only adds MCP names to roles; `weebot/mcp/server.py`, Weebot's own MCP server.

## If you change this
**Hits:** `tests/unit/tools/test_atomic_mail_tool.py`, `tests/unit/adapters/test_atomicmail_preset_names.py`, `tests/unit/test_executing_inbound_mail_gate.py`, `tests/unit/test_egress_guard.py`, `tests/unit/core/test_trust_boundary.py`, `tests/unit/core/test_trust_boundary_registry.py`, `tests/unit/test_trust_boundary.py`, `tests/unit/security/test_security_gates_fail_closed.py`, `tests/e2e/test_gate_pause_survives_the_seam.py`, `tests/unit/test_apify_actor_tool.py`, `tests/unit/test_apify_service.py`, `tests/unit/fixes/test_outbound_tools_ask.py`, `tests/unit/fixes/test_f06_financial_tools_ask.py`, `tests/unit/interfaces/test_build_tools_configured_mcp.py`, `tests/unit/fixes/test_mcp_toolkit_closed_on_exit.py`, `tests/unit/tools/test_product_tool.py`, `tests/unit/test_regression_tool_name_collision.py`.
**Does not hit:** the shell guards (`BashGuard`) for `atomic_mail`; the role table for `apify_*` and `mcp__*`.

## Surfaces
Every agent role built through `build_tools`; outbound asks reach the user through the approval channel (CLI prompt, web pause; refused in cron and webhooks, `webhook.py:139-143`).

## See
`weebot/interfaces/factories.py`
