---
name: server-health-check
description: "Use when checking system health, resource usage, or server status. Trigger: health check, system status, resource usage, CPU, memory, disk space, uptime, running services."
license: MIT
---
# Server Health Check

## When to use
Check the health and resource usage of the current system or a remote server.

## Workflow
1. **CPU** — load average, core count, top processes by CPU.
2. **Memory** — total, used, free, swap usage.
3. **Disk** — usage per mount, inode usage, largest directories.
4. **Network** — active connections, listening ports, interface stats.
5. **Services** — critical service status (ssh, nginx, docker, cron).
6. **Uptime** — system uptime, last boot time.
7. **Report** — summary with warnings for any metric exceeding 80% usage.

## Output
A health report with per-metric status, warnings, and recommendations.