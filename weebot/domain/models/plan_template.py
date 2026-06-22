"""PlanTemplate — a validated plan stored for reuse on similar tasks."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class PlanTemplate:
    """A validated plan that can seed planning for similar future tasks.

    Attributes:
        template_id: Unique identifier (UUID string).
        task_hash: SHA-256 fingerprint of the normalized task description.
        task_description: The original task prompt that produced this plan.
        plan_json: JSON-serialized Plan (steps, title, etc.).
        success_score: How well the plan performed (0.0-1.0), based on
            completion rate and verification scores.
        use_count: Number of times this template has been reused.
        created_at: When the template was first saved.
        last_used_at: When the template was last retrieved for seeding.
    """
    template_id: str
    task_hash: str
    task_description: str
    plan_json: str
    success_score: float = 1.0
    use_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_used_at: Optional[datetime] = None
