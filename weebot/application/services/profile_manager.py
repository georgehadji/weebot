"""User Profile Manager — application-layer orchestration for user profiles.

Extracted from the original domain/models/user_profile.py monolith as
part of architecture remediation (step-6).
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from weebot.application.ports.profile_storage_port import ProfileStoragePort
from weebot.domain.models.user_profile import (
    UserProfile,
    UserProfileType,
    PreferenceCategory,
    UserPreference,
    UserInteraction,
    UserGoal,
)

logger = logging.getLogger(__name__)


class UserProfileManager:
    """Manager for user profiles with advanced features."""

    def __init__(self, storage: ProfileStoragePort):
        self.storage = storage
        self._default_preferences = {
            PreferenceCategory.COMMUNICATION_STYLE: {
                "tone": "professional",
                "detail_level": "balanced",
                "response_speed_preference": "balanced",
            },
            PreferenceCategory.CONTENT_PREFERENCES: {
                "preferred_sources": ["academic", "news", "official"],
                "content_format": "mixed",
                "depth_preference": "balanced",
            },
            PreferenceCategory.PRIVACY_SETTINGS: {
                "data_sharing_consent": False,
                "personalization_level": "basic",
                "anonymization_preference": True,
            },
            PreferenceCategory.NOTIFICATION_PREFERENCES: {
                "email_notifications": True,
                "frequency": "asap",
                "preferred_hours": {"start": 9, "end": 17},
            },
            PreferenceCategory.INTERFACE_CUSTOMIZATION: {
                "theme": "light",
                "layout_preference": "standard",
            },
            PreferenceCategory.WORKFLOW_PREFERENCES: {
                "automation_level": "moderate",
                "review_before_execution": True,
            },
            PreferenceCategory.TOOL_PREFERENCES: {
                "default_tools": ["web_search", "calculator"],
                "tool_order_preference": "efficiency",
            },
        }

    async def create_profile(
        self,
        user_id: str,
        profile_type: UserProfileType = UserProfileType.CUSTOM,
        name: Optional[str] = None,
        email: Optional[str] = None,
        initial_preferences: Optional[Dict[PreferenceCategory, Dict[str, Any]]] = None,
    ) -> UserProfile:
        """Create a new user profile with default preferences."""
        profile = UserProfile(
            user_id=user_id,
            profile_type=profile_type,
            created_at=datetime.now(),
            last_interaction=datetime.now(),
            name=name,
            email=email,
        )

        for category, prefs in self._default_preferences.items():
            for key, value in prefs.items():
                profile.preferences.append(UserPreference(
                    category=category,
                    key=key,
                    value=value,
                    last_updated=datetime.now(),
                    confidence=0.8,
                ))

        if initial_preferences:
            for category, prefs in initial_preferences.items():
                for key, value in prefs.items():
                    pref_exists = False
                    for pref in profile.preferences:
                        if pref.category == category and pref.key == key:
                            pref.value = value
                            pref.last_updated = datetime.now()
                            pref_exists = True
                            break
                    if not pref_exists:
                        profile.preferences.append(UserPreference(
                            category=category,
                            key=key,
                            value=value,
                            last_updated=datetime.now(),
                            confidence=0.8,
                        ))

        await self.storage.save_profile(profile)
        return profile

    async def get_profile(self, user_id: str) -> Optional[UserProfile]:
        """Get a user profile."""
        return await self.storage.load_profile(user_id)

    async def update_profile(self, profile: UserProfile) -> bool:
        """Update a user profile."""
        profile.last_interaction = datetime.now()
        return await self.storage.update_profile(profile)

    async def add_interaction(self, user_id: str, interaction: UserInteraction) -> bool:
        """Add an interaction to a user's profile."""
        profile = await self.get_profile(user_id)
        if not profile:
            return False
        profile.interaction_history.append(interaction)
        if len(profile.interaction_history) > 1000:
            profile.interaction_history = profile.interaction_history[-1000:]
        return await self.update_profile(profile)

    async def update_preference(
        self,
        user_id: str,
        category: PreferenceCategory,
        key: str,
        value: Any,
        confidence: float = 1.0,
    ) -> bool:
        """Update a user preference."""
        profile = await self.get_profile(user_id)
        if not profile:
            return False

        for pref in profile.preferences:
            if pref.category == category and pref.key == key:
                pref.value = value
                pref.last_updated = datetime.now()
                pref.confidence = confidence
                return await self.update_profile(profile)

        profile.preferences.append(UserPreference(
            category=category,
            key=key,
            value=value,
            last_updated=datetime.now(),
            confidence=confidence,
        ))
        return await self.update_profile(profile)

    async def get_preference(self, user_id: str, category: PreferenceCategory, key: str) -> Optional[Any]:
        """Get a specific user preference."""
        profile = await self.get_profile(user_id)
        if not profile:
            return None
        for pref in profile.preferences:
            if pref.category == category and pref.key == key:
                return pref.value
        return None

    async def add_goal(self, user_id: str, goal: UserGoal) -> bool:
        """Add a goal to a user's profile."""
        profile = await self.get_profile(user_id)
        if not profile:
            return False
        profile.goals.append(goal)
        return await self.update_profile(profile)

    async def update_goal_progress(self, user_id: str, goal_id: str, progress: float) -> bool:
        """Update the progress of a specific goal."""
        profile = await self.get_profile(user_id)
        if not profile:
            return False
        for goal in profile.goals:
            if goal.goal_id == goal_id:
                goal.current_progress = max(0.0, min(1.0, progress))
                if goal.current_progress >= 1.0:
                    goal.status = "completed"
                return await self.update_profile(profile)
        return False

    async def infer_preferences_from_interactions(self, user_id: str) -> Dict[PreferenceCategory, Dict[str, Any]]:
        """Infer user preferences from interaction history."""
        profile = await self.get_profile(user_id)
        if not profile or not profile.interaction_history:
            return {}

        # Count interaction types
        type_counts: Dict[str, int] = {}
        for interaction in profile.interaction_history:
            t = interaction.interaction_type.value
            type_counts[t] = type_counts.get(t, 0) + 1

        inferred: Dict[PreferenceCategory, Dict[str, Any]] = {}
        if type_counts.get("research_request", 0) > type_counts.get("query", 0):
            inferred[PreferenceCategory.CONTENT_PREFERENCES] = {
                "depth_preference": "deep",
            }

        total_feedback = sum(
            1 for i in profile.interaction_history
            if i.interaction_type == InteractionType.FEEDBACK and i.satisfaction_score is not None
        )
        if total_feedback > 5:
            avg_satisfaction = sum(
                i.satisfaction_score for i in profile.interaction_history
                if i.interaction_type == InteractionType.FEEDBACK and i.satisfaction_score is not None
            ) / total_feedback
            inferred[PreferenceCategory.COMMUNICATION_STYLE] = {
                "effectiveness_score": avg_satisfaction,
            }

        return inferred

    def get_personalized_response_style(self, user_id: str) -> Dict[str, Any]:
        """Placeholder — would use stored preferences."""
        return {"tone": "professional", "detail_level": "balanced"}

    def get_user_expertise_domains(self, user_id: str) -> list:
        """Placeholder."""
        return []

    def calculate_user_affinity(self, user_id: str) -> float:
        """Placeholder affinity score."""
        return 0.5

    def get_privacy_settings(self, user_id: str) -> Dict[str, Any]:
        """Get privacy settings for a user (placeholder)."""
        return {
            "data_sharing_consent": False,
            "personalization_level": "basic",
            "anonymization_preference": True,
        }


# ---------------------------------------------------------------------------
# Filesystem profile management (named workspace profiles)
#
# Restored after the step-6 remediation overwrote this module: the CLI
# (`cli/commands/profile.py`) and tests import ``ProfileManager`` / ``Profile``
# from here.  Distinct from ``UserProfileManager`` above (user preferences) —
# this manages isolated ``~/.weebot/profiles/<name>/`` workspaces.
# ---------------------------------------------------------------------------

_PROFILES_ROOT = Path.home() / ".weebot" / "profiles"
_DEFAULT_PROFILE = "default"


@dataclass
class Profile:
    """A named profile with isolated configuration."""
    name: str
    path: Path
    created_at: str = ""


class ProfileManager:
    """Manage named profiles for isolated agent configuration.

    Profiles store their own config overrides, skill preferences, and
    memory/session search scope under ``~/.weebot/profiles/<name>/``.

    Args:
        profiles_root: Root directory for profiles. Defaults to
            ``~/.weebot/profiles/``.
    """

    def __init__(self, profiles_root: Optional[Path] = None) -> None:
        self._root = (profiles_root or _PROFILES_ROOT).resolve()

    # ── CRUD ───────────────────────────────────────────────────────

    def create(self, name: str, from_profile: Optional[str] = None) -> Profile:
        """Create a new profile.

        Args:
            name: Profile name (alphanumeric + hyphens/underscores).
            from_profile: Optional existing profile to copy from.

        Returns:
            The created Profile.

        Raises:
            ValueError: If the name is invalid or the profile already exists.
        """
        if not name or not name.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                f"Invalid profile name: {name!r}. "
                "Use letters, digits, hyphens, and underscores."
            )

        profile_path = self._root / name
        if profile_path.exists():
            raise ValueError(f"Profile '{name}' already exists.")

        profile_path.mkdir(parents=True, exist_ok=True)

        # Copy from existing profile if specified
        if from_profile:
            src = self._root / from_profile
            if src.exists() and src.is_dir():
                for item in src.iterdir():
                    if item.is_file():
                        shutil.copy2(str(item), str(profile_path / item.name))

        # Write profile metadata
        from datetime import timezone
        (profile_path / ".metadata").write_text(
            f"name: {name}\ncreated_at: {datetime.now(timezone.utc).isoformat()}\n",
            encoding="utf-8",
        )

        logger.info("Created profile '%s' at %s", name, profile_path)
        return Profile(name=name, path=profile_path)

    def get(self, name: str) -> Optional[Profile]:
        """Get a profile by name, or ``None`` if it does not exist."""
        profile_path = self._root / name
        if not profile_path.is_dir():
            return None

        created_at = ""
        meta_file = profile_path / ".metadata"
        if meta_file.exists():
            for line in meta_file.read_text(encoding="utf-8").split("\n"):
                if line.startswith("created_at:"):
                    created_at = line.split(":", 1)[1].strip()

        return Profile(name=name, path=profile_path, created_at=created_at)

    def list_profiles(self) -> list[Profile]:
        """List all available profiles."""
        if not self._root.is_dir():
            return []

        profiles = []
        for entry in sorted(self._root.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                profile = self.get(entry.name)
                if profile:
                    profiles.append(profile)
        return profiles

    def delete(self, name: str) -> bool:
        """Delete a profile and its directory.

        Returns ``True`` if deleted, ``False`` if it did not exist.
        Refuses to delete the ``default`` profile.
        """
        if name == _DEFAULT_PROFILE:
            raise ValueError("Cannot delete the default profile.")

        profile_path = self._root / name
        if not profile_path.is_dir():
            return False

        shutil.rmtree(str(profile_path))
        logger.info("Deleted profile '%s'", name)
        return True

    def switch(self, name: str) -> Optional[Profile]:
        """Switch to an existing profile, writing the active marker."""
        profile = self.get(name)
        if profile is None:
            return None

        self._root.parent.mkdir(parents=True, exist_ok=True)
        (self._root.parent / ".active_profile").write_text(name, encoding="utf-8")
        logger.info("Switched to profile '%s'", name)
        return profile

    @staticmethod
    def active_profile_name(profiles_root: Optional[Path] = None) -> str:
        """Return the currently active profile name (``default`` if unset)."""
        root = profiles_root or _PROFILES_ROOT
        marker = root.parent / ".active_profile"
        if marker.exists():
            return marker.read_text(encoding="utf-8").strip()
        return _DEFAULT_PROFILE

    def profile_path(self, name: str) -> Path:
        """Return the filesystem path for a profile's directory."""
        return self._root / name

    @property
    def profiles_root(self) -> Path:
        """Return the profiles root directory."""
        return self._root
