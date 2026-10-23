---
type: process
name: MCP tool loading
code: config/mcp_servers.json -> MCPClientManager -> MCPToolkitAdapter -> build_tools
cluster: infrastructure
universe: live
status: verified
verified: 2026-10-23
commit: c2f39937
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
**Movement:** DI reads and env-expands the file (fail closed on an unset variable), builds an `MCPClientManager`; `build_tools` connects it once per process through `MCPToolkitAdapter`, appends one `BaseTool` per remote tool, and wraps the list with `guard_tools`.
**Output:** `mcp__<server>__<tool>` tools in the flow's `ToolCollection`, outbound ones wrapped in `GuardedTool`.

## Steps
1. **Gate and path.** `Container._create_mcp_client` (`weebot/application/di/_factories.py:300`) returns an empty manager unless `WEEBOT_ENABLE_X_MCP` is set to a true value (`:315-316`), then reads `settings.mcp_servers_config_path` (`:320-323`; field `weebot/config/settings.py:252-255`, default None). The DI key is `"mcp_client"` (`weebot/application/di/__init__.py:344`).
2. **Parse and expand.** The file is parsed as YAML or JSON (`_factories.py:324-336`) and passed through `expand_env` (`:337`), which walks every string, including `_comment` values (`weebot/infrastructure/mcp/config_loader.py:36-55`), and raises `ConfigError` for any `${VAR}` / `$VAR` left unset (`:58-77`). `ConfigError` propagates (`_factories.py:339-340`); any other error is logged and gives an empty manager (`:341-345`).
3. **Manager.** `MCPClientManager(config={"mcpServers": servers})` (`_factories.py:338`; class `weebot/infrastructure/mcp/mcp_client_manager.py:27-46`). `has_servers` counts dict entries only, so `_comment` strings are skipped (`:47-51`).
4. **Resolve in the interfaces layer.** `_resolve_mcp_client` gets `"mcp_client"` through `_cached` and, when that swallowed an error, asks the shared container again so a `ConfigError` is logged as "Configured MCP servers not loaded" (`weebot/interfaces/factories.py:94-106`).
5. **Connect once per process.** `_configured_mcp_tools` returns the cached toolkit's tools if one exists; else, under an asyncio lock, builds `MCPToolkitAdapter(manager)` and `initialize()`s it; a connect failure is logged and the flow runs without MCP tools (`factories.py:109-141`).
6. **Connect servers.** `MCPClientManager.initialize` skips non-dict and `enabled: false` entries, connects each with exponential-backoff retry (3 attempts), logs a server that fails, and raises only when every server failed (`mcp_client_manager.py:53-99`). Transports: `stdio`, `http`/`sse`, `streamable-http` (`:101-114`); each connection caches `list_tools()` (`:175-182`).
7. **Adapt.** `MCPToolkitAdapter.initialize` turns `get_all_tools()` specs into `MCPToolAdapter` tools (`weebot/infrastructure/mcp/mcp_toolkit_adapter.py:35-50`). Names come from `build_namespaced_name` as `mcp__<server>__<tool>`, descriptions are prefixed `[<server>]` (`mcp_client_manager.py:200-221`; `weebot/core/mcp_naming.py:50-64`).
8. **Join the collection.** `build_tools` (`factories.py:360`) starts from the registry's role collection (`:377-394`). With an explicit `mcp_config` it builds a fresh adapter from that dict (`:396-405`); otherwise it appends `_configured_mcp_tools()` (`:406-407`). Extra and Apify preset tools follow (`:409-430`).
9. **Guard.** `guard_tools` from DI wraps the whole list with `include_egress=False`; without it, `RuntimeError` (`factories.py:432-439`). Every `mcp__` tool not named as a read asks (`weebot/application/services/tool_guards.py:241-257, 275-295`); see [tool-call-guard-chain](tool-call-guard-chain.md).
10. **Call.** `MCPToolAdapter.execute` calls `manager.call_tool`, which maps the public name back to server and tool by rebuilding names, reconnects a dropped server once, and joins the text content (`mcp_toolkit_adapter.py:20-25`; `mcp_client_manager.py:223-267`). Output of every `mcp__` tool is fenced as untrusted and taints later egress (`weebot/core/trust_boundary.py:141-167`).
11. **Close.** `close_mcp_toolkit` cleans up in the ending task (`factories.py:144-157`), called by the CLI wrapper (`cli/commands/flow.py:71-73`).

Consequences (read from source, not run):
- One unset variable for one server stops every server: `expand_env` covers the whole file before any server is built (`_factories.py:337`), and the `ConfigError` turns into no manager (`factories.py:100-105`).
- The `mcp_config` branch of `build_tools` skips `expand_env`: `MCPToolkitAdapter.initialize(config)` builds `MCPClientManager(config)` from the raw dict (`mcp_toolkit_adapter.py:36-37`). Only `Container.build_agent_runner` passes `mcp_config` (`weebot/application/di/__init__.py:419`).
- A remote tool error reads as success: `call_tool` never checks the MCP result's error flag and `MCPToolAdapter` returns `success=True` (`mcp_client_manager.py:255-267`; `mcp_toolkit_adapter.py:22-23`).
- A missing config file gives an empty manager with no log line (`_factories.py:330, 345`).
- The `WEEBOT_ENABLE_X_MCP` flag is read with `os.environ`, not `SecretAccessor` (`_factories.py:315`).

## If you change this
**Hits:** every flow that calls `build_tools` (CLI, web, gateways), MCP tool names that the guard and trust fence match on `mcp__`, `tool_scope`'s MCP service words (`weebot/application/services/tool_scope.py:96-101, 114-117`); tests `tests/unit/interfaces/test_build_tools_configured_mcp.py`, `tests/unit/fixes/test_mcp_toolkit_closed_on_exit.py`, `tests/unit/mcp/test_mcp_tool_guards.py`.
**Does not hit:** the MCP *server* Weebot exposes (`weebot/mcp/server.py`, `run_mcp.py`); `cli mcp` beyond the config file it edits; `MCPToolRegistryBridge`, which only adds names to roles (`factories.py:112-113`).

## See
`weebot/application/di/_factories.py`, `weebot/infrastructure/mcp/`, `weebot/interfaces/factories.py`
