---
type: object
name: Sandbox (SandboxPort and backends)
code: SandboxPort, SandboxConfig, SandboxFactory, NativeWindowsSandbox, WSL2Sandbox, DockerLinuxSandbox
cluster: infrastructure
universe: live
status: verified
verified: 2026-10-25
commit: 12624041
---

# Sandbox

The place where `bash`, `powershell` and `python_execute` actually run a process. `SandboxPort` is the interface; three backends implement it; `create_default_sandbox()` picks one. Network is off by default and opened per call only for cleared egress; only the Docker backend can enforce that, and only Docker isolates the process from the host.

## Why this shape
One port so tools do not care where code runs (`weebot/application/ports/sandbox_port.py:137-257`). Network is a per-call decision, not a backend setting: `ToolExecutor` runs a call whose egress was cleared inside `network_cleared_for_call()`, a context variable in the port, and backends ask `network_allowed(config)` (`sandbox_port.py:17-36`; W3.9, ADR-013). A capability `NETWORK_ISOLATION` says which backend can actually cut the network (`:58-60`). Mounts, hardening and the opt-in Docker-first mode are ADR-014 (`docs/adr/014-sandbox-workspace-mounts.md`).

## Shape
- Port: `SandboxType` (five members, of which `NATIVE_LINUX` and `KUBERNETES` have no implementation, `:39-46`), `SandboxCapability` (`:49-60`), a frozen `SandboxResult` (`:63-98`), a `SandboxConfig` dataclass (`:101-134`), and an ABC with `execute`, `execute_shell`, `execute_python`, `is_available`, `get_capabilities` (`:137-257`). `SandboxConfig` defaults: 30 s timeout, 64 KB output, no memory limit, `allow_network=False`, no mounts, `workspace_dir=None` (`:118-126`).
- `create_default_sandbox()` (sync, `weebot/infrastructure/sandbox/factory.py:380-427`) is what runs in practice. Config from `build_sandbox_config(settings)`: `sandbox_max_output_bytes`, `sandbox_allow_network` and `workspace_dir=WORKSPACE_ROOT` (`:480-500`). Mode `auto` (default): `NativeWindowsSandbox` on Windows, `DockerLinuxSandbox` elsewhere, with no availability check (`:396-398`). `docker_first`: Docker when it answers and `weebot-tool-env` is built, else the platform default with a warning (`:399-411`). `native` / `docker` / `wsl2` force a backend (`:412-419`). With `sandbox_require_isolation` and network off, a backend without `NETWORK_ISOLATION` is wrapped in `IsolationRequiredSandbox`, which refuses every call (`:420-425, 437-477`); otherwise a one-time warning says network-off is best effort (`:426, 506-517`).
- `NativeWindowsSandbox` (`native_windows.py:120`): runs the process with the host user's rights; its docstring says it is "a resource-limit wrapper, not a security boundary" (`:123-127`). Child environment is a small allowlist so API keys are not inherited (`:30-90`). "Network off" only sets dead proxy variables; raw sockets bypass it (`:54-56, 79-90`). Memory limit is a polling thread; if `psutil` is missing the monitor exits silently (`:100-115`). No `NETWORK_ISOLATION` capability (`:157-164`).
- `WSL2Sandbox` (`wsl2.py:18`): prefixes the command with `wsl` (`:86-92`). `allow_network` is read only to report a capability (`:81-82`); nothing enforces network off.
- `DockerLinuxSandbox` (`docker_linux.py:24`): requires image `weebot-tool-env:latest`, no fallback; `execute` refuses with a build hint when it is missing (`:48-53, 76-99, 264-274`). `docker run --rm -i --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --read-only --user 1000:1000 --tmpfs /tmp`, a pip cache volume (`:162-189`); `workspace_dir` read-only at `/workspace` and its `Output/` read-write (`:190-195`); `-m` when a memory limit is set (`:197-200`); `--network none` unless `network_allowed` (`:202-204`); `-e`, extra `-v` mounts (paths containing `..` skipped, `:206-222`); `-w` maps the host cwd into `/workspace` (`:101-112, 224-227`). Reports `NETWORK_ISOLATION` (`:136-148`). No CPU limit.
- `SandboxFactory` (`factory.py:38`): priority Docker, WSL2, native (`:63-64`); knows Native, WSL2 and (if the import works) Docker (`:68-74`); `create_default(mode)` is async and availability-checked (`:127-191`); `create_fallback_chain` (`:193-208`). `create_default_sandbox()` uses it only for a forced mode (`:419`), not its priority order.
- `ModalSandboxBackend` (`modal_backend.py:41`) is a port implementation outside the factory, referenced only by a test; `osworld.py` is the leftover `weebot/osworld` backend and the one place that defaults to `allow_network=True` (`osworld.py:60`).

Who gets which: DI binds `SandboxPort` to `create_default_sandbox()` (`application/di/_factories.py:105-108`, `di/__init__.py:147`); `BashTool`, `PowerShellTool` and `PythonTool` call it themselves when none is injected (`bash_tool.py:133-135`, `powershell_tool.py:65-67`, `python_tool.py:104-106`). Settings: `sandbox_mode`, `sandbox_require_isolation`, `sandbox_max_output_bytes`, `sandbox_allow_network` (`weebot/config/settings.py:193-202`); `bash_timeout` and `python_timeout` reach the tools through `ToolConfig` (`bash_tool.py:167`, `python_tool.py:121`).

Consequences (read from source, not run):
- Per-call network: `_clear_network_use` asks `EgressGuard.network_use` whether the call reaches the network; a known host (or detect-only mode) is cleared, otherwise the first host asks for approval (`application/agents/executor/_tool_executor.py:80-100`); a cleared call runs inside `network_cleared_for_call()` (`:379-392`). `python_execute` code that imports a network library counts as network use (`weebot/core/egress_guard.py:114-116, 443-445`; see EgressGuard card).
- On native Windows and WSL2 "network off" is not enforced: dead proxy variables, or nothing. Only `SANDBOX_MODE=docker` (or `docker_first` with the image built) or strict mode closes that.
- On Linux in `auto` mode the Docker backend is chosen without checking Docker or the image, so on a host without either every call returns an error result (`docker_linux.py:255-274`).
- The MCP server runs `BashTool()` and `PythonExecuteTool()` outside `ToolExecutor` (`weebot/mcp/server.py:383-392`), so no call there is ever network-cleared; with `SANDBOX_ALLOW_NETWORK` false those tools get network off (best effort on Windows).
- `create_default_sandbox()` is documented as the single source of truth (`factory.py:380-388`) but ignores the Docker-first priority `SandboxFactory` defines; on Windows the native backend is chosen unless a mode is set.

## Connected to
- **Owned by** the DI container and, as a fallback, each of the three shell tools. The MCP server's `BashTool()` / `PythonExecuteTool()` take the same fallback.
- **Opened per call by** `ToolExecutor` (`_tool_executor.py:462-475`) on `EgressGuard.network_use` (EgressGuard card).
- **Related:** `BashTool`, `PowerShellTool`, `PythonTool` (callers); `ExecApprovalPolicy`, `BashGuard`, `CommandSecurityAnalyzer` (gates that run before the sandbox); `ToolConfig` (`weebot/config/tool_config.py`).
- **Looks like but is not:** `EgressGuard` (decides whether to allow an outbound action or clear a call's network; does not stop a process); `BashGuard` (rates text).

## If you change this
**Hits:** all three shell tools, the DI `SandboxPort` binding, the MCP server's two tools, the per-call network clearing in `ToolExecutor`, tests `tests/unit/test_sandbox_config.py`, `tests/unit/tools/test_tool_registry.py:115`, `tests/unit/test_hermes_remaining.py` (Modal), `tests/unit/fixes/test_f29_sandbox_network_default.py`, `tests/unit/infrastructure/sandbox/test_docker_workspace.py`, `tests/unit/infrastructure/sandbox/test_sandbox_network.py`, `tests/unit/infrastructure/sandbox/test_sandbox_selection.py`.
**Does not hit:** guard ratings and approval rules; the browser adapter.

## Surfaces
The output and exit codes the agent sees from shell and Python tools; `SANDBOX_MODE`, `SANDBOX_REQUIRE_ISOLATION`, `SANDBOX_ALLOW_NETWORK` in `.env`.

## See
`weebot/infrastructure/sandbox/factory.py`, `weebot/application/ports/sandbox_port.py`, `docs/adr/014-sandbox-workspace-mounts.md`
