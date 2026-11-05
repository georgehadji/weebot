# ADR-027: A CONNECT allowlist proxy for network-cleared sandbox calls

**Date:** 2026-11-05
**Status:** Step 1 implemented 2026-11-05 as part of plan H23 (`tasks/specs/hermes_v022_parity_implementation_plan.md`), under the user's instruction "proceed". Step 2 (token swap with TLS interception) is not built. The plan calls this ADR-022; that number is the approval-floors ADR.
**Owner:** weebot maintainers

---

## Context

A sandbox call that `ToolExecutor` clears for the network (a download or install to a known or human-approved host, or egress that passed the egress gate) ran on Docker's default bridge: the whole internet, not the host that was cleared. `--network none` was all or nothing.

## Decision (step 1, decision D8)

1. **`network_cleared_for_call(hosts)`** carries the hosts a call was cleared for (`sandbox_port.network_hosts()`). `ToolExecutor` fills it from `EgressGuard.network_hosts` (every host a shell command names, plus the registry an install implies), else from the egress decision's recipient. `None` still means "any host": a human approved a call whose host could not be read.
2. With `WEEBOT_SANDBOX_EGRESS_PROXY=true`, `DockerLinuxSandbox` runs such a call on `weebot-sandbox-internal`, a Docker `--internal` network with no route out. Its only neighbour is a **sidecar** (`egress_sidecar.EgressSidecar`) that is also on the default bridge. The call gets `HTTP(S)_PROXY=http://<token>:x@egress:3128`.
3. **`egress_proxy.EgressProxy`** (standard library only; the same file is mounted read-only into the sidecar) tunnels `CONNECT host:80|443` only when the call's token allows `host`. It resolves the name itself and refuses a private, loopback, link-local or reserved address, so an allowed name cannot point back inside. It never reads the tunnel. `pypi.org` also allows `files.pythonhosted.org`.
4. The hosts are **pushed per call** over a control port that Docker publishes on host loopback only and that needs a random secret the sandbox never sees (`POST /allow`, `POST /revoke`). The token is revoked when the call ends, on every path.
5. **Fail closed.** If the sidecar or its network cannot start, the call does not run; it never falls back to an open network.
6. The sidecar runs `--read-only`, `--cap-drop ALL`, `no-new-privileges`, uid 1000, 128 MB, 64 pids. Its image is `WEEBOT_SANDBOX_EGRESS_PROXY_IMAGE` or the tool image (it needs only Python).

## Consequences

- Off by default; with it off, nothing changes. Native Windows and WSL2 keep the documented best-effort status.
- A program that ignores proxy variables and opens raw sockets cannot reach anything: the network has no route out. That is the point.
- Only ports 80 and 443; no UDP, no SSH.
- The image is not pinned by digest: the default is the locally built tool image. Pin `WEEBOT_SANDBOX_EGRESS_PROXY_IMAGE` by digest if you use a registry image.
- One sidecar per Weebot process (random name). `DockerLinuxSandbox.close()` removes it, but nothing calls `close()` at exit yet, so it keeps running until stopped (`docker ps --filter label=org.weebot.role=egress-proxy`).
- A call cleared with no host (`None`) still runs on the default bridge. A human approved it.
- Step 2 (the sandbox env holding placeholders, the proxy swapping real keys from H19 on allowlisted hosts) needs a per-session CA in the container trust store. It is only needed if keys must live inside the sandbox; they do not today.
