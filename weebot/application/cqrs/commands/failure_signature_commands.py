"""CQRS commands and queries for failure signature pipeline (Pydantic models).

Commands:
  - ExtractFailureSignatureCommand: extract φ(r_i) from a failed trajectory.
  - BatchExtractSignaturesCommand: batch extraction across many sessions.

Queries:
  - ClusterFailurePatternsQuery: group signatures by cluster key.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from weebot.application.cqrs.base import Command, Query


class ExtractFailureSignatureCommand(Command):
    """Extract a structured failure signature from a completed session.

    Emitted automatically by the ScoreTrajectoryHandler when a trajectory
    does not pass.  The handler calls a budget-tier LLM to parse
    (terminal_cause, agent_behavior, mechanism) from the trajectory text.
    """
    session_id: str = Field(min_length=1)
    task_id: str = Field(default="", description="Task identifier")
    trajectory_text: str = Field(default="", description="Compact trace for LLM analysis")
    failure_modes: list[str] = Field(
        default_factory=list,
        description="Existing failure mode labels (if any)",
    )
    trajectory_health: str | None = Field(
        default=None,
        description="Per-trajectory health classification, if available",
    )
    harness_version: str = Field(default="", description="Harness version at time of failure")
    model_id: str = Field(default="", description="Model that was executing")


class BatchExtractSignaturesCommand(Command):
    """Batch extraction — re-extract signatures for a set of session IDs.

    Useful when the harness version is updated and historical traces need
    re-clustering, or for initial bootstrapping of the signature table.
    """
    lookback_days: int = Field(default=7, ge=1, le=365)
    max_sessions: int = Field(default=200, ge=1, le=1000)
    harness_version: str = Field(default="")
    model_id: str = Field(default="")
    force_reprocess: bool = Field(
        default=False,
        description="Re-extract even for sessions that already have signatures",
    )


class ClusterFailurePatternsQuery(Query):
    """Query: group failure signatures into clusters for harness proposals.

    Returns an EvidenceBundle with clusters ordered by
    (support × mean_actionability) descending.
    """
    harness_version: str = Field(default="", description="Filter by harness version")
    model_id: str = Field(default="", description="Filter by model")
    min_support: int = Field(default=3, ge=1, le=100, description="Minimum cluster size")
    lookback_days: int = Field(default=7, ge=1, le=365)
    max_clusters: int = Field(default=5, ge=1, le=50, description="Max clusters to return")
