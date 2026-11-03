---
type: object
name: Delegation
code: DelegationPolicy, child_tool_names, DelegationDenied, SPAWN_TOOLS
cluster: domain
universe: live
status: stub
---

# Delegation

The limits on how an agent may start other agents, and the pure rule for which tools a child gets.

## Why this shape
Limits are a frozen value object and tool scoping is a function, so the rule is testable without an event loop; enforcement lives in the guard (`weebot/application/services/delegation_guard.py`). ADR-018 has the reasoning.

## Shape
- `DelegationPolicy`: `max_depth`, `max_concurrent_children`, `max_children_per_session`, `child_timeout_s`, `blocked_tools`; `from_mapping` reads `WEEBOT_DELEGATION_*` (`weebot/domain/models/delegation.py`).
- `child_tool_names(role_tools, requested, policy, child_depth)`: (role ∩ requested) − blocked. `blocked_at(depth)` keeps the spawn tools below the limit and removes them at it.

## Connected to
Read by `DelegationGuard` and by the two child-tool builders: `Container._create_sub_agent_factory` (`weebot/application/di/__init__.py`) and `_build_plan_act_flow_for_session` (`weebot/application/di/_agent_tools.py`). Role names come from `RoleBasedToolRegistry.DEFAULT_ROLE_MAPPINGS` (`weebot/application/services/tool_registry.py`). Looks like but is not `SubAgentSpec` (`weebot/domain/models/sub_agent.py`), which describes one child, not the limits.

## If you change this
**Hits:** every child's tool set, the `blocked_tools` default, `.env` documentation for `WEEBOT_DELEGATION_*`.
**Does not hit:** the top-level agent's tools, tool approval, the cascade.

## Surfaces
Every sub-agent spawn: `dispatch_parallel_tasks`, `swarm`, `debate`, `workflow_orchestrator`, `SubAgentFactory`.

## See
`docs/adr/018-delegation-policy.md`
