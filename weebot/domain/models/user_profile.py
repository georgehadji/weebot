"""
User Profile Models — Pure domain entities for user personalization.

This module contains ONLY the domain model classes. Storage adapters
live in infrastructure/, the manager lives in application/services/,
and the port interface lives in application/ports/.

Split from the original monolith (1268 lines) as part of architecture
remediation — see docs/architecture/REMEDIATION_PLAN.md step-6.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class UserProfileType(Enum):
    """Types of user profiles."""
    PERSONAL = "personal"
    PROFESSIONAL = "professional"
    ACADEMIC = "academic"
    BUSINESS = "business"
    EDUCATIONAL = "educational"
    CUSTOM = "custom"


class InteractionType(Enum):
    """Types of user interactions."""
    QUERY = "query"
    TASK_EXECUTION = "task_execution"
    RESEARCH_REQUEST = "research_request"
    FEEDBACK = "feedback"
    PREFERENCE_UPDATE = "preference_update"
    GOAL_SETTING = "goal_setting"


class PreferenceCategory(Enum):
    """Categories of user preferences."""
    COMMUNICATION_STYLE = "communication_style"
    CONTENT_PREFERENCES = "content_preferences"
    PRIVACY_SETTINGS = "privacy_settings"
    NOTIFICATION_PREFERENCES = "notification_preferences"
    INTERFACE_CUSTOMIZATION = "interface_customization"
    WORKFLOW_PREFERENCES = "workflow_preferences"
    TOOL_PREFERENCES = "tool_preferences"


@dataclass
class UserInteraction:
    """Record of a user interaction."""
    interaction_id: str
    interaction_type: InteractionType
    timestamp: datetime
    content: str
    context: Dict[str, Any]
    outcome: Optional[str] = None
    satisfaction_score: Optional[float] = None  # 0.0 to 1.0


@dataclass
class UserPreference:
    """A user preference setting."""
    category: PreferenceCategory
    key: str
    value: Any
    last_updated: datetime
    confidence: float = 1.0  # How confident we are (0.0 to 1.0)


@dataclass
class UserGoal:
    """A goal set by the user."""
    goal_id: str
    description: str
    category: str
    created_at: datetime
    target_completion: Optional[datetime] = None
    current_progress: float = 0.0  # 0.0 to 1.0
    status: str = "active"  # "active", "completed", "abandoned", "paused"
    related_tasks: List[str] = field(default_factory=list)


@dataclass
class UserProfile:
    """Complete user profile model."""
    user_id: str
    profile_type: UserProfileType
    created_at: datetime
    last_interaction: datetime
    name: Optional[str] = None
    email: Optional[str] = None
    preferences: List[UserPreference] = field(default_factory=list)
    interaction_history: List[UserInteraction] = field(default_factory=list)
    goals: List[UserGoal] = field(default_factory=list)
    expertise_level: str = "intermediate"
    preferred_domains: List[str] = field(default_factory=list)
    privacy_level: str = "balanced"  # "strict", "balanced", "relaxed"
    notification_preferences: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_active: bool = True


__all__ = [
    "UserProfileType",
    "InteractionType",
    "PreferenceCategory",
    "UserInteraction",
    "UserPreference",
    "UserGoal",
    "UserProfile",
]
