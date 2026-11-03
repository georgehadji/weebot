# ADR-018: Delegation is bounded by one policy and one guard

**Date:** 2026-11-03
**Status:** Implemented 2026-11-03 (plan H4, `tasks/specs/hermes_v022_parity_implementation_plan.md`), under the user's instruction "Continue with H4 (delegation policy) and H5 (shadow-git checkpoints)".
**Owner:** weebot maintainers
**Supersedes:** N/A

---

## Context

Nothing capped how deep agents could delegate. Every sub-agent got the full `admin` tool collection (`install_tool`, `ask_human`, `schedule` and every spawn tool included), and `SubAgentSpec.role` and `.tools` never narrowed it. `dispatch_parallel_tasks`, `swarm`, `debate` and `workflow_orchestrator` spawned through `_build_plan_act_flow_for_session`, a second path with no per-child timeout and its own semaphore.

## Decision

1. **A value object holds the limits.** `DelegationPolicy` (`weebot/domain/models/delegation.py`): `max_depth` (default 1), `max_concurrent_children` (4), `max_children_per_session` (20), `child_timeout_s` (300) and `blocked_tools`. Settings come from `WEEBOT_DELEGATION_MAX_DEPTH`, `_MAX_CONCURRENT`, `_MAX_PER_SESSION` and `_CHILD_TIMEOUT_S`; out-of-range values fail at startup.
2. **Tool scoping is a pure function.** `child_tool_names(role_tools, requested, policy, child_depth)` returns (role tools ∩ requested) − blocked. A request can only narrow a role. Below `max_depth` a child keeps the spawn tools; at the limit it loses them.
3. **One guard enforces it.** `DelegationGuard` (`weebot/application/services/delegation_guard.py`) is a DI singleton (`DELEGATION_GUARD`). `enter(parent_session_id)` checks depth, the per-session count and a bulkhead semaphore, then raises the depth in a `ContextVar` for the child's duration. asyncio copies the variable into child tasks, so a grandchild sees depth 2 without anyone passing it. `DelegationDenied` names the limit that was hit.
4. **Both spawn paths go through it.** `SubAgentFactory.spawn` runs the child's events inside `guard.enter` and builds its tools per spec (`tools_for`). `_build_plan_act_flow_for_session` returns the flow wrapped in `DelegatedFlow`, which adds the same guard and an overall `child_timeout_s` deadline. That covers `dispatch_parallel_tasks`, `swarm`, `debate` and `workflow_orchestrator` without editing each tool.

## Consequences

- A child cannot install tools, ask the user, schedule jobs, write persistent memory or start more agents, unless `max_depth` is raised.
- Raising `max_depth` above 1 lets children use the spawn tools down to the limit; the guard still refuses the next level.
- The top-level agent's own tool set (`role="admin"` in `Container.build_mediator`) is unchanged: it is depth 0, not a child.
- `mixture_of_agents` and `hyper_agent` keep their own semaphores for now. At the depth limit they are removed from child tool sets, so a child cannot reach them.
- Per-session counts are held in memory and not purged on session delete (`DelegationGuard.forget` exists; wiring it into the delete cascade is left for H5's purge work).
