"""Cron job domain models — scheduled agent task definitions.

Extends the existing SchedulingManager's job model with agent-specific
fields: prompt, attached skills, toolset selection, delivery target,
and runtime limits.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DeliveryTargetType(str, Enum):
    """Where to deliver cron agent results."""
    TELEGRAM = "telegram"
    DISCORD = "discord"
    SLACK = "slack"
    FILE = "file"
    NONE = "none"


class DeliveryTarget(BaseModel):
    """Where and how to deliver cron agent results."""
    type: DeliveryTargetType = DeliveryTargetType.NONE
    destination: str | None = Field(
        default=None,
        description="Chat ID, channel ID, file path, etc.",
    )
    format: str = Field(default="text", description="Delivery format: text, markdown, json")


class CronJobRecord(BaseModel):
    """A cron-scheduled agent task.

    Each record defines a job that spawns a PlanActFlow session with
    the specified prompt, skills, and toolsets at the scheduled interval.
    """
    id: str = Field(description="Unique job identifier")
    name: str = Field(description="Human-readable job name")
    schedule: str = Field(description="Cron expression or natural language schedule")
    prompt: str = Field(description="Task prompt for the agent session")
    attached_skills: list[str] = Field(default_factory=list, description="Skill names to inject")
    attached_toolsets: list[str] = Field(
        default_factory=list,
        description="Toolset names (e.g., 'admin', 'automation')",
    )
    model: str | None = Field(default=None, description="Model override for this job")
    provider: str | None = Field(default=None, description="Provider override")
    deliver_to: DeliveryTarget = Field(default_factory=DeliveryTarget)
    max_runtime_seconds: int = Field(default=300, ge=30, le=3600)
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_run_at: datetime | None = None
    last_result: str | None = None
    last_error: str | None = None
    run_count: int = 0
    error_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
