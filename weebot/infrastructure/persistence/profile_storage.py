"""Profile storage adapters — concrete implementations of ProfileStoragePort.

Extracted from the original domain/models/user_profile.py monolith as
part of architecture remediation (step-6).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

from weebot.application.ports.profile_storage_port import ProfileStoragePort
from weebot.domain.models.user_profile import (
    UserProfile,
    UserProfileType,
    UserPreference,
    PreferenceCategory,
    UserInteraction,
    InteractionType,
    UserGoal,
)

logger = logging.getLogger(__name__)


class InMemoryUserProfileStorage(ProfileStoragePort):
    """In-memory storage for user profiles."""

    def __init__(self):
        self.profiles: Dict[str, UserProfile] = {}

    async def save_profile(self, profile: UserProfile) -> bool:
        try:
            self.profiles[profile.user_id] = profile
            return True
        except Exception as e:
            logger.error("Error saving profile for user %s: %s", profile.user_id, e)
            return False

    async def load_profile(self, user_id: str) -> Optional[UserProfile]:
        return self.profiles.get(user_id)

    async def delete_profile(self, user_id: str) -> bool:
        if user_id in self.profiles:
            del self.profiles[user_id]
            return True
        return False

    async def update_profile(self, profile: UserProfile) -> bool:
        return await self.save_profile(profile)


class FileUserProfileStorage(ProfileStoragePort):
    """File-based storage for user profiles."""

    def __init__(self, storage_dir: str = "./user_profiles"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(exist_ok=True)

    async def save_profile(self, profile: UserProfile) -> bool:
        try:
            profile_dict = {
                "user_id": profile.user_id,
                "profile_type": profile.profile_type.value,
                "created_at": profile.created_at.isoformat(),
                "last_interaction": profile.last_interaction.isoformat(),
                "name": profile.name,
                "email": profile.email,
                "preferences": [
                    {
                        "category": pref.category.value,
                        "key": pref.key,
                        "value": pref.value,
                        "last_updated": pref.last_updated.isoformat(),
                        "confidence": pref.confidence,
                    }
                    for pref in profile.preferences
                ],
                "interaction_history": [
                    {
                        "interaction_id": interaction.interaction_id,
                        "interaction_type": interaction.interaction_type.value,
                        "timestamp": interaction.timestamp.isoformat(),
                        "content": interaction.content,
                        "context": interaction.context,
                        "outcome": interaction.outcome,
                        "satisfaction_score": interaction.satisfaction_score,
                    }
                    for interaction in profile.interaction_history
                ],
                "goals": [
                    {
                        "goal_id": goal.goal_id,
                        "description": goal.description,
                        "category": goal.category,
                        "created_at": goal.created_at.isoformat(),
                        "target_completion": goal.target_completion.isoformat() if goal.target_completion else None,
                        "current_progress": goal.current_progress,
                        "status": goal.status,
                        "related_tasks": goal.related_tasks,
                    }
                    for goal in profile.goals
                ],
                "expertise_level": profile.expertise_level,
                "preferred_domains": profile.preferred_domains,
                "privacy_level": profile.privacy_level,
                "notification_preferences": profile.notification_preferences,
                "metadata": profile.metadata,
                "is_active": profile.is_active,
            }

            file_path = self.storage_dir / f"{profile.user_id}.json"
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(profile_dict, f, indent=2, ensure_ascii=False)

            return True
        except Exception as e:
            logger.error("Error saving profile for user %s: %s", profile.user_id, e)
            return False

    async def load_profile(self, user_id: str) -> Optional[UserProfile]:
        try:
            file_path = self.storage_dir / f"{user_id}.json"
            if not file_path.exists():
                return None

            with open(file_path, "r", encoding="utf-8") as f:
                profile_dict = json.load(f)

            profile = UserProfile(
                user_id=profile_dict["user_id"],
                profile_type=UserProfileType(profile_dict["profile_type"]),
                created_at=datetime.fromisoformat(profile_dict["created_at"]),
                last_interaction=datetime.fromisoformat(profile_dict["last_interaction"]),
                name=profile_dict.get("name"),
                email=profile_dict.get("email"),
                expertise_level=profile_dict.get("expertise_level", "intermediate"),
                preferred_domains=profile_dict.get("preferred_domains", []),
                privacy_level=profile_dict.get("privacy_level", "balanced"),
                notification_preferences=profile_dict.get("notification_preferences", {}),
                metadata=profile_dict.get("metadata", {}),
                is_active=profile_dict.get("is_active", True),
            )

            for pref_dict in profile_dict.get("preferences", []):
                profile.preferences.append(UserPreference(
                    category=PreferenceCategory(pref_dict["category"]),
                    key=pref_dict["key"],
                    value=pref_dict["value"],
                    last_updated=datetime.fromisoformat(pref_dict["last_updated"]),
                    confidence=pref_dict.get("confidence", 1.0),
                ))

            for interaction_dict in profile_dict.get("interaction_history", []):
                profile.interaction_history.append(UserInteraction(
                    interaction_id=interaction_dict["interaction_id"],
                    interaction_type=InteractionType(interaction_dict["interaction_type"]),
                    timestamp=datetime.fromisoformat(interaction_dict["timestamp"]),
                    content=interaction_dict["content"],
                    context=interaction_dict["context"],
                    outcome=interaction_dict.get("outcome"),
                    satisfaction_score=interaction_dict.get("satisfaction_score"),
                ))

            for goal_dict in profile_dict.get("goals", []):
                profile.goals.append(UserGoal(
                    goal_id=goal_dict["goal_id"],
                    description=goal_dict["description"],
                    category=goal_dict["category"],
                    created_at=datetime.fromisoformat(goal_dict["created_at"]),
                    target_completion=datetime.fromisoformat(goal_dict["target_completion"]) if goal_dict.get("target_completion") else None,
                    current_progress=goal_dict.get("current_progress", 0.0),
                    status=goal_dict.get("status", "active"),
                    related_tasks=goal_dict.get("related_tasks", []),
                ))

            return profile
        except Exception as e:
            logger.error("Error loading profile for user %s: %s", user_id, e)
            return None

    async def delete_profile(self, user_id: str) -> bool:
        try:
            file_path = self.storage_dir / f"{user_id}.json"
            if file_path.exists():
                file_path.unlink()
                return True
            return False
        except Exception as e:
            logger.error("Error deleting profile for user %s: %s", user_id, e)
            return False

    async def update_profile(self, profile: UserProfile) -> bool:
        return await self.save_profile(profile)
