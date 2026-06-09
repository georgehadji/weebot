---
name: process-manager
description: "Use when managing system processes. Trigger: process, kill, restart, zombie, resource hog, service status."
license: MIT
---
# Process Manager

## When to use
Inspect, manage, or troubleshoot running processes.

## Workflow
1. **List processes** — by CPU, memory, or name filter.
2. **Identify issues** — zombie processes, high resource consumers, orphaned processes.
3. **Act** — kill, restart, or adjust priority as requested.
4. **Verify** — confirm the action succeeded.

## Safety
- Never kill system-critical processes without confirmation
- Use SIGTERM before SIGKILL

## Output
Process report with actions taken.