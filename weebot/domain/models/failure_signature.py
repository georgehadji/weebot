"""Failure signature domain models — the paper's φ(r_i) = (cause, behavior, mechanism) triple.

These models replace the current flat ``failure_modes: list[str]`` on
TrajectorySummary with structured, clusterable failure signatures.  The
Self-Harness Weakness Mining stage groups failed trajectories by exact
signature match, enabling targeted harness edits.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from weebot.domain.models.trajectory import TrajectoryHealth


class FailureSignature(BaseModel):
    """A structured failure signature — the paper's φ(r_i).

    Three fields capture the failure at increasing levels of abstraction:

    - **terminal_cause:** what the evaluator/verifier rejected
      (e.g. ``"timeout"``, ``"missing_artifact"``, ``"assertion_failure"``,
       ``"wrong_output"``)
    - **agent_behavior:** what the agent did (or failed to do) that
      led to the cause (e.g. ``"retry_loop"``, ``"wrong_file_edit"``,
       ``"premature_conclusion"``, ``"dependency_untested"``)
    - **mechanism:** the abstract reusable pattern this trace exemplifies
      (e.g. ``"unproductive_repetition"``, ``"verification_skipped"``,
       ``"tool_misuse"``, ``"missing_dependency"``)
    """

    session_id: str = Field(description="Session that produced this failure")
    task_id: str = Field(description="Task being executed")
    terminal_cause: str = Field(
        description="What the verifier/evaluator rejected",
    )
    agent_behavior: str = Field(
        description="What the agent did that led to the cause",
    )
    mechanism: str = Field(
        description="Abstract reusable failure pattern",
    )
    trajectory_health: Optional[TrajectoryHealth] = Field(
        default=None,
        description="Per-trajectory health classification (if available)",
    )
    actionability_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Estimated how actionable this signature is for harness edits",
    )
    harness_version: str = Field(
        default="",
        description="Harness version at time of failure",
    )
    model_id: str = Field(
        default="",
        description="Model that was executing when the failure occurred",
    )
    extracted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def cluster_key(self) -> tuple[str, str, str]:
        """Return the exact-match clustering key (cause, behavior, mechanism)."""
        return (self.terminal_cause, self.agent_behavior, self.mechanism)


class FailureCluster(BaseModel):
    """A cluster of failures sharing the same signature.

    This is the output of the Weakness Mining stage.  Each cluster
    represents a recurring failure mechanism that can potentially
    be addressed by a single harness edit.
    """

    signature: FailureSignature = Field(
        description="Representative signature for this cluster",
    )
    support: int = Field(
        ge=1, description="Number of sessions sharing this signature",
    )
    representative_session_ids: list[str] = Field(
        default_factory=list,
        description="Sample session IDs in this cluster (for trace inspection)",
    )
    mean_actionability: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Mean actionability across cluster members",
    )

    @classmethod
    def from_signatures(
        cls,
        signatures: list[FailureSignature],
    ) -> "FailureCluster":
        """Build a cluster from one or more signatures with identical keys."""
        if not signatures:
            raise ValueError("Cannot build cluster from empty list")

        rep = signatures[0]
        return cls(
            signature=rep,
            support=len(signatures),
            representative_session_ids=[s.session_id for s in signatures[:5]],
            mean_actionability=sum(
                s.actionability_score for s in signatures
            ) / len(signatures),
        )


class EvidenceBundle(BaseModel):
    """The mined evidence passed from Weakness Mining to Harness Proposal.

    Contains the dominant failure patterns ordered by (support ×
    mean_actionability), alongside metadata about the execution context.
    """

    harness_version: str = Field(default="", description="Harness version mined")
    model_id: str = Field(default="", description="Model used during mining")
    clusters: list[FailureCluster] = Field(
        default_factory=list,
        description="Failure clusters ordered by priority (descending)",
    )
    total_failures: int = Field(
        default=0, ge=0, description="Total failed trajectories examined",
    )
    total_trajectories: int = Field(
        default=0, ge=0, description="Total trajectories examined (including passes)",
    )
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    def top_clusters(self, n: int = 5) -> list[FailureCluster]:
        """Return the top N clusters by (support × mean_actionability) descending."""
        scored = sorted(
            self.clusters,
            key=lambda c: c.support * c.mean_actionability,
            reverse=True,
        )
        return scored[:n]
