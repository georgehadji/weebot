---
type: object
name: Sandbox (SandboxPort and backends)
code: SandboxPort, SandboxConfig, SandboxFactory, NativeWindowsSandbox, WSL2Sandbox, DockerLinuxSandbox, ModalSandboxBackend
cluster: infrastructure
universe: live
status: verified
verified: 2026-10-31
commit: 85a51bdd
---

# Sandbox

The place where `bash`, `powershell` and `python_execute` actually run a process. `SandboxPort` is the interface; four backends implement it; `create_default_sandbox()` picks one. Network is off by default and opened per call only for cleared egress; only the Docker backend can enforce that, and only Docker isolates the process from the host.

## Why this shape
One port so tools do not care where code runs (`weebot/application/ports/sandbox_port.py:138-258`). Network is a per-call decision, not a backend setting: `ToolExecutor` runs a call whose egress was cleared inside `network_cleared_for_call()`, a context variable in the port, and backends ask `network_allowed(config)` (`sandbox_port.py:17-36`; W3.9, ADR-013). A capability `NETWORK_ISOLATION` says which backend can actually cut the network (`sandbox_port.py:59-61`). Mounts, hardening and the opt-in Docker-first mode are ADR-014 (`docs/adr/014-sandbox-workspace-mounts.md`).

## Shape
- Port: `SandboxType` (six members, of which `NATIVE_LINUX` and `KUBERNETES` have no implementation, `sandbox_port.py:39-47`), `SandboxCapability` (`sandbox_port.py:50-61`), a frozen `SandboxResult` (`sandbox_port.py:64-99`), a `SandboxConfig` dataclass (`sandbox_port.py:102-135`), and an ABC with `execute`, `execute_shell`, `execute_python`, `is_available`, `get_capabilities` (`sandbox_port.py:138-258`). `SandboxConfig` defaults: 30 s timeout, 64 KB output, no memory limit, `allow_network=False`, no mounts, `workspace_dir=None` (`sandbox_port.py:119-127`).
- `create_default_sandbox()` (sync, `weebot/infrastructure/sandbox/factory.py:385-432`) is what runs in practice. Config from `build_sandbox_config(settings)`: `sandbox_max_output_bytes`, `sandbox_allow_network` and `workspace_dir=WORKSPACE_ROOT` (`weebot/infrastructure/sandbox/factory.py:485-499`). Mode `auto` (default): `NativeWindowsSandbox` on Windows, `DockerLinuxSandbox` elsewhere, with no availability check (`weebot/infrastructure/sandbox/factory.py:401-403`). `docker_first`: Docker when it answers and `weebot-tool-env` is built, else the platform default with a warning (`weebot/infrastructure/sandbox/factory.py:404-416`). `native` / `docker` / `wsl2` / `modal` force a backend, again unchecked (`weebot/infrastructure/sandbox/factory.py:417-424`). With `sandbox_require_isolation` and network off, a backend without `NETWORK_ISOLATION` is wrapped in `IsolationRequiredSandbox`, which refuses every call (`weebot/infrastructure/sandbox/factory.py:425-430, 442-482`); otherwise a one-time warning says network-off is best effort (`weebot/infrastructure/sandbox/factory.py:431, 511-522`).
- `NativeWindowsSandbox` (`native_windows.py:128`): runs the process with the host user's rights; its docstring says it is "a resource-limit wrapper, not a security boundary" (`native_windows.py:131-135`). Child environment is a small allowlist so API keys are not inherited (`native_windows.py:29-95`). "Network off" only sets dead proxy variables; raw sockets bypass it (`native_windows.py:58-60, 82-93`). Memory limit is a polling thread; if `psutil` is missing the monitor exits silently (`native_windows.py:103-120`). No `NETWORK_ISOLATION` capability (`native_windows.py:165-186`). On an event loop that cannot spawn subprocesses it runs the command from a worker thread (`native_windows.py:242-248, 290-362`).
- `WSL2Sandbox` (`wsl2.py:19`): prefixes the command with `wsl` (`wsl2.py:87-93`). `allow_network` is read only to report a capability (`wsl2.py:82-83`); nothing enforces network off.
- `DockerLinuxSandbox` (`docker_linux.py:25`): requires image `weebot-tool-env:latest`, no fallback; `execute` refuses with a build hint when it is missing (`docker_linux.py:48-55, 77-100, 265-275`). `docker run --rm -i --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --read-only --user 1000:1000 --tmpfs /tmp`, a pip cache volume (`docker_linux.py:163-190`); `workspace_dir` read-only at `/workspace` and its `Output/` read-write (`docker_linux.py:191-196`); `-m` when a memory limit is set (`docker_linux.py:198-201`); `--network none` unless `network_allowed` (`docker_linux.py:203-205`); `-e`, extra `-v` mounts (paths containing `..` skipped, `docker_linux.py:207-223`); `-w` maps the host cwd into `/workspace` (`docker_linux.py:102-113, 225-228`). Reports `NETWORK_ISOLATION` (`docker_linux.py:137-149`). No CPU limit.
- `SandboxFactory` (`factory.py:39`): priority Docker, WSL2, native (`factory.py:64-65`); knows Native, WSL2, Modal and (if the import works) Docker (`factory.py:69-79`); `create_default(mode)` is async and availability-checked (`factory.py:132-196`); `create_fallback_chain` (`factory.py:198-213`). `create_default_sandbox()` uses it only for a forced mode (`factory.py:424`), not its priority order.
- `ModalSandboxBackend` (`modal_backend.py:51`) runs each call in a remote, billed Modal sandbox; only `SANDBOX_MODE=modal` selects it, and it needs the `modal` package and a token (`modal_backend.py:32-48, 79`, `weebot/infrastructure/sandbox/factory.py:76-79`). It reports `NETWORK_ISOLATION` when `allow_network` is false and passes `block_network=not network_allowed(config)` (`modal_backend.py:81-87, 129`). Written against Modal's API without the package installed; tests use a fake (`tests/unit/fixes/test_d4_modal_sandbox.py`).

Who gets which: DI binds `SandboxPort` to `create_default_sandbox()` (`application/di/_factories.py:127-131`, `di/__init__.py:154`); `BashTool`, `PowerShellTool` and `PythonTool` call it themselves when none is injected (`bash_tool.py:135-137`, `powershell_tool.py:70-72`, `python_tool.py:105-107`). Settings: `sandbox_mode` (the validator also accepts `modal`, `weebot/config/settings.py:269-278`), `sandbox_require_isolation`, `sandbox_max_output_bytes`, `sandbox_allow_network` (`weebot/config/settings.py:203-210`); `bash_timeout` and `python_timeout` reach the tools through `ToolConfig` (`bash_tool.py:169`, `python_tool.py:122`).

Consequences (read from source, not run):
- Per-call network: `_clear_network_use` asks `EgressGuard.network_use` whether the call reaches the network; a known host (or detect-only mode) is cleared, otherwise the first host asks for approval (`application/agents/executor/_tool_executor.py:105-154`); a cleared call runs inside `network_cleared_for_call()` (`application/agents/executor/_tool_executor.py:533-546`). `python_execute` code that imports a network library counts as network use (`weebot/core/egress_guard.py:117-128, 562-568`; see EgressGuard card).
- On native Windows and WSL2 "network off" is not enforced: dead proxy variables, or nothing. Only `SANDBOX_MODE=docker` (or `docker_first` with the image built) or strict mode closes that.
- On Linux in `auto` mode the Docker backend is chosen without checking Docker or the image, so on a host without either every call returns an error result (`docker_linux.py:256-275`).
- The MCP server runs `BashTool()` and `PythonExecuteTool()` outside `ToolExecutor` (`weebot/mcp/server.py:381-391`), so no call there is ever network-cleared; with `SANDBOX_ALLOW_NETWORK` false those tools get network off (best effort on Windows).
- `create_default_sandbox()` is documented as the single source of truth (`factory.py:385-393`) but ignores the Docker-first priority `SandboxFactory` defines; on Windows the native backend is chosen unless a mode is set.

## Connected to
- **Owned by** the DI container and, as a fallback, each of the three shell tools. The MCP server's `BashTool()` / `PythonExecuteTool()` take the same fallback.
- **Opened per call by** `ToolExecutor` (`_tool_executor.py:533-546`) on `EgressGuard.network_use` (EgressGuard card).
- **Related:** `BashTool`, `PowerShellTool`, `PythonTool` (callers); `ExecApprovalPolicy`, `BashGuard`, `CommandSecurityAnalyzer` (gates that run before the sandbox); `ToolConfig` (`weebot/config/tool_config.py`).
- **Looks like but is not:** `EgressGuard` (decides whether to allow an outbound action or clear a call's network; does not stop a process); `BashGuard` (rates text).

## If you change this
**Hits:** all three shell tools, the DI `SandboxPort` binding, the MCP server's two tools, the per-call network clearing in `ToolExecutor`, tests `tests/unit/test_sandbox_config.py`, `tests/unit/tools/test_tool_registry.py:115`, `tests/unit/test_hermes_remaining.py` and `tests/unit/fixes/test_d4_modal_sandbox.py` (Modal), `tests/unit/fixes/test_f29_sandbox_network_default.py`, `tests/unit/infrastructure/sandbox/test_docker_workspace.py`, `tests/unit/infrastructure/sandbox/test_sandbox_network.py`, `tests/unit/infrastructure/sandbox/test_sandbox_selection.py`.
**Does not hit:** guard ratings and approval rules; the browser adapter.

## Surfaces
The output and exit codes the agent sees from shell and Python tools; `SANDBOX_MODE`, `SANDBOX_REQUIRE_ISOLATION`, `SANDBOX_ALLOW_NETWORK` in `.env`.

## See
`weebot/infrastructure/sandbox/factory.py`, `weebot/application/ports/sandbox_port.py`, `docs/adr/014-sandbox-workspace-mounts.md`
