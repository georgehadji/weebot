---
name: network-diagnostics
description: "Use when diagnosing network connectivity issues. Trigger: network, ping, traceroute, DNS, connectivity, latency, packet loss."
license: MIT
---
# Network Diagnostics

## When to use
Diagnose network connectivity problems — latency, DNS resolution, routing.

## Workflow
1. **Ping** — measure latency and packet loss to target hosts.
2. **DNS** — check resolution, propagation, record types (A, AAAA, MX, CNAME).
3. **Traceroute** — map network path to target.
4. **Port check** — verify specific ports are open and listening.
5. **Report** — summary of findings with affected hosts and recommended fixes.

## Output
A diagnostic report with latency, DNS status, and connectivity issues.