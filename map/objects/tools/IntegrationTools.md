---
type: object
name: Integration tools
code: AtomicMailTool, ApifyActorTool, ApifyService, ProductTool, DesignSystemTool, MCPToolAdapter
cluster: tools
universe: live
status: stale
stale_reason: 2026-10-24 remediation moved code these citations point at (tool registry, trust boundary, flow builder, DI); re-verify against source
verified: 2026-10-24
commit: d4ffb555
---

# Integration tools

Tools that talk to an outside service: the agent-owned mail inbox (`atomic_mail`), Apify actors (`apify_*`), the product backlog (`product`), design-token extraction (`design_system`), and the external MCP servers (Postiz, Jira, HubSpot) whose tools join the tool set as `mcp__<server>__<tool>`.

## Why this shape
Native integrations are `BaseTool`s in the role table. Apify and MCP tools are generated at runtime (one tool per preset or per remote tool), so the registry cannot build them by name; `build_tools` appends them after the registry collection (`weebot/interfaces/factories.py:388-430`) and wraps the result in the guard chain again (`weebot/interfaces/factories.py:432-439`). Publish/send/spend actions on those tools are recognised by name, and an MCP tool not named like a read asks (`weebot/application/services/tool_guards.py:241-257`).

## Shape
- `atomic_mail`: `AtomicMailTool` `weebot/tools/atomic_mail_tool.py:55`, actions `register`, `jmap_request`, `help` (`weebot/tools/atomic_mail_tool.py:45`); runs the vendored client's `handle_tool_call` in a thread with a 60 s timeout (`weebot/tools/atomic_mail_tool.py:48-52, 151-193`) behind a module circuit breaker (3 failures, 60 s, `weebot/tools/atomic_mail_tool.py:42`). `WEEBOT_ENABLE_ATOMIC_MAIL` is read only in `health_check` (`weebot/tools/atomic_mail_tool.py:256-258`). Roles: automation, admin, webhook (`weebot/tools/tool_registry.py:69, 111, 159`).
- `apify_*`: ten presets in `weebot/tools/apify_presets.py:23-220` (`apify_web_scraper`, `apify_google_search`, `apify_google_images`, `apify_youtube_transcript`, `apify_linkedin_jobs`, `apify_twitter_scraper`, `apify_reddit_scraper`, `apify_website_to_markdown`, `apify_email_finder`, `apify_bing_search`), each an `ApifyActorTool` (`weebot/tools/apify_actor_tool.py:30`) bound to one `actor_id`; `execute` forwards `run_input` or, if absent, the remaining kwargs (`weebot/tools/apify_actor_tool.py:39-55`). `ApifyService` reads `APIFY_API_KEY` (`weebot/infrastructure/adapters/apify/apify_service.py:62-63`) and opens two `aiohttp` sessions in `initialize` (`weebot/infrastructure/adapters/apify/apify_service.py:79-88`). Added only by `build_tools` when `APIFY_API_KEY` is set (`weebot/interfaces/factories.py:412-430`); in no role. `config/mcp_servers.json` also lists Apify's hosted MCP server (`apify`, any Actor, same key).
- `product`: `ProductTool` `weebot/tools/product_tool.py:24`, needs `repo: ToolRepositoryPort` (`weebot/tools/product_tool.py:91-95`), supplied by `Container.tool_wiring` (`weebot/application/di/_factories.py:458, 465`). Roles: documentation, product_manager, admin, webhook (`weebot/tools/tool_registry.py:71-72, 101, 152`).
- `design_system`: `DesignSystemTool` `weebot/tools/design_system_tool.py:14`, runs `npx skillui` with `subprocess.run` in a temp dir (`weebot/tools/design_system_tool.py:66-76, 101-116`). Role: admin only; `webhook` drops it (`weebot/tools/tool_registry.py:108, 125-127`).
- External MCP: `config/mcp_servers.json` names `postiz` (streamable-http, `POSTIZ_API_KEY`), `jira` (`uvx mcp-atlassian`), `hubspot` (`npx -y @hubspot/mcp-server`) and `apify` (streamable-http, `APIFY_API_KEY`). `_create_mcp_client` returns an empty manager unless `WEEBOT_ENABLE_X_MCP` is on, then loads `mcp_servers_config_path` and expands `${VAR}`s per server: a server with an unset variable is skipped with a warning, any other load error leaves an empty manager (`weebot/application/di/_factories.py:300-351`). `_configured_mcp_tools` connects once per process and caches the `MCPToolkitAdapter` (`weebot/interfaces/factories.py:109-141`); each remote tool becomes an `MCPToolAdapter` (`weebot/infrastructure/mcp/mcp_toolkit_adapter.py:11-25`) named by `build_namespaced_name` (`weebot/infrastructure/mcp/mcp_client_manager.py:245-255`). A `mcp_config` argument to `build_tools` builds a separate adapter instead (`weebot/interfaces/factories.py:396-405`).

Approval, read from source:
- `guard_tools` wraps a tool if its name is a shell tool, matches `WEEBOT_FINANCIAL_TOOL_PATTERNS` or is outbound (`weebot/application/services/tool_guards.py:476-497`). Outbound means a match of `WEEBOT_OUTBOUND_TOOL_PATTERNS`, default `*schedulepost*,*deletepost*,*publish*,*send_email*,*send_mail*,*send_reply*,*send_message*,*tweet*,*generate*,*clipping*,apify_*,image_gen,video_gen,mixture_of_agents` (`weebot/config/settings.py:394-406`), or any `mcp__` tool whose name does not read as a read verb (`weebot/application/services/tool_guards.py:256-257, 260-296`). An outbound tool always asks, even in observe mode unless `WEEBOT_OUTBOUND_ASK_IN_OBSERVE=false` (`weebot/application/services/tool_guards.py:298-318`, `weebot/config/settings.py:407-411`). `docs/SECURITY_MODEL.md` names `mcp__postiz__schedulePostTool`.
- `atomic_mail` matches no pattern; its sends are gated by `EgressGuard` instead: a `jmap_request` that is not a dry run and not the `list_inbox` preset, or inline `ops` containing `EmailSubmission`, is egress to `vars.TO` or to an unknown recipient (`weebot/core/egress_guard.py:194-199, 424-441`). Fetched mail is fenced as untrusted (`weebot/core/trust_boundary.py:86`) and the next step pauses for review (`weebot/application/flows/states/executing.py:106-120, 294-310, 500-503`; category `inbound_mail` `weebot/core/approval_policy.py:592-594`).

Consequences (read from source, not run):
- `ProductTool`'s docstring still promises a sqlite fallback (`weebot/tools/product_tool.py:3-4`); without a `ToolRepositoryPort` the tool is left out of the wiring and skipped (see the RoleBasedToolRegistry card).
- Apify output is fenced as untrusted by its `apify_` prefix (`weebot/core/trust_boundary.py:151-154`), and every `apify_*` call asks (outbound pattern above). `apify_email_finder` harvests addresses (`weebot/tools/apify_presets.py:186-188`).
- `design_system` output (pages and repos it scrapes) is not in `UNTRUSTED_OUTPUT_TOOLS` (`weebot/core/trust_boundary.py:49-95`). When `skillui` is missing it reports the install command instead of installing (`weebot/tools/design_system_tool.py:86-92`); token-file parse errors are swallowed with `except Exception: pass` (`weebot/tools/design_system_tool.py:158-159`).
- Jira, HubSpot and Apify MCP tools ask unless named like a read (`jira_get_issue` reads; anything with a write verb asks, `weebot/application/services/tool_guards.py:260-296`); the remote tool names are not in this repo, so which ones ask is inferred.
- Each `build_tools` call with `APIFY_API_KEY` set builds and initialises a new `ApifyService` (`weebot/interfaces/factories.py:424-425`); `ToolCollection.teardown` shuts it down through the `GuardedTool` (`weebot/application/models/tool_collection.py:119-128`), so its `aiohttp` sessions close only when the owner calls `teardown`. `ApifyActorRegistry` (`weebot/infrastructure/adapters/apify/actor_registry.py:33`) is exported (`weebot/infrastructure/adapters/apify/__init__.py:4`) and used nowhere.
- `.weebot/skills/apify-scraper/SKILL.md` lists exactly the ten preset names and `APIFY_API_KEY` (lines 5-6, 17-28), matching `weebot/tools/apify_presets.py` and `weebot/interfaces/factories.py:417`. Its `requires_env` key is not read by `SkillRegistry`, which takes `env` from `metadata` (`weebot/application/skills/skill_registry.py:158`), so the skill counts as ready without the key.

## Connected to
- **Built by** `build_tools` (`weebot/interfaces/factories.py:360`), callers `weebot/interfaces/cli/agent_runner.py:93`, `weebot/interfaces/web/routers/sessions.py:300, 425`, `weebot/interfaces/web/routers/webhook.py:128`, the gateways (`interfaces/gateways/*.py`), `weebot/application/use_cases/dispatch_session_input.py:83, 106`. Native ones also by `RoleBasedToolRegistry` (card `tools/RoleBasedToolRegistry.md`).
- **Gated by** `EgressGuard`, the guard chain (`GuardedTool`), the trust boundary; cards `core/EgressGuard.md`, `core/ExecApprovalPolicy.md`.
- **Looks like but is not:** `MCPToolRegistryBridge` (`weebot/application/services/mcp_tool_registry_bridge.py`), which only adds MCP names to roles; `weebot/mcp/server.py`, Weebot's own MCP server.

## If you change this
**Hits:** `tests/unit/tools/test_atomic_mail_tool.py`, `tests/unit/adapters/test_atomicmail_preset_names.py`, `tests/unit/test_executing_inbound_mail_gate.py`, `tests/unit/test_egress_guard.py`, `tests/unit/core/test_trust_boundary.py`, `tests/unit/core/test_trust_boundary_registry.py`, `tests/unit/test_trust_boundary.py`, `tests/unit/security/test_security_gates_fail_closed.py`, `tests/e2e/test_gate_pause_survives_the_seam.py`, `tests/unit/test_apify_actor_tool.py`, `tests/unit/test_apify_service.py`, `tests/unit/fixes/test_outbound_tools_ask.py`, `tests/unit/fixes/test_f06_financial_tools_ask.py`, `tests/unit/interfaces/test_build_tools_configured_mcp.py`, `tests/unit/fixes/test_mcp_toolkit_closed_on_exit.py`, `tests/unit/tools/test_product_tool.py`, `tests/unit/test_regression_tool_name_collision.py`.
**Does not hit:** the shell guards (`BashGuard`) for `atomic_mail`; the role table for `apify_*` and `mcp__*`.

## Surfaces
Every agent role built through `build_tools`; outbound asks reach the user through the approval channel (CLI prompt, web pause; refused in cron and webhooks, `weebot/interfaces/web/routers/webhook.py:144-147`).

## See
`weebot/interfaces/factories.py`
