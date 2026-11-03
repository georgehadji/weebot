---
type: object
name: DelegationGuard
code: DelegationGuard, DelegatedFlow, current_depth, DELEGATION_GUARD
cluster: application
universe: live
status: stub
---

# DelegationGuard

The one choke point a spawned child passes through: depth, per-session count, concurrency and timeout.

## Why this shape
Depth rides a `ContextVar` (the mechanism `approval_scope` uses) so asyncio copies it into child tasks and no spawn path has to pass it down. The bulkhead and counts live on a DI singleton, not a module global. ADR-018 has the reasoning.

## Shape
- `enter(parent_session_id)`: async context manager; raises `DelegationDenied` naming the limit, otherwise yields the child depth (`weebot/application/services/delegation_guard.py`).
- `wrap(flow, parent_session_id)` returns `DelegatedFlow`, whose `run` is inside `enter` and under `child_timeout_s`.
- `current_depth()` reads the variable; the child-tool builders call it to pick the child's depth.

## Connected to
Registered under `DELEGATION_GUARD` (`weebot/application/di/keys.py`, `weebot/application/di/__init__.py`). Used by `SubAgentFactory.spawn` (`weebot/infrastructure/adapters/sub_agent_factory.py`) and `_build_plan_act_flow_for_session` (`weebot/application/di/_agent_tools.py`). Limits come from `DelegationPolicy`. Looks like but is not `ToolExecutor`'s approval scope, which scopes consent, not spawning.

## If you change this
**Hits:** `dispatch_parallel_tasks`, `swarm`, `debate`, `workflow_orchestrator`, `SubAgentFactory`, any flow that reads `current_depth`.
**Does not hit:** `mixture_of_agents` and `hyper_agent` semaphores (still their own), the cost meter.

## Surfaces
Every sub-agent run; a denied spawn shows as a failed child with the limit's name in its error.

## See
`docs/adr/018-delegation-policy.md`
