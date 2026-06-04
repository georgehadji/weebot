"""User Profile Manager — application-layer orchestration for user profiles.

Extracted from the original domain/models/user_profile.py monolith as
part of architecture remediation (step-6).
"""
from __future__ import annotations

import logging
from datetime import datetime
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
