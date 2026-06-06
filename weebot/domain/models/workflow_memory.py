"""Workflow-scoped shared memory for multi-agent coordination."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class MemoryEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str = Field(min_length=1)
    value: Any = Field(default=None)
    source_agent_id: str = Field(min_length=1)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkflowMemory(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow_id: str = Field(default_factory=lambda: str(uuid4()))
    entries: tuple[MemoryEntry, ...] = Field(default_factory=tuple)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def add(self, key: str, value: Any, agent_id: str, confidence: float = 0.5) -> "WorkflowMemory":
        entry = MemoryEntry(key=key, value=value, source_agent_id=agent_id, confidence=confidence)
        return self.model_copy(update={"entries": self.entries + (entry,)})

    def get(self, key: str) -> Optional[MemoryEntry]:
        for entry in reversed(self.entries):
            if entry.key == key:
                return entry
        return None

    def snapshot(self) -> dict[str, Any]:
        seen: dict[str, Any] = {}
        for entry in self.entries:
            seen[entry.key] = entry.value
        return seen
