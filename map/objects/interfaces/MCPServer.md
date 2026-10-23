---
type: object
name: MCP server
code: WeebotMCPServer, run_mcp.py
cluster: interfaces
universe: live
status: verified
verified: 2026-10-23
commit: 2be1ab8a
---

# MCP server

Weebot exposed as a Model Context Protocol server: a FastMCP instance with shell, Python, search and file tools plus `weebot://` resources. Class `WeebotMCPServer` (`weebot/mcp/server.py:109`), entry point `python run_mcp.py` (`run_mcp.py:70-124`).

## Why this shape
An external client (Claude Desktop over stdio, an IDE over SSE) calls Weebot's tools directly, outside any flow, so the server applies the guard chain itself: `guard_tools([BashTool(), PythonExecuteTool()])` (`server.py:388-392`) and `guard_tools(self._dynamic_tools)` (`:269-276`). No approval channel is set in this process, so the default `DenyApproval` applies (`weebot/application/services/tool_approval.py:172`). Every collaborator is optional so the server starts with whatever the container can build (`run_mcp.py:33-39, 42-67`).

## Shape
- Entry point: `--transport stdio|sse`, `--host` (default `127.0.0.1`), `--port` (8765), `--allow-remote` (`run_mcp.py:71-85`). It requires one provider key (`:88-94`), refuses a non-loopback SSE host without `--allow-remote` (`:97-104`), and `--allow-remote` requires `WEEBOT_MCP_API_KEY` (`:107-117`).
- `_build_server` (`run_mcp.py:42-67`): one `Container()` with `configure_defaults()`; passes state repo, scheduler, event store, reranker and `mcp_composite_tools_enabled`.
- Auth: `api_key` or `WEEBOT_MCP_API_KEY` (`server.py:160`) enables `_APIKeyTokenVerifier` (`:67-97`, constant-time compare, returns `AccessToken`) with `AuthSettings` (`:175-190`). `run_sse` refuses a non-loopback bind without a key (`:215-241`), so the guard holds for callers that skip `run_mcp.py`.
- Tools (`:569-650`): `bash`, `python_execute`, `web_search`, `file_view`, `file_create`, `file_str_replace`, `file_insert`, deprecated `file_editor`, `ping`. Each handler applies `check_rate_limit`, records metrics and pushes to the `ActivityStream` (`:404-554`). Composite tools register first and can hide atomic ones (`:653-667, 669-686`). File tools use one `StrReplaceEditorTool` (`:399`), not wrapped by `guard_tools`.
- Resources (`:690-773`): `weebot://skills`, `activity`, `state`, `schedule`, `products`, `tools`, `costs`, `routing`, built in `weebot/mcp/resources.py`.

Consequences (read from source, not run):
- `run_mcp._build_server` passes no `tool_discovery`, `skill_registry`, `cascade_tracker`, `product_db_path` or `dynamic_tools` (`run_mcp.py:61-67`). From the real entry point `weebot://tools`, `weebot://skills`, `weebot://routing` and `weebot://products` always return their empty stubs (`weebot/mcp/resources.py:120-125, 177-182, 242-246, 302-306`), and no dynamic tool is registered.
- The activity stream is a new empty one per process (`server.py:144`); `weebot://activity` shows only this server's own tool calls.
- `run_mcp.py` loads `.env` with `override=True` at import (`:19-21`) with no pytest guard, unlike `cli/main.py:58-61` and the web main.

## Connected to
- **Uses** the DI container, `BashTool` / `PythonExecuteTool` and the guard chain (`tools/ExecTools.md`, `tools/BaseTool.md`), the event store for `weebot://costs` (`infrastructure/EventStore.md`), the scheduler.
- **Looks like but is not:** the MCP *client* in `weebot/infrastructure/mcp/` (`MCPClientManager`, `MCPToolkitAdapter`), which connects Weebot to other servers. That client is built by `_create_mcp_client` (`weebot/application/di/_factories.py:300-335`), is empty unless `WEEBOT_ENABLE_X_MCP` is on (`:314-315`), and reads `mcp_servers_config_path` (`weebot/config/settings.py:252-255`, default None; the repo ships `config/mcp_servers.json`). Its tools reach flows through `build_tools` (`weebot/interfaces/factories.py:109-141, 388-389`); `python -m cli.main mcp ...` (`cli/commands/mcp.py`) edits that client's list. Also not the tool list in `RoleBasedToolRegistry`, which the server does not use.

## If you change this
**Hits:** MCP clients' tool and resource catalog, tests `tests/unit/interfaces/test_mcp_server.py`, `tests/unit/interfaces/test_run_mcp.py`, `tests/unit/interfaces/test_dynamic_mcp_tools_are_callable.py`, `tests/unit/mcp/test_mcp_auth.py`, `tests/unit/mcp/test_d47_sse_transport_auth.py`, `tests/unit/mcp/test_mcp_tool_guards.py`, `tests/unit/mcp/test_resources.py`, `tests/unit/mcp/test_sanitize.py`, `tests/unit/fixes/test_f13_run_mcp_key_check.py`, `tests/unit/fixes/test_ssot_version.py`, `tests/unit/fixes/test_w42_one_cost_query.py`, `tests/unit/core/test_the_redactor_is_safe_to_wire.py`, `tests/unit/test_acr_p4.py`, `tests/unit/test_mcp_config_loader.py`.
**Does not hit:** flows, the web API, the MCP client config.

## Surfaces
Claude Desktop (stdio), IDE and web MCP clients (SSE on 8765); `examples/04_mcp_server_demo.py` constructs the server directly.

## See
`weebot/mcp/server.py`, `run_mcp.py`
