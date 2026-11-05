# ADR-026: python_execute keeps a session's variables in a kernel (native backend)

**Date:** 2026-11-04
**Status:** PR 1 of 5 of plan H17 (`tasks/specs/hermes_v022_parity_implementation_plan.md`) implemented 2026-11-04; PR 2 (tool RPC, native backend) implemented 2026-11-04, both under the user's instruction "proceed". PRs 3 to 5 (Docker socket, WSL2, telemetry and eval) are not built.
**Owner:** weebot maintainers
**Supersedes:** N/A (the plan calls this ADR-020; that number is the spillover ADR)

---

## Context

`python_execute` ran each call in a fresh interpreter through `SandboxPort.execute_python`. A data task that loads a file, then filters it, then plots it had to repeat the load in every call or write intermediate files, and each step cost a model turn.

## Decision

1. **`KernelPort`** (`start`, `exec`, `stop`) with `KernelHandle` and `KernelResult` (`stdout`, `error`, `duration_s`, `timed_out`, `died`).
2. **`kernel_server.py`**, a standard-library script in `infrastructure/sandbox/`: one JSON request per line on stdin, one JSON reply per line on the original stdout, a persistent `globals`. Python-level stdout and stderr are captured in order into `stdout`; the operating-system stdin and stdout are replaced with null devices, so a `print` from a child process or `input()` cannot corrupt the reply. Output is cut at 200 000 characters and says so. `sys.exit` ends the call, not the kernel.
3. **`NativeKernel`**, the backend: the same allowlisted environment as the native sandbox (`build_child_env`: no provider keys), the same proxy blockade when network is off, a memory limit that kills the process (1024 MB; the one-shot run uses 256 MB), and a timeout that kills the process.
4. **`KernelManager`**: one kernel per session, at most four live, least recently used out. Calls to one kernel run one at a time (an `asyncio.Lock` per kernel, in place of the plan's mailbox task; same ordering). A kernel that dies, times out, is cancelled or is evicted is dropped; the next call for that session starts a fresh one and the tool tells the model its variables are gone and why. A call whose kernel was already gone before the code reached it (for example killed for memory between calls) is run again on a fresh kernel. A kernel with a call running or waiting is never evicted; if all four are busy the call falls back to one-shot. The slot table is changed only by code that does not await, so there is no manager-wide lock: a kernel is started and stopped outside any shared lock, and a slow start for one session does not hold up another. The per-slot locks are renewed when the manager is used from a different event loop.
5. **The tool.** `python_execute` gains `persistent` (default true) and `reset`. A call runs in the kernel only when the manager is wired, the sandbox is the native one, there is a session id, and the call was not cleared for the network. Every other call runs one-shot, as before. `BashGuard` and `ExecApprovalPolicy` still run on every call's code first.
6. **Wiring.** `KernelManager` is a container singleton; `tool_wiring` hands it to `python_execute`; the session-delete cascade calls `stop_session`.

7. **Tool RPC (PR 2).** Code in a kernel can call tools through `import weebot_tools` (`bash`, `web_search`, `file_view`, `file_write`, `call_tool(name, **args)`; a failure raises `ToolError`). A call is a JSON-RPC 2.0 request on the kernel's own pipes: `kernel_server.py` writes `{"rpc": ...}` where it writes its reply, and the host answers with one `{"rpc_result": ...}` line on stdin. `NativeKernel.exec` answers each through the `on_rpc` handler it is given, and the time that takes is added to the code's deadline. `ToolRpcServer.handle` checks the allowlist (`WEEBOT_KERNEL_RPC_TOOLS`, default `bash,file_editor,web_search`; `python_execute` and `dispatch_parallel_tasks` are never allowed; empty turns it off), caps a run at 24 calls, and dispatches through `ToolExecutor.execute_tool`. `ToolExecutor` opens `tool_rpc_scope(self.execute_tool)` around a `python_execute` call, and `PythonExecuteTool` builds the server from it, so a call made by code meets the guard chain, the approval floors (H18), the egress gate, D5 taint and the effect ledger as a model call does. External output from such a call taints the session through that same path.

## Consequences

- State persists across calls in a session. Output trust stays `LOCAL`, as `python_execute` was; the tool cannot call other tools yet, so nothing external enters the kernel.
- **No more isolation than before.** The native sandbox is a resource wrapper, not a security boundary, and so is this. Docker and WSL2 sessions keep one-shot execution until PRs 3 and 4.
- **The guard sees each call's code, not the kernel's state.** Code split across two calls is scanned as two pieces.
- The network is decided when a kernel starts. A call that is cleared for the network, and any call with `persistent=false`, runs one-shot, outside the kernel and without its variables.
- The kernel memory limit is four times the one-shot limit, for data work. A kernel killed for memory reports it on the next call.
- The kernel's operating-system stdout is discarded: output from a child process (`os.system`) never reaches the model.
- The manager is shared by every session in the container, which is what bounds the live kernels. A kernel is a host process per session; four idle ones hold memory until evicted or the session is deleted.
- **A tool call from code that would ask a person is an error for the code, not a pause**: the code gets `ToolError("This call needs approval; make it as a tool call, not from code.")`, and the model can make the call itself. A floor's `human` verdict behaves the same, a `deny` verdict is refused.
- **Deviations from the plan.** The plan puts the native RPC on loopback TCP with a per-session token; the pipes the kernel already has carry it instead, so no port is open and no token exists to leak or guess (the "wrong token" test does not apply). The plan also has each RPC call count against the step's tool-call cap and the `exec` refund its loop iteration; the cap here is 24 calls per run, and the step budget is untouched. The whole `python_execute` run is bounded at 305 s, whatever its tools take, in place of the tool's usual timeout plus five seconds.
- **Not built:** the step-budget refund, the Docker socket and WSL2 transports, telemetry. **Eval-gated, not run:** the data-wrangling suite must show at least 30% fewer model turns at equal pass rate; the suite does not exist yet, so no numbers are attached.
