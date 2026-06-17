"""Suggestion Engine — generates blueprint-based scheduling suggestions on skill install.

When a skill is installed and has a ``blueprint`` field in its manifest,
the suggestion engine creates a suggestion (not an active job) that the
user can accept, dismiss, or modify.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weebot.domain.models.skill import Skill

logger = logging.getLogger(__name__)

SUGGESTIONS_PATH = Path.home() / ".weebot" / "skill_suggestions.json"


class BlueprintSuggestion:
    """A suggestion to create a cron agent job from a skill's blueprint."""

    def __init__(
        self,
        skill_name: str,
        schedule: str,
        prompt: str,
        deliver_to: str = "none",
        destination: str | None = None,
        no_agent: bool = False,
    ) -> None:
        self.id = f"suggestion-{uuid.uuid4().hex[:8]}"
        self.skill_name = skill_name
        self.schedule = schedule
        self.prompt = prompt
        self.deliver_to = deliver_to
        self.destination = destination
        self.no_agent = no_agent
        self.created_at = datetime.now(timezone.utc)
        self.status = "pending"  # pending, accepted, dismissed, modified

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "skill_name": self.skill_name,
            "schedule": self.schedule,
            "prompt": self.prompt,
            "deliver_to": self.deliver_to,
            "destination": self.destination,
            "no_agent": self.no_agent,
            "created_at": self.created_at.isoformat(),
            "status": self.status,
        }

    @classmethod
    def from_skill(cls, skill: Skill) -> "BlueprintSuggestion | None":
        """Create a suggestion from a skill's blueprint, if present."""
        bp = skill.blueprint
        if bp is None:
            return None
        return cls(
            skill_name=skill.name,
            schedule=bp.get("schedule", "0 * * * *"),
            prompt=bp.get("prompt", f"Run skill: {skill.name}"),
            deliver_to=bp.get("deliver_to", "none"),
            destination=bp.get("destination"),
            no_agent=bp.get("no_agent", False),
        )


class SuggestionEngine:
    """Manages blueprint-based scheduling suggestions."""

    def __init__(self) -> None:
        self._suggestions: dict[str, BlueprintSuggestion] = {}
        self._load()

    def _load(self) -> None:
        """Load suggestions from disk."""
        if SUGGESTIONS_PATH.exists():
            try:
                data = json.loads(SUGGESTIONS_PATH.read_text(encoding="utf-8"))
                for item in data:
                    s = BlueprintSuggestion(
                        skill_name=item["skill_name"],
                        schedule=item["schedule"],
                        prompt=item["prompt"],
                        deliver_to=item.get("deliver_to", "none"),
                        destination=item.get("destination"),
                        no_agent=item.get("no_agent", False),
                    )
                    s.id = item["id"]
                    s.created_at = datetime.fromisoformat(item["created_at"])
                    s.status = item.get("status", "pending")
                    self._suggestions[s.id] = s
            except Exception as exc:
                logger.warning("Failed to load suggestions: %s", exc)

    def _save(self) -> None:
        """Persist suggestions to disk."""
        SUGGESTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = [s.to_dict() for s in self._suggestions.values()]
        SUGGESTIONS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def add_suggestion(self, suggestion: BlueprintSuggestion) -> None:
        """Add a new suggestion."""
        self._suggestions[suggestion.id] = suggestion
        self._save()
        logger.info("Created suggestion: %s for skill '%s'", suggestion.id, suggestion.skill_name)

    def add_from_skill(self, skill: Skill) -> BlueprintSuggestion | None:
        """Create a suggestion from a skill's blueprint, if present."""
        suggestion = BlueprintSuggestion.from_skill(skill)
        if suggestion:
            self.add_suggestion(suggestion)
        return suggestion

    def accept(self, suggestion_id: str) -> BlueprintSuggestion | None:
        """Accept a suggestion (creates the actual cron job)."""
        suggestion = self._suggestions.get(suggestion_id)
        if suggestion is None:
            return None
        suggestion.status = "accepted"
        self._save()
        return suggestion

    def dismiss(self, suggestion_id: str) -> bool:
        """Dismiss a suggestion."""
        suggestion = self._suggestions.get(suggestion_id)
        if suggestion is None:
            return False
        suggestion.status = "dismissed"
        self._save()
        return True

    def list_pending(self) -> list[BlueprintSuggestion]:
        """Return all pending suggestions."""
        return [s for s in self._suggestions.values() if s.status == "pending"]

    def list_all(self) -> list[BlueprintSuggestion]:
        """Return all suggestions."""
        return list(self._suggestions.values())
