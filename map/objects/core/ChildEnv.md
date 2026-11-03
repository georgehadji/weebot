---
type: object
name: ChildEnv
code: build_child_env, BASE_POSIX, BASE_WINDOWS
cluster: core
universe: live
status: stub
---

# ChildEnv

The environment a child process (MCP stdio server, sandbox command) is started with: an allowlist of the parent environment plus the caller's declared variables.

## Why this shape
`{**parent_env, **declared}` handed every provider key to every MCP server, and an empty merge passed as `env=None` made the WSL2 and native sandboxes inherit everything. A pure function over a `source` mapping is tested without the real environment and never returns `None` (`weebot/core/child_env.py:28`). Declared values win; names match case-insensitively on win32 so `Path` and `APPDATA` survive (`weebot/core/child_env.py:14-25`).

## Shape
- `build_child_env(source, *, declared, passthrough, inherit_proxy, platform)` returns a new dict (`weebot/core/child_env.py:28`).
- `source` comes from `SecretAccessor.environ_view()` (`weebot/config/secret_accessor.py:131`), a read-only copy, so no new bare environment read appears.
- An MCP server opts a secret in with `env_passthrough` in its config, or declares it in `env` (`weebot/infrastructure/mcp/mcp_client_manager.py:164`).

## Connected to
Used by the MCP stdio client, `NativeWindowsSandbox._build_child_env` (`weebot/infrastructure/sandbox/native_windows.py:51`) and the WSL2 sandbox (`weebot/infrastructure/sandbox/wsl2.py:141`). Looks like but is not `SecretAccessor`, which reads single named values.

## If you change this
**Hits:** every MCP stdio server and sandbox child. A server that relied on an inherited variable stops seeing it until it is declared or passed through.
**Does not hit:** HTTP/SSE MCP transports, the Docker sandbox, or the bash tool's own environment handling.

## Surfaces
MCP server config (`env`, `env_passthrough`); sandbox `env_vars`.

## See
`weebot/core/child_env.py`
