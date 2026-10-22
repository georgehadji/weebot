---
type: object
name: Sandbox (SandboxPort and backends)
code: SandboxPort, SandboxConfig, SandboxFactory, NativeWindowsSandbox, WSL2Sandbox, DockerLinuxSandbox
cluster: infrastructure
universe: live
status: verified
verified: 2026-10-21
commit: f00ea38
---

# Sandbox

The place where `bash`, `powershell` and `python_execute` actually run a process. `SandboxPort` is the interface; three backends implement it; a factory picks one. Only the Docker backend can isolate the process from the host, and no production code configures it to.

## Why this shape
One port so tools do not care where code runs (`weebot/application/ports/sandbox_port.py:107-227`). A factory with a priority order (Docker, then WSL2, then native) so the most isolated backend wins when it exists (`weebot/infrastructure/sandbox/factory.py:63-64`). The mode can be forced with `WeebotSettings.sandbox_mode` (`factory.py:19-24, 380-405`).

**Changed 2026-10-22 (plan W3.9). The rest of this card describes `f00ea38`.**
- `create_default_sandbox()` builds its config from settings (`build_sandbox_config`), and network is off by default.
- A call gets network only inside `network_cleared_for_call()`, which `ToolExecutor` sets for cleared egress or network use. Backends read `network_allowed(config)`.
- Docker reports `NETWORK_ISOLATION` and runs with `--cap-drop ALL`, `no-new-privileges` and `--pids-limit 256`.
- Factory priority, workspace mounts, `--read-only` and `--user` are unchanged.

**Changed again 2026-10-22 (ADR-014, `docs/adr/014-sandbox-workspace-mounts.md`).** This supersedes the W3.9 note above on these points:
- **Mounts:** Docker mounts `workspace_dir` read-only at `/workspace` and `Output/` read-write.
- **Hardening:** it runs `--read-only --user 1000:1000` with a `/tmp` tmpfs.
- **Image:** it requires `weebot-tool-env`, with no fallback.
- **Selection:** `SANDBOX_MODE=docker_first` is an opt-in Docker-first choice; `auto` is as described below.
- **Strict mode:** `SANDBOX_REQUIRE_ISOLATION=true` refuses calls on backends without `NETWORK_ISOLATION`.

## Shape
- Port: `SandboxType` (five members, of which `NATIVE_LINUX` and `KUBERNETES` have no implementation), `SandboxCapability`, a frozen `SandboxResult`, a `SandboxConfig` dataclass, and an ABC with `execute`, `execute_shell`, `execute_python`, `is_available`, `get_capabilities` (`sandbox_port.py:15-227`). `SandboxConfig` defaults: 30 s timeout, 64 KB output, **no memory limit, `allow_network=True`, no mounts** (`:89-96`).
- `NativeWindowsSandbox` (`native_windows.py:118`): runs the process with the host user's rights. Its own docstring says it is "a resource-limit wrapper, not a security boundary" (`:121-125`). Child environment is a small allowlist so API keys are not inherited (`:29-90`). "Network off" only sets dead proxy variables; raw sockets bypass it (`:54-56, 78-88`). Memory limit is a polling thread; if `psutil` is missing the monitor exits silently (`:98-115`).
- `WSL2Sandbox` (`wsl2.py:18`): prefixes the command with `wsl` (`:86-92`). `allow_network` is read only to report a capability (`:81`); nothing enforces it.
- `DockerLinuxSandbox` (`docker_linux.py:23`): `docker run --rm -i`, plus `-m` when a memory limit is set, `--network none` when `allow_network` is false, `-e`, `-v` mounts (paths containing `..` are skipped), `-w`, image `weebot-tool-env:latest` else `python:3.11-slim` (`:47-48, 129-183`). No `--read-only`, `--cap-drop`, `--user`, CPU or pid limit.
- `ModalSandboxBackend` (`modal_backend.py:41`) is a port implementation outside the factory, referenced only by a test; `osworld.py` is the leftover `weebot/osworld` backend.
- `SandboxFactory` (`factory.py:38`): knows Native, WSL2 and (if the import works) Docker (`:68-74`); `create_default(mode)` is async and availability-checked (`:127-191`); `create_fallback_chain` (`:193-208`).
- `create_default_sandbox()` (sync, `factory.py:380-405`) is what runs in practice: forced mode if set, else `NativeWindowsSandbox` on Windows and `DockerLinuxSandbox` elsewhere, **without** an availability check or the factory's priority order.

Who gets which: DI binds `SandboxPort` to `create_default_sandbox()` (`application/di/_factories.py:106-108`, `di/__init__.py:137`); `BashTool`, `PowerShellTool` and `PythonTool` call it themselves when none is injected (`bash_tool.py:128-130`, `powershell_tool.py:59-61`, `python_tool.py:98-100`).

Consequences (read from source, not run):
- No production code builds a `SandboxConfig` with arguments (grep `SandboxConfig(`: only a docstring example and `osworld.py`). Every sandbox DI or the tools create therefore runs with the defaults: **network allowed, no memory limit, no mounts**.
- `WeebotSettings.sandbox_allow_network` (default false) and `sandbox_max_output_bytes` have no reader in `weebot/` (grep, 2026-10-21); only `bash_timeout` and `python_timeout` reach the tools, through `ToolConfig` (`bash_tool.py:162`, `python_tool.py:115`). The settings that read as network containment do nothing.
- So Python or shell code the agent runs can open network connections on every backend. `EgressGuard` does not classify `python_execute` (see its card), so nothing else covers it. This settles the sandbox half of plan item F09: the sandbox does not contain it.
- On Linux the default Docker sandbox has no bind mounts, so code runs in a bare container that cannot see the workspace and discards its files on exit (`--rm`). Not run; no workspace paths are ever passed.
- `create_default_sandbox()` is documented as the single source of truth (`factory.py:380-388`) but ignores the Docker-first priority the class defines; on Windows the native backend is always chosen unless a mode is forced.

## Connected to
- **Owned by** the DI container and, as a fallback, each of the three shell tools. The MCP server builds `BashTool()` and `PythonExecuteTool()` with no sandbox (`weebot/mcp/server.py:380-381`), so it gets the same defaults.
- **Related:** `BashTool`, `PowerShellTool`, `PythonTool` (callers); `ExecApprovalPolicy`, `BashGuard`, `CommandSecurityAnalyzer` (gates that run before the sandbox); `ToolConfig` (`weebot/config/tool_config.py`).
- **Looks like but is not:** `EgressGuard` (decides whether to allow an outbound action; does not stop a process); `BashGuard` (rates text).

## If you change this
**Hits:** all three shell tools, the DI `SandboxPort` binding, the MCP server's two tools, tests `tests/unit/test_sandbox_config.py`, `tests/unit/tools/test_tool_registry.py:114`, `tests/unit/test_hermes_remaining.py` (Modal).
**Does not hit:** guard ratings and approval rules; the browser adapter.

## Surfaces
The output and exit codes the agent sees from shell and Python tools; `SANDBOX_MODE` in `.env`.

## See
`weebot/infrastructure/sandbox/factory.py`, `weebot/application/ports/sandbox_port.py`
