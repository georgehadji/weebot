"""Port interface for hook registries.

Any object that implements ``execute_hooks`` with this signature can be wired
into ``PlanActFlowConfig.hooks``.  ``weebot.templates.hooks.HookRegistry``
satisfies this protocol structurally without any import change.
"""
from __future__ import annotations

from typing import Any, Dict, Protocol, runtime_checkable


@runtime_checkable
class HookRegistryPort(Protocol):
    """Observer interface for PlanActFlow lifecycle callbacks.

    Stages fired by PlanActFlow:
      pre_execute       — flow starts     (session_id, prompt, plan)
      post_execute      — flow ends       (session_id, plan, status, elapsed_ms, total_tokens)
      pre_task          — step starts     (session_id, step_id, step_description, step_index, total_steps, plan)
      post_task         — step done       (session_id, step_id, step_description, elapsed_ms, plan)
      on_error          — step/flow err   (session_id, step_id, error, error_type, plan)
      pre_tool_call     — tool dispatched (session_id, step_id, tool_name, tool_args)
      post_tool_call    — tool returned   (session_id, step_id, tool_name, tool_args, result, elapsed_ms, success)
      post_plan_created — plan generated  (session_id, plan, step_count, elapsed_ms)
      post_plan_updated — plan updated    (session_id, plan, step_count, elapsed_ms, reason)
      post_verification — verification    (session_id, scores, gate_failures, inconsistency_count)
      post_bash_guard   — bash guard ran  (session_id, command, risk_level, allowed)
      post_complete     — flow completed  (session_id, plan, tool_count, error_count, total_elapsed_ms, plan_fingerprint)
    """

    async def execute_hooks(
        self, stage: str, context: Dict[str, Any]
    ) -> Dict[str, Any]: ...

    def get_valid_stages(self) -> frozenset[str]: ...


class StepCancelledError(Exception):
    """Raised by a pre_task hook to cancel the current step gracefully.

    The flow catches this, marks the step as completed with a cancellation
    reason, and transitions directly to VerifyingState.
    """

    def __init__(self, reason: str = ""):
        super().__init__(reason)
        self.reason = reason
