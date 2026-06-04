"""UserModelingService — dialectic user modeling across sessions.

Tracks user interaction patterns, preferences, and expertise level
across sessions to build a deepening model of the user.

Inspired by Honcho (plastic-labs/honcho) dialectic user modeling.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class UserObservation:
    """A single observation about the user from a session."""
    timestamp: str
    category: str  # preference, skill, knowledge, behavior
    observation: str
    confidence: float = 0.5


@dataclass
class UserModel:
    """Accumulated model of the user across sessions."""
    user_id: str
    observations: list[UserObservation] = field(default_factory=list)
    expertise_areas: list[str] = field(default_factory=list)
    preferences: dict[str, str] = field(default_factory=dict)
    interaction_count: int = 0

    @property
    def avg_confidence(self) -> float:
        if not self.observations:
            return 0.0
        return sum(o.confidence for o in self.observations) / len(self.observations)


class UserModelingService:
    """Dialectic user modeling — builds a profile from interaction patterns.

    Args:
        models_dir: Directory to persist user models.
    """

    def __init__(self, models_dir: Optional[str] = None) -> None:
        self._dir = Path(models_dir) if models_dir else Path.home() / ".weebot" / "user-models"
        self._dir.mkdir(parents=True, exist_ok=True)

    async def record_observation(
        self,
        user_id: str,
        category: str,
        observation: str,
        confidence: float = 0.5,
    ) -> None:
        """Record an observation about a user."""
        model = await self.load_model(user_id)
        model.observations.append(UserObservation(
            timestamp=datetime.now(timezone.utc).isoformat(),
            category=category,
            observation=observation,
            confidence=confidence,
        ))
        model.interaction_count += 1
        await self._save_model(model)

    async def infer_preference(
        self,
        user_id: str,
        key: str,
        value: str,
    ) -> None:
        """Record or update a user preference."""
        model = await self.load_model(user_id)
        model.preferences[key] = value
        await self._save_model(model)

    async def load_model(self, user_id: str) -> UserModel:
        """Load a user model, creating a new one if none exists."""
        path = self._dir / f"{user_id}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return UserModel(
                user_id=data["user_id"],
                observations=[UserObservation(**o) for o in data.get("observations", [])],
                expertise_areas=data.get("expertise_areas", []),
                preferences=data.get("preferences", {}),
                interaction_count=data.get("interaction_count", 0),
            )
        return UserModel(user_id=user_id)

    async def get_context_summary(self, user_id: str) -> str:
        """Generate a context summary for the agent prompt.

        Returns a natural language summary of the user model
        suitable for injection into the system prompt.
        """
        model = await self.load_model(user_id)
        if model.interaction_count == 0:
            return ""

        parts = []
        if model.preferences:
            prefs = "; ".join(f"{k}={v}" for k, v in model.preferences.items())
            parts.append(f"User preferences: {prefs}")
        if model.expertise_areas:
            parts.append(f"User expertise: {', '.join(model.expertise_areas)}")
        if model.observations:
            recent = model.observations[-3:]
            for o in recent:
                parts.append(f"Observed ({o.category}): {o.observation}")

        return "\n".join(parts)

    async def _save_model(self, model: UserModel) -> None:
        """Persist a user model to disk."""
        path = self._dir / f"{model.user_id}.json"
        data = {
            "user_id": model.user_id,
            "observations": [{"timestamp": o.timestamp, "category": o.category,
                              "observation": o.observation, "confidence": o.confidence}
                             for o in model.observations],
            "expertise_areas": model.expertise_areas,
            "preferences": model.preferences,
            "interaction_count": model.interaction_count,
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
