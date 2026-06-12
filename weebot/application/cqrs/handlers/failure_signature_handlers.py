"""CQRS handlers for failure signature extraction and clustering.

ExtractFailureSignatureHandler:
  Calls a budget-tier LLM to parse (terminal_cause, agent_behavior, mechanism)
  from a failed trajectory's trace text.  Persists the result.

ClusterFailurePatternsHandler:
  Groups stored signatures by exact (cause, behavior, mechanism) match,
  orders by (support × mean_actionability), and returns an EvidenceBundle.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from weebot.application.cqrs.base import CommandHandler, CommandResult, QueryHandler, QueryResult
from weebot.application.cqrs.commands.failure_signature_commands import (
    BatchExtractSignaturesCommand,
    ClusterFailurePatternsQuery,
    ExtractFailureSignatureCommand,
)
from weebot.domain.models.failure_signature import (
    EvidenceBundle,
    FailureCluster,
    FailureSignature,
)
from weebot.domain.models.trajectory import TrajectoryHealth

if TYPE_CHECKING:
    from weebot.application.ports.llm_port import LLMPort
    from weebot.infrastructure.persistence.trajectory_repo import (
        TrajectoryRepository,
    )

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """Analyse the following agent execution trace and extract a structured failure signature.

The trace is from a task that FAILED verification.  Your job is to identify:

1. **terminal_cause** — what the evaluator/verifier ultimately rejected
   (one of: "timeout", "missing_artifact", "assertion_failure", "wrong_output",
    "incomplete", "crash", "permission_denied", "other")
2. **agent_behavior** — what the agent did (or didn't do) that led to the failure
   (e.g. "retry_loop", "wrong_file_edit", "premature_conclusion",
    "dependency_untested", "tool_misuse", "verification_skipped")
3. **mechanism** — the abstract reusable pattern this exemplifies
   (e.g. "unproductive_repetition", "verification_skipped", "tool_misuse",
    "missing_dependency", "wrong_assumption", "early_exit")

Respond ONLY with a JSON object:
{{"terminal_cause": "...", "agent_behavior": "...", "mechanism": "..."}}

Trace:
{trajectory_text}

Failure modes: {failure_modes}
"""


class ExtractFailureSignatureHandler(CommandHandler):
    """Extract a structured FailureSignature from a failed trajectory.

    Uses a budget-tier LLM call to parse the execution trace and identify
    the (terminal_cause, agent_behavior, mechanism) triple.
    """

    def __init__(
        self,
        llm: "LLMPort",
        trajectory_repo: "TrajectoryRepository",
        budget_model: str | None = None,
    ) -> None:
        self._llm = llm
        self._repo = trajectory_repo
        self._budget_model = budget_model

    async def handle(self, command: ExtractFailureSignatureCommand) -> CommandResult:
        try:
            if not command.trajectory_text:
                logger.info(
                    "No trajectory text for session %s — skipping extraction",
                    command.session_id,
                )
                return CommandResult.fail(
                    error="No trajectory text provided",
                    error_code="NO_TRACE",
                )

            # Call LLM to extract the triple
            prompt = _EXTRACTION_PROMPT.format(
                trajectory_text=command.trajectory_text[:4000],
                failure_modes=", ".join(command.failure_modes) if command.failure_modes else "(none)",
            )

            response = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self._budget_model,
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=300,
            )

            if not response or not response.content:
                return CommandResult.fail(
                    error="LLM returned empty response",
                    error_code="EMPTY_LLM",
                )

            # Strip markdown code fences if the model wrapped the JSON
            raw = response.content
            fence_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
            if fence_match:
                raw = fence_match.group(1)

            parsed = json.loads(raw)
            terminal_cause = parsed.get("terminal_cause", "unknown")
            agent_behavior = parsed.get("agent_behavior", "unknown")
            mechanism = parsed.get("mechanism", "unknown")

            # Map trajectory_health string → enum
            health = None
            if command.trajectory_health:
                try:
                    health = TrajectoryHealth(command.trajectory_health)
                except ValueError:
                    logger.warning(
                        "Unknown trajectory_health value %r for session %s — storing as None",
                        command.trajectory_health, command.session_id,
                    )

            # NOTE: command.harness_version currently receives
            # trajectory.harness ("direct_chat" etc.) not a version
            # string like "0.2.0".  Full version wiring is Phase 5.
            signature = FailureSignature(
                session_id=command.session_id,
                task_id=command.task_id or "",
                terminal_cause=terminal_cause,
                agent_behavior=agent_behavior,
                mechanism=mechanism,
                trajectory_health=health,
                actionability_score=_estimate_actionability(
                    terminal_cause, agent_behavior, mechanism,
                ),
                harness_version=command.harness_version,
                model_id=command.model_id,
            )

            await self._repo.save_failure_signature(signature)

            return CommandResult.ok(data={
                "session_id": command.session_id,
                "signature": signature.model_dump(),
            })

        except json.JSONDecodeError as exc:
            return CommandResult.fail(
                error=f"Failed to parse LLM JSON: {exc}",
                error_code="PARSE_ERROR",
            )
        except Exception as exc:
            logger.error("Failure signature extraction failed: %s", exc, exc_info=True)
            return CommandResult.fail(
                error=str(exc),
                error_code="EXTRACTION_ERROR",
            )


class BatchExtractSignaturesHandler(CommandHandler):
    """Re-extract signatures for recent sessions in bulk.

    Used when the harness version is updated or for bootstrapping.
    """

    def __init__(
        self,
        handler: ExtractFailureSignatureHandler,
        trajectory_repo: "TrajectoryRepository",
    ) -> None:
        self._handler = handler
        self._repo = trajectory_repo

    async def handle(self, command: BatchExtractSignaturesCommand) -> CommandResult:
        try:
            existing = await self._repo.get_sessions_without_signature(
                lookback_days=command.lookback_days,
                max_sessions=command.max_sessions,
                force_reprocess=command.force_reprocess,
            )

            if not existing:
                return CommandResult.ok(data={
                    "processed": 0,
                    "message": "No sessions without signatures found",
                })

            results = []
            for session_id, task_id, trace_text, failure_modes in existing:
                sub_cmd = ExtractFailureSignatureCommand(
                    session_id=session_id,
                    task_id=task_id or "",
                    trajectory_text=trace_text or "",
                    failure_modes=json.loads(failure_modes) if failure_modes else [],
                    harness_version=command.harness_version,
                    model_id=command.model_id,
                )
                result = await self._handler.handle(sub_cmd)
                results.append({
                    "session_id": session_id,
                    "success": result.success,
                    "error": result.error if not result.success else None,
                })

            return CommandResult.ok(data={
                "processed": len(results),
                "success_count": sum(1 for r in results if r["success"]),
                "failed_count": sum(1 for r in results if not r["success"]),
                "results": results,
            })

        except Exception as exc:
            logger.error("Batch extraction failed: %s", exc, exc_info=True)
            return CommandResult.fail(
                error=str(exc),
                error_code="BATCH_EXTRACTION_ERROR",
            )


class ClusterFailurePatternsHandler(QueryHandler):
    """Group failure signatures into clusters for harness proposal.

    Queries the failure_signatures table, groups by exact
    (terminal_cause, agent_behavior, mechanism) match, and returns
    an EvidenceBundle ordered by (support × mean_actionability).
    """

    def __init__(self, trajectory_repo: "TrajectoryRepository") -> None:
        self._repo = trajectory_repo

    async def handle(self, query: ClusterFailurePatternsQuery) -> QueryResult:
        try:
            clusters = await self._repo.get_clusters(
                min_support=query.min_support,
                lookback_days=query.lookback_days,
                max_clusters=query.max_clusters,
                harness_version=query.harness_version or None,
                model_id=query.model_id or None,
            )

            total_failures = sum(c.support for c in clusters)

            # Also query total trajectories examined
            total_trajectories = await self._repo.count_trajectories(
                lookback_days=query.lookback_days,
            )

            bundle = EvidenceBundle(
                harness_version=query.harness_version,
                model_id=query.model_id,
                clusters=clusters,
                total_failures=total_failures,
                total_trajectories=total_trajectories,
            )

            return QueryResult.ok(data=bundle.model_dump())

        except Exception as exc:
            logger.error("Failure clustering failed: %s", exc, exc_info=True)
            return QueryResult.fail(error=str(exc))


# ── Helpers ──────────────────────────────────────────────────────────────

def _estimate_actionability(
    terminal_cause: str, agent_behavior: str, mechanism: str,
) -> float:
    """Heuristic actionability score based on signature characteristics.

    Returns 0.0–1.0.  High scores = likely addressable by a harness edit.
    Low scores = likely a model capability or task difficulty limit.
    """
    # Mechanisms that are typically addressable by harness changes
    high_impact = {
        "verification_skipped", "tool_misuse", "missing_dependency",
        "unproductive_repetition", "wrong_assumption",
    }
    # Agent behaviors that indicate addressable patterns
    high_impact_behaviors = {
        "retry_loop", "premature_conclusion", "verification_skipped",
        "dependency_untested",
    }

    # Known terminal causes — use exact match, not substring
    LOW_ACTIONABILITY_CAUSES = {"timeout", "crash"}

    score = 0.5  # neutral baseline

    if mechanism in high_impact:
        score += 0.3
    if agent_behavior in high_impact_behaviors:
        score += 0.2
    if terminal_cause in LOW_ACTIONABILITY_CAUSES:
        penalty = 0.1 if terminal_cause == "timeout" else 0.2
        score -= penalty

    return max(0.1, min(1.0, score))
