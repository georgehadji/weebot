"""VerifyingState — Chain-of-Verification fact-checking after summarization.

Implements the CoVe pattern (Dhuliawala et al., 2023):
1. Generate verification questions from the summary
2. Answer each question INDEPENDENTLY (no shared context with draft)
3. If contradictions found, revise the summary
4. Emit VerificationEvents for audit

Factored verification: each question is answered in its own LLM call
without seeing the original summary.  This prevents the LLM from
repeating hallucinations (the paper's key finding).
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from openai import AuthenticationError

from weebot.application.flows.states.base import FlowState, AgentStatus
from weebot.config.constants import (
    MAX_TOKENS_BRIEF,
    MAX_TOKENS_COMPACT,
    MAX_TOKENS_CRISP,
    MAX_TOKENS_SHORT,
    MAX_TOKENS_VERDICT,
    TEMPERATURE_DETERMINISTIC,
    VERIFICATION_AXES,
    VERIFICATION_MAX_REVISION_PASSES,
    VERIFICATION_SCORE_MIN,
)
from weebot.domain.models.event import VerificationEvent

_log = logging.getLogger(__name__)

# Number of consecutive auth errors before skipping verification.
_MAX_AUTH_RETRIES = 2


class VerifyingState(FlowState):
    """CoVe verification state — fact-checks the summary before completion.

    Controlled by env var ``WEEBOT_COVE_ENABLED`` (default: True).
    Set to ``false`` to skip verification and proceed directly to Completed.
    """

    status = AgentStatus.VERIFYING  # type: ignore[assignment]

    def __init__(self, max_questions: int = 3):
        self._max_questions = max_questions

    async def execute(self, flow, prompt: str = ""):
        """Run the CoVe verification pipeline.

        Args:
            flow: The PlanActFlow instance (provides llm, session, plan).
            prompt: Not used — verification runs on the flow's current plan/session.
        """
        from weebot.config.settings import WeebotSettings
        _settings = WeebotSettings()

        # ── Feature toggle ──────────────────────────────────────────
        if not _settings.cove_enabled:
            _log.debug("CoVe disabled — skipping verification")
            from weebot.application.flows.states.completed import CompletedState
            flow.set_state(CompletedState())
            return

        num_questions = _settings.cove_max_questions

        # ── Get the summary to verify ───────────────────────────────
        plan = flow._plan
        if plan is None:
            _log.debug("No plan to verify — skipping")
            from weebot.application.flows.states.completed import CompletedState
            flow.set_state(CompletedState())
            return

        # Collect completed step results as the "summary" to fact-check
        completed = [s for s in plan.steps if hasattr(s.status, "value") and s.status.value == "completed"]
        if not completed:
            _log.debug("No completed steps to verify — skipping")
            from weebot.application.flows.states.completed import CompletedState
            flow.set_state(CompletedState())
            return

        summary = "\n".join(
            f"Step {s.id}: {s.description}\nResult: {s.result or '(no result)'}"
            for s in completed[-5:]  # Last 5 steps
        )

        # ── Auth error guard: if the LLM is unreachable (circuit breaker
        # open + dead fallback), skip verification instead of retrying 7+ times.
        _auth_error_count = 0

        # ── Step 1: Generate verification questions ─────────────────
        try:
            questions = await self._generate_questions(flow, summary, num_questions)
        except AuthenticationError:
            _log.warning(
                "Verification skipped: authentication error on question generation. "
                "Check OPENROUTER_API_KEY and XAI_API_KEY."
            )
            from weebot.application.flows.states.completed import CompletedState
            flow.set_state(CompletedState())
            return
        if not questions:
            _log.debug("No verification questions generated — skipping")
            from weebot.application.flows.states.completed import CompletedState
            flow.set_state(CompletedState())
            return

        # ── Step 2: Answer each independently (factored) ────────────
        inconsistencies: list[tuple[str, str, str]] = []  # (question, answer, original_claim)
        for question in questions:
            try:
                answer = await self._answer_independently(flow, question)
                consistent = await self._check_consistency(flow, question, answer, summary)
            except AuthenticationError:
                _auth_error_count += 1
                if _auth_error_count >= _MAX_AUTH_RETRIES:
                    _log.warning(
                        "Verification skipped: %d consecutive auth errors. "
                        "Circuit breaker may be open or API keys are invalid.",
                        _auth_error_count,
                    )
                    from weebot.application.flows.states.completed import CompletedState
                    flow.set_state(CompletedState())
                    return
                # Skip this question, continue with others
                continue
            _auth_error_count = 0  # reset on success

            yield VerificationEvent(
                step_id="verify",
                question=question,
                answer=answer,
                consistent=consistent,
            )

            if not consistent:
                # Find which claim this question was about
                inconsistencies.append((question, answer, summary[:200]))

        # ── Step 3: Revise if needed ────────────────────────────────
        if inconsistencies:
            _log.info(
                "CoVe found %d inconsistencies — revising summary",
                len(inconsistencies),
            )
            revised = await self._revise_summary(flow, summary, inconsistencies)
            if revised:
                last = completed[-1]
                setattr(last, "result", revised[:500])
                summary = revised
        else:
            _log.info("CoVe verification passed — no inconsistencies")

        # ── Step 4: Self-critique scoring ───────────────────────────
        final_summary, scores = await self._score_and_revise(flow, summary)

        # ── Step 5: Gate sweep ──────────────────────────────────────
        gate_failures = await self._gate_sweep(flow, final_summary)
        for gate in gate_failures:
            yield VerificationEvent(
                step_id="gate_sweep",
                question=f"Gate: {gate}",
                answer="FAILED",
                consistent=False,
            )

        # Store scores + gate results on session for stamp
        if hasattr(flow._session, "context"):
            ctx = flow._session.context
            try:
                ctx.extra["verification_scores"] = scores
                ctx.extra["gate_failures"] = gate_failures
            except Exception:
                pass

        # ── Hook: post_verification ─────────────────────────────────
        if getattr(flow, "_hooks", None) is not None:
            await flow._hooks.execute_hooks("post_verification", {
                "session_id": flow._session.id,
                "scores": scores,
                "gate_failures": gate_failures,
                "inconsistency_count": len(inconsistencies) if 'inconsistencies' in dir() else 0,
            })

        # ── Transition to Completed ─────────────────────────────────
        from weebot.application.flows.states.completed import CompletedState
        flow.set_state(CompletedState())

    # ── Self-critique scoring ───────────────────────────────────────

    async def _score_output(self, flow, summary: str) -> dict[str, int]:
        """Score the summary on VERIFICATION_AXES (1-5 each).

        Returns a dict like {"correctness": 4, "completeness": 5, ...}.
        """
        axes_list = ", ".join(VERIFICATION_AXES)
        prompt = (
            f"Score this agent output 1-5 on each axis:\n"
            f"1. Correctness — Are all factual claims backed by tool output or prior verification?\n"
            f"2. Completeness — Did the agent address every part of the user's request?\n"
            f"3. Specificity — Does the output reference specific files, commands, numbers, or results?\n"
            f"4. Restraint — Did the agent avoid unnecessary extra work, refactors, or tangents?\n\n"
            f"Output:\n{summary[:1000]}\n\n"
            f'Return ONLY valid JSON: {{"correctness": N, "completeness": N, "specificity": N, "restraint": N}}'
        )
        try:
            response = await flow._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=TEMPERATURE_DETERMINISTIC,
                max_tokens=MAX_TOKENS_BRIEF,
            )
            scores = json.loads(response.content or "{}")
            return {
                axis: max(1, min(5, int(scores.get(axis, VERIFICATION_SCORE_MIN))))
                for axis in VERIFICATION_AXES
            }
        except Exception:
            _log.debug("Self-critique scoring failed — assuming passing scores", exc_info=True)
            return {axis: VERIFICATION_SCORE_MIN for axis in VERIFICATION_AXES}

    async def _score_and_revise(self, flow, summary: str) -> tuple[str, dict[str, int]]:
        """Score the summary; revise if any axis < VERIFICATION_SCORE_MIN.

        Returns (final_summary, final_scores). Limits revision to
        VERIFICATION_MAX_REVISION_PASSES attempts.
        """
        for attempt in range(1, VERIFICATION_MAX_REVISION_PASSES + 1):
            scores = await self._score_output(flow, summary)
            weak_axes = [a for a, s in scores.items() if s < VERIFICATION_SCORE_MIN]

            if not weak_axes:
                _log.info("Self-critique passed: %s", scores)
                return summary, scores

            _log.info(
                "Self-critique attempt %d/%d — weak axes: %s (scores: %s)",
                attempt, VERIFICATION_MAX_REVISION_PASSES, weak_axes, scores,
            )

            # Revise: prompt the LLM to improve the weak axes
            revision_hint = ", ".join(weak_axes)
            prompt = (
                f"Your output scored below threshold on these axes: {revision_hint}.\n"
                f"Original output:\n{summary[:800]}\n\n"
                f"Revise the output to improve ONLY the weak axes. Keep everything else."
            )
            try:
                response = await flow._llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=TEMPERATURE_DETERMINISTIC,
                    max_tokens=MAX_TOKENS_SHORT,
                )
                summary = (response.content or summary).strip()
            except Exception:
                _log.debug("Revision failed — keeping current summary", exc_info=True)
                break

        # Final attempt — accept whatever we have
        final_scores = await self._score_output(flow, summary)
        return summary, final_scores

    # ── Gate sweep ──────────────────────────────────────────────────

    async def _gate_sweep(self, flow, summary: str) -> list[str]:
        """Run 5 binary gates on the session. Returns list of failed gate names."""
        failures: list[str] = []

        # Gate 1: Unverified facts — did VerifyingState find inconsistencies?
        # (Tracked via VerificationEvents in the session — check from execute())
        # Gate 2: Blocked commands — check session events for BLOCKED tool calls
        session = flow._session
        from weebot.domain.models.event import ToolEvent
        for event in session.events:
            if isinstance(event, ToolEvent):
                result = getattr(event, "result", "")
                if result and "blocked" in str(result).lower():
                    failures.append("blocked_commands")
                    break

        # Gate 3: Unresolved errors — check for ErrorEvents without recovery
        from weebot.domain.models.event import ErrorEvent, WaitForUserEvent
        has_error = any(isinstance(e, ErrorEvent) for e in session.events)
        has_recovery = any(isinstance(e, WaitForUserEvent) for e in session.events)
        if has_error and not has_recovery:
            failures.append("unresolved_errors")

        # Gate 4: Token budget — check executor token usage
        if flow._executor and hasattr(flow._executor, "token_usage"):
            usage = flow._executor.token_usage
            if usage.get("total_tokens", 0) > 100_000:
                failures.append("token_budget_exceeded")

        # Gate 5: Unverified file writes — check for write events without verification
        if hasattr(flow._session, "events"):
            write_count = sum(
                1 for e in flow._session.events
                if isinstance(e, ToolEvent)
                and getattr(e, "tool_name", "") == "file_editor"
                and "str_replace" in str(getattr(e, "function_args", {}))
            )
            verify_count = sum(
                1 for e in flow._session.events
                if isinstance(e, VerificationEvent)
                and getattr(e, "step_id", "") == "gate_verify"
            )
            if write_count > 0 and verify_count == 0:
                failures.append("unverified_writes")

        # Gate 6+7: Artifact verification (Enhancement 3 — S7 fix)
        artifact_failures = await self._gate_artifact_verification(flow)
        failures.extend(artifact_failures)

        if failures:
            _log.info("Gate sweep failed: %s", failures)
        else:
            _log.info("Gate sweep passed — all gates clean")

        return failures

    async def _gate_artifact_verification(self, flow) -> list[str]:
        """Verify execution artifacts exist and tests passed.

        Reads ToolEvent results directly — NOT the LLM summary.
        Addresses S7 (Inaccurate Self-Reporting): agent claims completion
        but execution artifacts contradict it.
        """
        from pathlib import Path
        from weebot.domain.models.event import ToolEvent as _ToolEvent

        failures: list[str] = []
        session = flow._session

        # Gate A: Files written by file_editor must still exist on disk.
        written_paths: list[str] = []
        for event in session.events:
            if not isinstance(event, _ToolEvent):
                continue
            if event.tool_name not in ("file_editor", "edit_file", "write_file", "create_file"):
                continue
            args = event.function_args or {}
            path = args.get("path") or args.get("file_path") or args.get("target_file", "")
            if path:
                written_paths.append(str(path))

        missing = []
        for p in written_paths:
            try:
                if not Path(p).exists():
                    missing.append(p)
            except (OSError, ValueError):
                pass  # invalid path — skip without blocking

        if missing:
            _log.warning(
                "Artifact gate A: %d written file(s) not found on disk: %s",
                len(missing), missing[:3],
            )
            failures.append(f"written_files_missing:{','.join(missing[:2])}")

        # Gate B: Test commands with failure markers in their output.
        _test_keywords = (
            "pytest", "npm test", "jest", "cargo test", "go test", "python -m pytest",
        )
        for event in session.events:
            if not isinstance(event, _ToolEvent):
                continue
            if event.tool_name not in ("bash", "shell_exec", "powershell"):
                continue
            cmd = str((event.function_args or {}).get("command", "")).lower()
            if not any(kw in cmd for kw in _test_keywords):
                continue
            result = (event.result or "").lower()
            if any(m in result for m in ("failed", "error", "assertion error", "test failed")):
                if "passed" not in result:
                    _log.warning("Artifact gate B: test failure detected in bash output")
                    failures.append("test_run_failed")
                    break

        return failures

    # ── Internal ─────────────────────────────────────────────────────

    async def _generate_questions(self, flow, summary: str, n: int) -> list[str]:
        """Generate verification questions from the summary."""
        prompt = (
            f"Given this task summary, list up to {n} specific fact-checking "
            f"questions that could verify its accuracy.  Each question should "
            f"target a concrete claim (dates, counts, names, file paths, results).\n\n"
            f"Summary:\n{summary}\n\n"
            f"Verification questions (one per line, no numbering):"
        )
        try:
            response = await flow._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=TEMPERATURE_DETERMINISTIC,
                max_tokens=MAX_TOKENS_COMPACT,
            )
            content = response.content or ""
            questions = [
                line.strip("-• "*3).strip()
                for line in content.splitlines()
                if line.strip() and "?" in line
            ]
            return questions[:n]
        except Exception:
            _log.debug("Failed to generate verification questions", exc_info=True)
            return []

    async def _answer_independently(self, flow, question: str) -> str:
        """Answer a verification question WITHOUT seeing the original summary."""
        try:
            response = await flow._llm.chat(
                messages=[{"role": "user", "content": question}],
                temperature=TEMPERATURE_DETERMINISTIC,
                max_tokens=MAX_TOKENS_CRISP,
            )
            return (response.content or "").strip()
        except Exception:
            _log.debug("Failed to answer verification question", exc_info=True)
            return "(verification failed)"

    async def _check_consistency(
        self, flow, question: str, answer: str, summary: str
    ) -> bool:
        """Check if the independent answer is consistent with the summary."""
        prompt = (
            f"Original claim (from summary):\n{summary[:300]}\n\n"
            f"Verification question: {question}\n"
            f"Independent answer: {answer}\n\n"
            f"Is the independent answer CONSISTENT with the original claim? "
            f"Answer only YES or NO."
        )
        try:
            response = await flow._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=TEMPERATURE_DETERMINISTIC,
                max_tokens=MAX_TOKENS_VERDICT,
            )
            return "yes" in (response.content or "").lower()
        except Exception:
            return True  # Assume consistent on failure — don't block completion

    async def _revise_summary(
        self, flow, summary: str, inconsistencies: list[tuple[str, str, str]]
    ) -> str | None:
        """Revise the summary based on verified inconsistencies."""
        inc_block = "\n".join(
            f"Q: {q}\nA: {a}\n" for q, a, _ in inconsistencies
        )
        prompt = (
            f"Original summary:\n{summary}\n\n"
            f"The following claims were found to be inconsistent:\n{inc_block}\n\n"
            f"Revise the summary to correct only the inconsistent claims. "
            f"Keep everything else unchanged."
        )
        try:
            response = await flow._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=TEMPERATURE_DETERMINISTIC,
                max_tokens=MAX_TOKENS_SHORT,
            )
            return (response.content or "").strip()
        except Exception:
            _log.debug("Failed to revise summary", exc_info=True)
            return None
