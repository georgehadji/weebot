---
type: object
name: PythonKernel
code: KernelPort, KernelManager, NativeKernel, kernel_server
cluster: application
universe: live
status: stub
---

# PythonKernel

A Python interpreter per session that keeps its variables between `python_execute` calls.

## Why this shape
Each call used to start a fresh interpreter, so a multi-step data task repeated its setup or wrote files between steps. ADR-026 has the reasoning and the five-PR plan; only the native backend exists.

## Shape
- `KernelPort`: `start(session_id)`, `exec(handle, code, timeout)`, `stop(handle)`; `KernelResult` carries `stdout`, `error`, `timed_out`, `died` (`weebot/application/ports/kernel_port.py`).
- `KernelManager.run(session_id, code, timeout, reset=)`: one kernel per session, four at most, least recently used out, one call at a time per kernel; `stop_session`, `stop_all` (`weebot/application/services/kernel_manager.py`).
- `NativeKernel`: a child process with the native sandbox's environment allowlist, proxy blockade and a memory kill (`weebot/infrastructure/sandbox/native_kernel.py`), running `kernel_server.py`, a standard-library REPL speaking JSON lines (`weebot/infrastructure/sandbox/kernel_server.py`).

## Connected to
Used by `PythonExecuteTool` (`weebot/tools/python_tool.py`), only on the native sandbox, with a session id and no network clearance for the call; any other call runs one-shot through `SandboxPort.execute_python`. Bound in `weebot/application/di/_capabilities.py`, passed by `Container.tool_wiring` and `RoleBasedToolRegistry`, and stopped by the session-delete cascade (`_session_stores` in `weebot/interfaces/web/dependencies.py`). Not the same as `SandboxPort`, which runs one command and returns.

## If you change this
**Hits:** the `python_execute` schema (`persistent`, `reset`) and so `tasks/quality/prompt_surface/`, memory held by idle kernels, what the model is told when its variables are lost.
**Does not hit:** `bash` and `powershell` (one-shot), the BashGuard and approval checks (they run before the kernel).

## Surfaces
The `python_execute` tool.

## See
`docs/adr/026-persistent-python-kernel.md`
