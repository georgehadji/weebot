---
type: process
name: MCP tool loading
code: config/mcp_servers.json -> MCPClientManager -> MCPToolkitAdapter -> build_tools
cluster: infrastructure
universe: live
status: verified
verified: 2026-10-29
commit: 78bcc65f
consumes:
  - ../objects/core/WeebotSettings.md
  - ../objects/application/DIContainer.md
  - ../objects/tools/IntegrationTools.md
  - ../objects/tools/RoleBasedToolRegistry.md
produces:
  - ../objects/tools/BaseTool.md
---

# MCP tool loading

**Input:** `config/mcp_servers.json` (servers `postiz`, `jira`, `hubspot`, `apify`, each with `${VAR}` references), `WEEBOT_ENABLE_X_MCP=1` and `MCP_SERVERS_CONFIG_PATH` pointing at the file.
**Movement:** DI reads the file and env-expands it per server (an unset variable drops that server only), builds an `MCPClientManager`; `build_tools` connects it once per process through `MCPToolkitAdapter`, appends one `BaseTool` per remote tool, and wraps the list with `guard_tools`.
**Output:** `mcp__<server>__<tool>` tools in the flow's `ToolCollection`, the ones that do not read by name wrapped in `GuardedTool`.

## Steps
1. **Gate and path.** `Container._create_mcp_client` (`weebot/application/di/_factories.py:362`) returns an empty manager unless `WEEBOT_ENABLE_X_MCP` is set to something other than empty, `0` or `false` (`:359-360`), then reads `settings.mcp_servers_config_path` (`:364-368`; field `weebot/config/settings.py:285-288`, default None). The DI key is `"mcp_client"` (`weebot/application/di/__init__.py:405`).
2. **Parse and expand.** The file is parsed as YAML or JSON (`_factories.py:392-398`). Each top-level entry goes through `expand_env` on its own (`:380-385`); it walks every string, including a `_comment` value (`weebot/infrastructure/mcp/config_loader.py:36-55`), and raises `ConfigError` for any `${VAR}` / `$VAR` left unset (`:58-77`). A `ConfigError` logs "MCP server ... not loaded" and skips that entry (`_factories.py:405-408`); any other error is logged and gives an empty manager (`:392-395`). A missing file logs a warning (`:391`).
3. **Manager.** `MCPClientManager(config={"mcpServers": loaded})` (`_factories.py:409`; class `weebot/infrastructure/mcp/mcp_client_manager.py:27-50`). `has_servers` counts dict entries only, so `_comment` strings are skipped (`:52-56`).
4. **Resolve in the interfaces layer.** `_resolve_mcp_client` gets `"mcp_client"` through `_cached` and, when that returned nothing and a shared container exists, asks the container again so the error is logged as "Configured MCP servers not loaded" (`weebot/interfaces/factories.py:88-100`).
5. **Connect once per process.** `_configured_mcp_tools` returns the cached toolkit's tools if one exists; else, under an asyncio lock, builds `MCPToolkitAdapter(manager)` and `initialize()`s it; a connect failure is logged and the flow runs without MCP tools (`factories.py:103-135`). `_mcp_tools_within` runs that in a shared background future and waits at most 8 s: on timeout this run starts without the tools and later runs get them (`:138-159`).
6. **Connect servers.** `MCPClientManager.initialize` skips non-dict and `enabled: false` entries and connects the rest in parallel, one holder task per server (`mcp_client_manager.py:58-103`). Each connects with exponential-backoff retry, 3 attempts (`:105-135`). A server that fails is logged, and `initialize` raises only when every server failed (`:72-79`). Transports: `stdio`, `http`/`sse`, `streamable-http` (`:140-152`); each connection caches `list_tools()` (`:171, 187, 217, 219-226`).
7. **Adapt.** `MCPToolkitAdapter.initialize` turns `get_all_tools()` specs into `MCPToolAdapter` tools (`weebot/infrastructure/mcp/mcp_toolkit_adapter.py:39-56`). Names come from `build_namespaced_name` as `mcp__<server>__<tool>`, descriptions are prefixed `[<server>]` (`mcp_client_manager.py:245-266`; `weebot/core/mcp_naming.py:50-64`).
8. **Join the collection.** `build_tools` (`factories.py:286`) starts from the registry's role collection (`:297-314`). With an explicit `mcp_config` it builds a fresh adapter from that dict (`:316-325`); otherwise it appends `_mcp_tools_within()` (`:326-327`). Extra and Apify preset tools follow (`:329-350`).
9. **Guard.** `guard_tools` from DI wraps the whole list with `include_egress=False`; without it, `RuntimeError` (`factories.py:352-359`). Every `mcp__` tool not named as a read asks (`weebot/application/services/tool_guards.py:267-283, 260-295`); see [tool-call-guard-chain](tool-call-guard-chain.md). The collection is then built with the canonicalizer and contract loader (`factories.py:360-362`).
10. **Call.** `MCPToolAdapter.execute` calls `manager.call_tool` (`mcp_toolkit_adapter.py:24-29`), which maps the public name back to server and tool by building names for the discovered tools, reconnects a dropped server once, and joins the text content (`mcp_client_manager.py:268-315`). Output is fenced as untrusted and taints later egress because `MCPToolAdapter` declares `OutputTrust.EXTERNAL` (`mcp_toolkit_adapter.py:16`); a `GuardedTool` passes that declaration through (`tool_guards.py:434-437`), and `trust_of`, `must_fence` and `must_taint` decide from it, not from the `mcp__` prefix (`weebot/core/trust_boundary.py:58-90`).
11. **Close.** `close_mcp_toolkit` cleans up in the ending task (`factories.py:162-175`), called by the CLI wrapper (`cli/commands/flow.py:70-72`) and the web app shutdown (`weebot/interfaces/web/main.py:384-386`).

Consequences (read from source, not run):
- One unset variable drops only its own server: expansion is per entry (`_factories.py:399-408`). The `_comment` string is expanded too, so a `${VAR}` written in it would drop the comment only.
- The `mcp_config` branch of `build_tools` now expands env as well: `MCPToolkitAdapter.initialize(config)` wraps the dict in `expand_env` (`mcp_toolkit_adapter.py:39-43`), and a `ConfigError` there is not caught in `build_tools` (`factories.py:316-325`). Only `AgentRunner` passes `mcp_config` (`weebot/interfaces/cli/agent_runner.py:58, 93-95`).
- A remote tool error reads as failure: `call_tool` raises when the result's `isError` is set (`mcp_client_manager.py:313-314`) and `MCPToolAdapter` turns the exception into `success=False` (`mcp_toolkit_adapter.py:28-29`).
- The `WEEBOT_ENABLE_X_MCP` flag is read with `os.environ`, not `SecretAccessor` (`_factories.py:378`).

## If you change this
**Hits:** every flow that calls `build_tools` (CLI, web, gateways), MCP tool names that the guard matches on `mcp__`, `tool_scope`'s MCP service words (`weebot/application/services/tool_scope.py:96-101, 114-117`); tests `tests/unit/interfaces/test_build_tools_configured_mcp.py`, `tests/unit/fixes/test_mcp_toolkit_closed_on_exit.py`, `tests/unit/mcp/test_mcp_tool_guards.py`.
**Does not hit:** the MCP *server* Weebot exposes (`weebot/mcp/server.py`, `run_mcp.py`); `cli mcp` beyond the config file it edits; `MCPToolRegistryBridge`, which only adds names to roles (`factories.py:106-107`).

## See
`weebot/application/di/_factories.py`, `weebot/infrastructure/mcp/`, `weebot/interfaces/factories.py`
