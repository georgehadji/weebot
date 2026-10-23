"""StepExecutionContext — the flow's executor settings for one step (ADR-015).

The executor that runs a step is built by the container's factory from
singletons. This carries what only the flow knows (role-scoped tools, skill
prompt, role, behavioral learner, harness block, ...) to that factory, on
``ExecuteStepCommand.step_context``. In process only: it is excluded from every
dump of the command.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True)
class StepExecutionContext:
    """Per-flow ``ExecutorAgent`` keyword arguments; None means "not set"."""

    tools: Any = None
    skill_prompt: str | None = None
    skill_retriever: Any = None
    profile_name: str | None = None
    personality: Any = None
    agent_role: str | None = None
    behavioral_learner: Any = None
    harness_instruction_block: str | None = None
    middleware_chain: Any = None
    trajectory_config: Any = None
    max_steps: int | None = None
    pinned_model: str | None = None  # `flow run --model`: tried first each step

    def executor_kwargs(self) -> dict[str, Any]:
        """The fields the flow set, as ``ExecutorAgent`` keyword arguments."""
        return {
            f.name: getattr(self, f.name)
            for f in fields(self)
            if getattr(self, f.name) is not None
        }
