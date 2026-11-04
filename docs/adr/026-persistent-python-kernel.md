# ADR-026: python_execute keeps a session's variables in a kernel (native backend)

**Date:** 2026-11-04
**Status:** Implemented 2026-11-04 as PR 1 of 5 of plan H17 (`tasks/specs/hermes_v022_parity_implementation_plan.md`), under the user's instruction "proceed". PRs 2 to 5 (tool RPC, Docker socket, WSL2, telemetry and eval) are not built.
**Owner:** weebot maintainers
**Supersedes:** N/A (the plan calls this ADR-020; that number is the spillover ADR)

---

## Context

`python_execute` ran each call in a fresh interpreter through `SandboxPort.execute_python`. A data task that loads a file, then filters it, then plots it had to repeat the load in every call or write intermediate files, and each step cost a model turn.

## Decision

1. **`KernelPort`** (`start`, `exec`, `stop`) with `KernelHandle` and `KernelResult` (`stdout`, `error`, `duration_s`, `timed_out`, `died`).
2. **`kernel_server.py`**, a standard-library script in `infrastructure/sandbox/`: one JSON request per line on stdin, one JSON reply per line on the original stdout, a persistent `globals`. Python-level stdout and stderr are captured in order into `stdout`; the operating-system stdin and stdout are replaced with null devices, so a `print` from a child process or `input()` cannot corrupt the reply. Output is cut at 200 000 characters and says so. `sys.exit` ends the call, not the kernel.
3. **`NativeKernel`**, the backend: the same allowlisted environment as the native sandbox (`build_child_env`: no provider keys), the same proxy blockade when network is off, a memory limit that kills the process (1024 MB; the one-shot run uses 256 MB), and a timeout that kills the process.
4. **`KernelManager`**: one kernel per session, at most four live, least recently used out. Calls to one kernel run one at a time (an `asyncio.Lock` per kernel, in place of the plan's mailbox task; same ordering). A kernel that dies, times out or is evicted is dropped; the next call for that session starts a fresh one and the tool tells the model its variables are gone and why. A kernel that is running a call is never evicted; if all four are busy the call falls back to one-shot.
5. **The tool.** `python_execute` gains `persistent` (default true) and `reset`. A call runs in the kernel only when the manager is wired, the sandbox is the native one, there is a session id, and the call was not cleared for the network. Every other call runs one-shot, as before. `BashGuard` and `ExecApprovalPolicy` still run on every call's code first.
6. **Wiring.** `KernelManager` is a container singleton; `tool_wiring` hands it to `python_execute`; the session-delete cascade calls `stop_session`.

## Consequences

- State persists across calls in a session. Output trust stays `LOCAL`, as `python_execute` was; the tool cannot call other tools yet, so nothing external enters the kernel.
- **No more isolation than before.** The native sandbox is a resource wrapper, not a security boundary, and so is this. Docker and WSL2 sessions keep one-shot execution until PRs 3 and 4.
- **The guard sees each call's code, not the kernel's state.** Code split across two calls is scanned as two pieces.
- The network is decided when a kernel starts. A call that is cleared for the network, and any call with `persistent=false`, runs one-shot, outside the kernel and without its variables.
- The kernel memory limit is four times the one-shot limit, for data work. A kernel killed for memory reports it on the next call.
- The kernel's operating-system stdout is discarded: output from a child process (`os.system`) never reaches the model.
- The manager is shared by every session in the container, which is what bounds the live kernels. A kernel is a host process per session; four idle ones hold memory until evicted or the session is deleted.
- **Not built:** tool RPC and the `weebot_tools` stub, the Docker socket and WSL2 transports, the step-budget refund, telemetry. **Eval-gated, not run:** the data-wrangling suite must show at least 30% fewer model turns at equal pass rate; the suite does not exist yet, so no numbers are attached.
