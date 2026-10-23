# ADR-014: What the Docker sandbox can see and write

**Date:** 2026-10-22
**Status:** Approved 2026-10-22 with the proposed answers (user: "workspace read-only, Output/ read-write, SANDBOX_MODE=auto opt-in, strict mode off by default, require weebot-tool-env image"). Implemented 2026-10-22 (unit-tested; no live container run, because Docker Desktop was not running).

**Changes from the draft, made while implementing:**
- **New mode value:** `SANDBOX_MODE=auto` already existed as the default, meaning "native on Windows, Docker elsewhere". The opt-in Docker-first mode is therefore `SANDBOX_MODE=docker_first` (user: "Use SANDBOX_MODE=docker_first for Docker-first and keep auto unchanged"), and `auto` is unchanged.
- **Container user:** the image's existing user `weebot` (pinned to uid 1000), not a new `sandbox` user. The pip cache mounts at `/home/weebot/.cache/pip`.
- **pip installs:** they go to `/tmp/.local` (`PIP_USER=1`, `PYTHONUSERBASE`), because the root filesystem and home are read-only.
**Owner:** weebot maintainers
**Supersedes:** N/A

---

## Context

This ADR concerns `DockerLinuxSandbox` (`weebot/infrastructure/sandbox/docker_linux.py`). It is the only backend that really isolates code, because only Docker enforces network-off (`--network none`).

**What it does today**, from code read on 2026-10-22:
- It runs `docker run --rm -i --cap-drop ALL --security-opt no-new-privileges --pids-limit 256`, adds `--network none` unless the call is cleared (W3.9), adds `-m` when a memory limit is set, and adds `-e` for each environment variable.
- It mounts every `SandboxConfig.read_only_paths` and `read_write_paths` entry at the same path inside the container. Paths containing `..` are skipped.
- No production code fills those lists. So code runs in a bare container: it cannot see the workspace, and whatever it writes is discarded on exit (`--rm`).
- `--read-only` and `--user` are not set. With no mount, `pip install` and every file write need a writable root filesystem, and code runs as root inside the container.

**Factory choice:**
- `create_default_sandbox()` picks `NativeWindowsSandbox` on Windows and Docker elsewhere, with no availability check, unless `SANDBOX_MODE` forces a backend.
- The native backend runs code as the host user, with the user's own rights over the whole disk.
- Switching to Docker as things stand would break every task that reads or writes project files.

**So the plan's hardening items wait on one decision:** what does sandboxed code see and write? Those items are W3.9 "not done", F30 and F31: `--read-only`, `--user`, Docker-first selection, and a strict isolation mode.

## Decision (proposed)

1. **Layout inside the container:**

   | Path | Mount | Why |
   |---|---|---|
   | `/workspace` | the session's working directory, **read-only** | code reads project files but cannot change them behind the human's back |
   | `/workspace/Output` | host `Output/`, **read-write** | the one place results land, which is already the project's output convention |
   | `/tmp` | `tmpfs`, 256 MB | scratch space |
   | `/home/sandbox/.cache/pip` | named volume `weebot-pip-cache` | `pip install` works without a writable root filesystem and is fast the second time |
   | everything else | `--read-only` root filesystem | |

2. **User:** `--user 1000:1000`, and the image `weebot-tool-env` gets a `sandbox` user with that uid. On Linux hosts, the host uid if it is not 0.
3. **Paths:** tools pass `cwd=/workspace` (or a subdirectory) and the backend translates the host working directory to `/workspace`. Commands that contain host paths (`C:\...`) fail inside the container. That limit is shared with WSL2 and is documented, not emulated.
4. **Factory:** `SANDBOX_MODE=auto` (new) tries Docker first, if `docker info` succeeds and the image exists, then falls back to the native backend with the existing best-effort warning. Unset keeps today's behaviour. That fixes F31 without changing what anyone runs today.
5. **Strict mode:** `SANDBOX_REQUIRE_ISOLATION=true` refuses to run a sandboxed call on a backend without `NETWORK_ISOLATION`, instead of warning. The default is false.

## Consequences

- Code can no longer edit project files directly. Edits go through `file_editor`, which is the reviewed path.
- **Breaking:** a task that today runs `python script.py` writing next to itself would have to write to `Output/`. This is the main cost.
- Installs persist across calls only in the pip cache volume. A package must be installed in the same call that uses it, or the image must ship it.
- Docker Desktop on Windows mounts `C:\` paths through its file-sharing layer. That works, but I/O is slower than native.

## Open questions for review

1. Should `/workspace` be read-only (proposed), or read-write with the same review as `file_editor`?
2. Which directories, besides `Output/`, need write access? Logs, the session database and memory files must not be writable from the sandbox.
3. Should `SANDBOX_MODE=auto` become the default on Windows once Docker is installed (it is on this machine), or stay opt-in?
4. Should strict mode default to true in web and gateway processes, which serve remote users, and false in the CLI?
5. Image: keep `python:3.11-slim` as the fallback, or require a built `weebot-tool-env` image so the `sandbox` user exists?

## Not covered

- Kubernetes and Modal backends.
- The MCP server path: it runs tools without `ToolExecutor` and needs `SANDBOX_ALLOW_NETWORK=true` for network (`docs/SECURITY_MODEL.md`).
