"""Replace loop state + budget cap + stuck detection in _base.py with IterationGuard.

This script replaces lines 500-676 in weebot/application/agents/executor/_base.py
with calls to IterationGuard from _iteration_guard.py.
"""
from __future__ import annotations

from pathlib import Path

BASE_PATH = Path("weebot/application/agents/executor/_base.py")


def main():
    content = Path(BASE_PATH).read_text(encoding="utf-8")

    # Add import
    if "from weebot.application.agents.executor._iteration_guard import IterationGuard" not in content:
        content = content.replace(
            "from weebot.application.agents.executor._prompt_builder import build_executor_prompt",
            "from weebot.application.agents.executor._iteration_guard import IterationGuard, IterationGuardState\nfrom weebot.application.agents.executor._prompt_builder import build_executor_prompt",
        )

    # Replace loop state init (lines 500-512) + budget init (520-524)
    old_loop_start = "        step_result = \"\"\n        loop_error: str | None = None"
    new_loop_start = """        guard = IterationGuard(
            step_id=step.id,
            max_tool_calls_per_step=12,
            max_repeated_assistant_turns=2,
            repeated_tool_signature_limit=4,
        )
        step_result = ""
        loop_error: str | None = None"""
    content = content.replace(old_loop_start, new_loop_start)

    # Remove redundant individual state variables (repeated_assistant_turns, last_assistant_text, etc.)
    # These are now in IterationGuardState
    old_state_vars = """        repeated_assistant_turns = 0
        last_assistant_text = ""
        repeated_tool_calls = 0
        last_tool_signature: str | None = None
        recent_tool_signatures: deque[str] = deque(maxlen=6)
        thought_iteration: int = 0
        tool_calls_attempted: int = 0
        tool_calls_succeeded: int = 0
        semantic_loop_recoveries: int = 0
        _MAX_SEMANTIC_LOOP_RECOVERIES = 2

        # ── Tier 1.3: TrajectoryMonitor — reset per-step windows, preserve cross-step ──
        if self._trajectory_monitor is not None:
            self._trajectory_monitor.reset_step()
            # Pass step description for TDD RED-phase tolerance
            self._trajectory_monitor.set_step_context(step.description or "")

        self._step_budget.reset()
        # Enhancement D: per-step tool-call cap (default 8).
        # Prevents the executor from burning 30+ LLM calls on simple steps.
        _tool_call_count = 0
        _MAX_TOOL_CALLS_PER_STEP = 12"""
    new_state_vars = """        thought_iteration: int = 0
        tool_calls_attempted: int = 0
        tool_calls_succeeded: int = 0
        semantic_loop_recoveries: int = 0
        _MAX_SEMANTIC_LOOP_RECOVERIES = 2

        # ── Tier 1.3: TrajectoryMonitor — reset per-step windows, preserve cross-step ──
        if self._trajectory_monitor is not None:
            self._trajectory_monitor.reset_step()
            self._trajectory_monitor.set_step_context(step.description or "")

        self._step_budget.reset()"""
    content = content.replace(old_state_vars, new_state_vars)

    # Replace while loop header + budget cap check (lines 525-559)
    old_while = """        while self._step_budget.consume():
            _tool_call_count += 1
            if _tool_call_count > _MAX_TOOL_CALLS_PER_STEP:
                logger.warning(
                    "Step %s: tool-call budget exhausted (%d calls). "
                    "Completing step with current findings.",
                    step.id, _MAX_TOOL_CALLS_PER_STEP,
                )
                # Force the LLM to produce a summary instead of more tool calls
                self._conversation_buffer.append({
                    "role": "user",
                    "content": (
                        "You have reached the maximum number of tool calls for this step. "
                        "Summarize what you found and complete the step. Do NOT call "
                        "any more tools."
                    ),
                })
                # One more LLM call to produce the summary, then break
                messages = [
                    {"role": "system", "content": self._system_prompt}
                ] + list(self._conversation_buffer)
                try:
                    response = await self._cascade.call_with_cascade(
                        messages=messages,
                        description=step.description,
                    )
                    step_result = response.content or "Step completed (budget cap)."
                except Exception as exc:
                    logger.warning(
                        "Budget-cap summary call failed: %s — using fallback", exc
                    )
                    step_result = "Step completed (budget cap)."
                yield MessageEvent(role="assistant", message=step_result)
                abort_step = True
                break"""
    new_while = """        while self._step_budget.consume():
            guard.record_iteration()
            if guard.is_tool_call_budget_exhausted():
                logger.warning(
                    "Step %s: tool-call budget exhausted (%d calls). "
                    "Completing step with current findings.",
                    step.id, guard._max_tool_calls,
                )
                self._conversation_buffer.append({
                    "role": "user",
                    "content": (
                        "You have reached the maximum number of tool calls for this step. "
                        "Summarize what you found and complete the step. Do NOT call "
                        "any more tools."
                    ),
                })
                messages = [
                    {"role": "system", "content": self._system_prompt}
                ] + list(self._conversation_buffer)
                try:
                    response = await self._cascade.call_with_cascade(
                        messages=messages,
                        description=step.description,
                    )
                    step_result = response.content or "Step completed (budget cap)."
                except Exception as exc:
                    logger.warning(
                        "Budget-cap summary call failed: %s — using fallback", exc
                    )
                    step_result = "Step completed (budget cap)."
                yield MessageEvent(role="assistant", message=step_result)
                abort_step = True
                break"""
    content = content.replace(old_while, new_while)

    # Replace repeated assistant text detection (lines 623-643)
    old_assistant_stuck = """            if not response.tool_calls:
                normalized = normalize_text(assistant_content)
                if normalized and normalized == last_assistant_text:
                    repeated_assistant_turns += 1
                else:
                    repeated_assistant_turns = 0
                last_assistant_text = normalized

                step_result = assistant_content or "No result"
                if follow_up_like(step_result):
                    step_result = "Step completed. Continuing to the next plan step."

                if repeated_assistant_turns >= 2:
                    loop_error = build_stuck_error(
                        step=step,
                        reason="repeated assistant-only responses with no tool progress",
                        recent_signatures=recent_tool_signatures,
                        max_steps=self._max_steps,
                    )
                    yield ErrorEvent(error=loop_error)
                    break"""
    new_assistant_stuck = """            if not response.tool_calls:
                guard.record_assistant_turn(normalize_text(assistant_content))

                step_result = assistant_content or "No result"
                if follow_up_like(step_result):
                    step_result = "Step completed. Continuing to the next plan step."

                if guard.is_assistant_turn_loop():
                    loop_error = guard.build_stuck_error(
                        reason="repeated assistant-only responses with no tool progress",
                        step_description=step.description,
                    )
                    yield ErrorEvent(error=loop_error)
                    break"""
    content = content.replace(old_assistant_stuck, new_assistant_stuck)

    # Replace repeated tool call detection (lines 649-676)
    old_tool_stuck = """            abort_step = False
            # ── Phase 2: Pre-flight checks (sequential) ─────────
            # Check for repeated tool signatures before executing
            # anything, so we don't waste parallel execution on a
            # stuck sequence.
            _batch_tool_calls: list[dict] = []
            for tc in response.tool_calls:
                tool_name = tc["function"]["name"]
                raw_arguments = tc["function"].get("arguments", "{}")
                signature = tool_signature(tool_name, raw_arguments)
                recent_tool_signatures.append(signature)

                if signature == last_tool_signature:
                    repeated_tool_calls += 1
                else:
                    repeated_tool_calls = 1
                    last_tool_signature = signature

                if repeated_tool_calls >= 4:
                    loop_error = build_stuck_error(
                        step=step,
                        reason=f"repeated identical tool call '{tool_name}'",
                        recent_signatures=recent_tool_signatures,
                        max_steps=self._max_steps,
                    )
                    yield ErrorEvent(error=loop_error)
                    abort_step = True
                    break"""
    new_tool_stuck = """            abort_step = False
            # ── Phase 2: Pre-flight checks (sequential) ─────────
            _batch_tool_calls: list[dict] = []
            for tc in response.tool_calls:
                tool_name = tc["function"]["name"]
                raw_arguments = tc["function"].get("arguments", "{}")
                signature = tool_signature(tool_name, raw_arguments)
                guard.record_tool_call(signature)

                if guard.is_tool_signature_loop():
                    loop_error = guard.build_stuck_error(
                        reason=f"repeated identical tool call '{tool_name}'",
                        step_description=step.description,
                    )
                    yield ErrorEvent(error=loop_error)
                    abort_step = True
                    break"""
    content = content.replace(old_tool_stuck, new_tool_stuck)

    Path(BASE_PATH).write_text(content, encoding="utf-8", newline="")
    print("IterationGuard wired into execute_step loop")


if __name__ == "__main__":
    main()
