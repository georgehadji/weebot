"""Delegation policy: how deep, how wide and how long an agent may delegate (H4).

A frozen value object plus two pure functions. The guard that enforces it at run time is
``application.services.delegation_guard``; this module has no I/O.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

from pydantic import BaseModel, ConfigDict, Field

# Tools that start more agents. A child at the depth limit must not have them.
SPAWN_TOOLS: frozenset[str] = frozenset(
    {
        "dispatch_parallel_tasks",
        "swarm",
        "debate",
        "mixture_of_agents",
        "workflow_orchestrator",
        "hyper_agent",
    }
)

# Tools a child never gets: they act on the user or the host, not on the child's task.
_NEVER_FOR_CHILDREN: frozenset[str] = frozenset(
    {"ask_human", "schedule", "install_tool", "persistent_memory"}
)


class DelegationDenied(Exception):
    """A delegation was refused by policy. The message names the limit that was hit."""


class DelegationPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_depth: int = Field(default=1, ge=1, le=3)
    max_concurrent_children: int = Field(default=4, ge=1, le=16)
    max_children_per_session: int = Field(default=20, ge=1, le=200)
    child_timeout_s: int = Field(default=300, ge=10, le=3600)
    blocked_tools: frozenset[str] = SPAWN_TOOLS | _NEVER_FOR_CHILDREN

    @classmethod
    def from_mapping(cls, env: Mapping[str, str | None]) -> DelegationPolicy:
        """Read ``WEEBOT_DELEGATION_*`` settings; a missing or empty value keeps the default."""
        fields = {
            "max_depth": "WEEBOT_DELEGATION_MAX_DEPTH",
            "max_concurrent_children": "WEEBOT_DELEGATION_MAX_CONCURRENT",
            "max_children_per_session": "WEEBOT_DELEGATION_MAX_PER_SESSION",
            "child_timeout_s": "WEEBOT_DELEGATION_CHILD_TIMEOUT_S",
        }
        return cls(**{f: int(v) for f, key in fields.items() if (v := env.get(key))})

    def blocked_at(self, child_depth: int) -> frozenset[str]:
        """Tools a child at *child_depth* may not use. Below the limit it may still delegate."""
        if child_depth < self.max_depth:
            return self.blocked_tools - SPAWN_TOOLS
        return self.blocked_tools | SPAWN_TOOLS


def child_tool_names(
    role_tools: Collection[str],
    requested: Collection[str],
    policy: DelegationPolicy,
    child_depth: int,
) -> list[str]:
    """(role tools ∩ requested, when given) − blocked, in the role's order."""
    blocked = policy.blocked_at(child_depth)
    return [t for t in role_tools if (not requested or t in requested) and t not in blocked]
