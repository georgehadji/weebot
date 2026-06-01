"""
User Profile Model for Weebot

This module provides capabilities for creating and managing user profiles
to enable personalized experiences and tailored interactions.
"""
from __future__ import annotations

import asyncio
import json
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol
import logging
from abc import ABC, abstractmethod
import uuid
from pathlib import Path


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
    context: Dict[str, Any]  # Additional context about the interaction
    outcome: Optional[str] = None  # Result of the interaction
    satisfaction_score: Optional[float] = None  # 0.0 to 1.0


@dataclass
class UserPreference:
    """A user preference setting."""
    category: PreferenceCategory
    key: str
    value: Any
    last_updated: datetime
    confidence: float = 1.0  # How confident we are in this preference (0.0 to 1.0)


@dataclass
class UserGoal:
    """A goal set by the user."""
    goal_id: str
    description: str
    category: str  # e.g., "research", "productivity", "learning"
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
    expertise_level: str = "intermediate"  # "beginner", "intermediate", "advanced", "expert"
    preferred_domains: List[str] = field(default_factory=list)  # e.g., ["technology", "science", "business"]
    privacy_level: str = "balanced"  # "strict", "balanced", "relaxed"
    notification_preferences: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_active: bool = True


class UserProfileStorage(ABC):
    """Abstract base class for user profile storage."""
    
    @abstractmethod
    async def save_profile(self, profile: UserProfile) -> bool:
        """Save a user profile."""
        pass
    
    @abstractmethod
    async def load_profile(self, user_id: str) -> Optional[UserProfile]:
        """Load a user profile by user ID."""
        pass
    
    @abstractmethod
    async def delete_profile(self, user_id: str) -> bool:
        """Delete a user profile."""
        pass
    
    @abstractmethod
    async def update_profile(self, profile: UserProfile) -> bool:
        """Update an existing user profile."""
        pass


class InMemoryUserProfileStorage(UserProfileStorage):
    """In-memory storage for user profiles."""
    
    def __init__(self):
        self.profiles: Dict[str, UserProfile] = {}
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    async def save_profile(self, profile: UserProfile) -> bool:
        """Save a user profile to memory."""
        try:
            self.profiles[profile.user_id] = profile
            self.logger.debug(f"Saved profile for user {profile.user_id}")
            return True
        except Exception as e:
            self.logger.error(f"Error saving profile for user {profile.user_id}: {e}")
            return False
    
    async def load_profile(self, user_id: str) -> Optional[UserProfile]:
        """Load a user profile from memory."""
        try:
            profile = self.profiles.get(user_id)
            if profile:
                self.logger.debug(f"Loaded profile for user {user_id}")
            else:
                self.logger.debug(f"No profile found for user {user_id}")
            return profile
        except Exception as e:
            self.logger.error(f"Error loading profile for user {user_id}: {e}")
            return None
    
    async def delete_profile(self, user_id: str) -> bool:
        """Delete a user profile from memory."""
        try:
            if user_id in self.profiles:
                del self.profiles[user_id]
                self.logger.debug(f"Deleted profile for user {user_id}")
                return True
            else:
                self.logger.warning(f"Attempted to delete non-existent profile for user {user_id}")
                return False
        except Exception as e:
            self.logger.error(f"Error deleting profile for user {user_id}: {e}")
            return False
    
    async def update_profile(self, profile: UserProfile) -> bool:
        """Update an existing user profile."""
        return await self.save_profile(profile)


class FileUserProfileStorage(UserProfileStorage):
    """File-based storage for user profiles."""
    
    def __init__(self, storage_dir: str = "./user_profiles"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(exist_ok=True)
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    async def save_profile(self, profile: UserProfile) -> bool:
        """Save a user profile to file."""
        try:
            # Create a serializable version of the profile
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
                        "confidence": pref.confidence
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
                        "satisfaction_score": interaction.satisfaction_score
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
                        "related_tasks": goal.related_tasks
                    }
                    for goal in profile.goals
                ],
                "expertise_level": profile.expertise_level,
                "preferred_domains": profile.preferred_domains,
                "privacy_level": profile.privacy_level,
                "notification_preferences": profile.notification_preferences,
                "metadata": profile.metadata,
                "is_active": profile.is_active
            }
            
            # Save to file
            file_path = self.storage_dir / f"{profile.user_id}.json"
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(profile_dict, f, indent=2, ensure_ascii=False)
            
            self.logger.debug(f"Saved profile for user {profile.user_id} to {file_path}")
            return True
        except Exception as e:
            self.logger.error(f"Error saving profile for user {profile.user_id}: {e}")
            return False
    
    async def load_profile(self, user_id: str) -> Optional[UserProfile]:
        """Load a user profile from file."""
        try:
            file_path = self.storage_dir / f"{user_id}.json"
            if not file_path.exists():
                self.logger.debug(f"No profile file found for user {user_id}")
                return None
            
            with open(file_path, 'r', encoding='utf-8') as f:
                profile_dict = json.load(f)
            
            # Reconstruct the profile object
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
                is_active=profile_dict.get("is_active", True)
            )
            
            # Reconstruct preferences
            for pref_dict in profile_dict.get("preferences", []):
                profile.preferences.append(UserPreference(
                    category=PreferenceCategory(pref_dict["category"]),
                    key=pref_dict["key"],
                    value=pref_dict["value"],
                    last_updated=datetime.fromisoformat(pref_dict["last_updated"]),
                    confidence=pref_dict.get("confidence", 1.0)
                ))
            
            # Reconstruct interaction history
            for interaction_dict in profile_dict.get("interaction_history", []):
                profile.interaction_history.append(UserInteraction(
                    interaction_id=interaction_dict["interaction_id"],
                    interaction_type=InteractionType(interaction_dict["interaction_type"]),
                    timestamp=datetime.fromisoformat(interaction_dict["timestamp"]),
                    content=interaction_dict["content"],
                    context=interaction_dict["context"],
                    outcome=interaction_dict.get("outcome"),
                    satisfaction_score=interaction_dict.get("satisfaction_score")
                ))
            
            # Reconstruct goals
            for goal_dict in profile_dict.get("goals", []):
                profile.goals.append(UserGoal(
                    goal_id=goal_dict["goal_id"],
                    description=goal_dict["description"],
                    category=goal_dict["category"],
                    created_at=datetime.fromisoformat(goal_dict["created_at"]),
                    target_completion=datetime.fromisoformat(goal_dict["target_completion"]) if goal_dict["target_completion"] else None,
                    current_progress=goal_dict.get("current_progress", 0.0),
                    status=goal_dict.get("status", "active"),
                    related_tasks=goal_dict.get("related_tasks", [])
                ))
            
            self.logger.debug(f"Loaded profile for user {user_id} from {file_path}")
            return profile
        except Exception as e:
            self.logger.error(f"Error loading profile for user {user_id}: {e}")
            return None
    
    async def delete_profile(self, user_id: str) -> bool:
        """Delete a user profile from file."""
        try:
            file_path = self.storage_dir / f"{user_id}.json"
            if file_path.exists():
                file_path.unlink()
                self.logger.debug(f"Deleted profile file for user {user_id}")
                return True
            else:
                self.logger.warning(f"Attempted to delete non-existent profile file for user {user_id}")
                return False
        except Exception as e:
            self.logger.error(f"Error deleting profile for user {user_id}: {e}")
            return False
    
    async def update_profile(self, profile: UserProfile) -> bool:
        """Update an existing user profile."""
        return await self.save_profile(profile)


class UserProfileManager:
    """Manager for user profiles with advanced features."""
    
    def __init__(self, storage: UserProfileStorage):
        self.storage = storage
        self.logger = logging.getLogger(f"{__name__}.UserProfileManager")
        self._default_preferences = {
            PreferenceCategory.COMMUNICATION_STYLE: {
                "tone": "professional",
                "detail_level": "balanced",  # "brief", "balanced", "detailed"
                "response_speed_preference": "balanced"  # "fast", "balanced", "thorough"
            },
            PreferenceCategory.CONTENT_PREFERENCES: {
                "preferred_sources": ["academic", "news", "official"],
                "content_format": "mixed",  # "text", "lists", "structured", "mixed"
                "depth_preference": "balanced"  # "shallow", "balanced", "deep"
            },
            PreferenceCategory.PRIVACY_SETTINGS: {
                "data_sharing_consent": False,
                "personalization_level": "basic",  # "none", "basic", "advanced"
                "anonymization_preference": True
            },
            PreferenceCategory.NOTIFICATION_PREFERENCES: {
                "email_notifications": True,
                "frequency": "asap",  # "asap", "daily_digest", "weekly_summary"
                "preferred_hours": {"start": 9, "end": 17}
            },
            PreferenceCategory.INTERFACE_CUSTOMIZATION: {
                "theme": "light",  # "light", "dark", "auto"
                "layout_preference": "standard"  # "compact", "standard", "spacious"
            },
            PreferenceCategory.WORKFLOW_PREFERENCES: {
                "automation_level": "moderate",  # "minimal", "moderate", "maximum"
                "review_before_execution": True
            },
            PreferenceCategory.TOOL_PREFERENCES: {
                "default_tools": ["web_search", "calculator"],
                "tool_order_preference": "efficiency"
            }
        }
    
    async def create_profile(
        self,
        user_id: str,
        profile_type: UserProfileType = UserProfileType.CUSTOM,
        name: Optional[str] = None,
        email: Optional[str] = None,
        initial_preferences: Optional[Dict[PreferenceCategory, Dict[str, Any]]] = None
    ) -> UserProfile:
        """Create a new user profile."""
        # Create default profile
        profile = UserProfile(
            user_id=user_id,
            profile_type=profile_type,
            created_at=datetime.now(),
            last_interaction=datetime.now(),
            name=name,
            email=email
        )
        
        # Set default preferences
        for category, prefs in self._default_preferences.items():
            for key, value in prefs.items():
                profile.preferences.append(UserPreference(
                    category=category,
                    key=key,
                    value=value,
                    last_updated=datetime.now(),
                    confidence=0.8  # Default confidence for initial preferences
                ))
        
        # Override with initial preferences if provided
        if initial_preferences:
            for category, prefs in initial_preferences.items():
                for key, value in prefs.items():
                    # Update or add preference
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
                            confidence=0.8
                        ))
        
        # Save the profile
        success = await self.storage.save_profile(profile)
        if success:
            self.logger.info(f"Created profile for user {user_id}")
        else:
            self.logger.error(f"Failed to create profile for user {user_id}")
        
        return profile
    
    async def get_profile(self, user_id: str) -> Optional[UserProfile]:
        """Get a user profile."""
        profile = await self.storage.load_profile(user_id)
        if profile:
            self.logger.debug(f"Retrieved profile for user {user_id}")
        else:
            self.logger.debug(f"No profile found for user {user_id}")
        return profile
    
    async def update_profile(self, profile: UserProfile) -> bool:
        """Update a user profile."""
        profile.last_interaction = datetime.now()
        success = await self.storage.update_profile(profile)
        if success:
            self.logger.info(f"Updated profile for user {profile.user_id}")
        else:
            self.logger.error(f"Failed to update profile for user {profile.user_id}")
        return success
    
    async def add_interaction(self, user_id: str, interaction: UserInteraction) -> bool:
        """Add an interaction to a user's profile."""
        profile = await self.get_profile(user_id)
        if not profile:
            self.logger.warning(f"Cannot add interaction for non-existent user {user_id}")
            return False
        
        profile.interaction_history.append(interaction)
        
        # Keep interaction history to a reasonable size
        if len(profile.interaction_history) > 1000:
            profile.interaction_history = profile.interaction_history[-1000:]
        
        return await self.update_profile(profile)
    
    async def update_preference(
        self, 
        user_id: str, 
        category: PreferenceCategory, 
        key: str, 
        value: Any,
        confidence: float = 1.0
    ) -> bool:
        """Update a user preference."""
        profile = await self.get_profile(user_id)
        if not profile:
            self.logger.warning(f"Cannot update preference for non-existent user {user_id}")
            return False
        
        # Check if preference already exists
        pref_exists = False
        for pref in profile.preferences:
            if pref.category == category and pref.key == key:
                pref.value = value
                pref.last_updated = datetime.now()
                pref.confidence = confidence
                pref_exists = True
                break
        
        # If preference doesn't exist, add it
        if not pref_exists:
            profile.preferences.append(UserPreference(
                category=category,
                key=key,
                value=value,
                last_updated=datetime.now(),
                confidence=confidence
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
            self.logger.warning(f"Cannot add goal for non-existent user {user_id}")
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
                goal.current_progress = max(0.0, min(1.0, progress))  # Clamp between 0 and 1
                if goal.current_progress >= 1.0:
                    goal.status = "completed"
                return await self.update_profile(profile)
        
        return False
    
    async def infer_preferences_from_interactions(self, user_id: str) -> Dict[PreferenceCategory, Dict[str, Any]]:
        """Infer user preferences from their interaction history."""
        profile = await self.get_profile(user_id)
        if not profile or not profile.interaction_history:
            return {}
        
        inferred_prefs = {}
        
        # Analyze interaction patterns
        interactions = profile.interaction_history[-50:]  # Look at recent interactions
        
        # Infer communication style preferences
        if not interactions:
            return {}
        
        # Count interaction types
        interaction_counts = {}
        for interaction in interactions:
            itype = interaction.interaction_type.value
            interaction_counts[itype] = interaction_counts.get(itype, 0) + 1
        
        # Infer based on most common interaction type
        if interaction_counts:
            most_common_type = max(interaction_counts, key=interaction_counts.get)
            
            if most_common_type in ["research_request", "query"]:
                # User prefers detailed, research-oriented interactions
                if PreferenceCategory.CONTENT_PREFERENCES not in inferred_prefs:
                    inferred_prefs[PreferenceCategory.CONTENT_PREFERENCES] = {}
                inferred_prefs[PreferenceCategory.CONTENT_PREFERENCES]["depth_preference"] = "deep"
                inferred_prefs[PreferenceCategory.CONTENT_PREFERENCES]["content_format"] = "structured"
            
            elif most_common_type == "task_execution":
                # User prefers efficient, task-oriented interactions
                if PreferenceCategory.COMMUNICATION_STYLE not in inferred_prefs:
                    inferred_prefs[PreferenceCategory.COMMUNICATION_STYLE] = {}
                inferred_prefs[PreferenceCategory.COMMUNICATION_STYLE]["detail_level"] = "brief"
                inferred_prefs[PreferenceCategory.COMMUNICATION_STYLE]["response_speed_preference"] = "fast"
        
        # Analyze satisfaction scores if available
        satisfaction_scores = [i.satisfaction_score for i in interactions if i.satisfaction_score is not None]
        if satisfaction_scores:
            avg_satisfaction = sum(satisfaction_scores) / len(satisfaction_scores)
            
            # If satisfaction is high, maintain current preferences
            # If satisfaction is low, consider adjusting preferences
            if avg_satisfaction < 0.5:
                # User seems dissatisfied, might need different approach
                if PreferenceCategory.COMMUNICATION_STYLE not in inferred_prefs:
                    inferred_prefs[PreferenceCategory.COMMUNICATION_STYLE] = {}
                inferred_prefs[PreferenceCategory.COMMUNICATION_STYLE]["tone"] = "more_courteous"
        
        return inferred_prefs
    
    async def get_personalized_response_style(self, user_id: str) -> Dict[str, Any]:
        """Get personalized response style settings for a user."""
        profile = await self.get_profile(user_id)
        if not profile:
            # Return default settings
            return {
                "tone": "professional",
                "detail_level": "balanced",
                "response_speed_preference": "balanced",
                "content_format": "mixed",
                "depth_preference": "balanced"
            }
        
        # Extract relevant preferences
        response_style = {}
        
        for pref in profile.preferences:
            if pref.category == PreferenceCategory.COMMUNICATION_STYLE:
                response_style[pref.key] = pref.value
            elif pref.category == PreferenceCategory.CONTENT_PREFERENCES:
                response_style[pref.key] = pref.value
        
        # Fill in defaults for missing preferences
        defaults = {
            "tone": "professional",
            "detail_level": "balanced",
            "response_speed_preference": "balanced",
            "content_format": "mixed",
            "depth_preference": "balanced"
        }
        
        for key, default_value in defaults.items():
            if key not in response_style:
                response_style[key] = default_value
        
        return response_style
    
    async def get_user_expertise_domains(self, user_id: str) -> List[str]:
        """Get domains where the user has expressed expertise."""
        profile = await self.get_profile(user_id)
        if not profile:
            return []
        
        # For now, return preferred domains
        # In a more sophisticated implementation, this would analyze
        # the user's queries and interactions to identify expertise areas
        return profile.preferred_domains
    
    async def calculate_user_affinity(self, user_id: str, content_domain: str) -> float:
        """Calculate how much a user is interested in a particular content domain."""
        profile = await self.get_profile(user_id)
        if not profile:
            return 0.5  # Neutral affinity
        
        # Check if domain is in preferred domains
        if content_domain in profile.preferred_domains:
            return 0.8  # High affinity
        
        # Analyze interaction history for domain-related queries
        domain_related_interactions = 0
        total_interactions = len(profile.interaction_history)
        
        if total_interactions == 0:
            return 0.5  # Neutral if no history
        
        for interaction in profile.interaction_history[-20:]:  # Check recent interactions
            content_lower = interaction.content.lower()
            if content_domain.lower() in content_lower:
                domain_related_interactions += 1
        
        # Calculate affinity based on proportion of domain-related interactions
        affinity = domain_related_interactions / min(20, total_interactions)
        
        # Boost if user has set domain as preferred
        if content_domain in profile.preferred_domains:
            affinity = min(1.0, affinity * 1.5)
        
        return affinity
    
    async def get_privacy_settings(self, user_id: str) -> Dict[str, Any]:
        """Get privacy settings for a user."""
        profile = await self.get_profile(user_id)
        if not profile:
            return {
                "data_sharing_consent": False,
                "personalization_level": "basic",
                "anonymization_preference": True
            }
        
        privacy_settings = {}
        for pref in profile.preferences:
            if pref.category == PreferenceCategory.PRIVACY_SETTINGS:
                privacy_settings[pref.key] = pref.value
        
        # Fill in defaults
        defaults = {
            "data_sharing_consent": False,
            "personalization_level": "basic",
            "anonymization_preference": True
        }
        
        for key, default_value in defaults.items():
            if key not in privacy_settings:
                privacy_settings[key] = default_value
        
        return privacy_settings


class UserProfileTool:
    """Tool for managing user profiles."""
    
    def __init__(self, profile_manager: UserProfileManager):
        self.profile_manager = profile_manager
        self.logger = logging.getLogger(f"{__name__}.UserProfileTool")
    
    async def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        """Get a user's profile information."""
        try:
            profile = await self.profile_manager.get_profile(user_id)
            if profile:
                return {
                    "user_id": profile.user_id,
                    "name": profile.name,
                    "email": profile.email,
                    "profile_type": profile.profile_type.value,
                    "created_at": profile.created_at.isoformat(),
                    "last_interaction": profile.last_interaction.isoformat(),
                    "expertise_level": profile.expertise_level,
                    "preferred_domains": profile.preferred_domains,
                    "is_active": profile.is_active,
                    "interaction_count": len(profile.interaction_history),
                    "goal_count": len(profile.goals)
                }
            else:
                return {"error": f"No profile found for user {user_id}"}
        except Exception as e:
            self.logger.error(f"Error getting user profile: {e}")
            return {"error": f"Error getting user profile: {str(e)}"}
    
    async def update_user_preference(self, user_id: str, category: str, key: str, value: Any) -> Dict[str, Any]:
        """Update a user preference."""
        try:
            # Convert string category to enum
            try:
                pref_category = PreferenceCategory(category.lower())
            except ValueError:
                return {"error": f"Invalid preference category: {category}"}
            
            success = await self.profile_manager.update_preference(user_id, pref_category, key, value)
            if success:
                return {
                    "success": True,
                    "message": f"Updated preference {category}.{key} for user {user_id}"
                }
            else:
                return {"error": f"Failed to update preference for user {user_id}"}
        except Exception as e:
            self.logger.error(f"Error updating user preference: {e}")
            return {"error": f"Error updating user preference: {str(e)}"}
    
    async def get_user_preferences(self, user_id: str) -> Dict[str, Any]:
        """Get all user preferences."""
        try:
            profile = await self.profile_manager.get_profile(user_id)
            if not profile:
                return {"error": f"No profile found for user {user_id}"}
            
            preferences = {}
            for pref in profile.preferences:
                category = pref.category.value
                if category not in preferences:
                    preferences[category] = {}
                preferences[category][pref.key] = {
                    "value": pref.value,
                    "last_updated": pref.last_updated.isoformat(),
                    "confidence": pref.confidence
                }
            
            return {
                "user_id": user_id,
                "preferences": preferences
            }
        except Exception as e:
            self.logger.error(f"Error getting user preferences: {e}")
            return {"error": f"Error getting user preferences: {str(e)}"}
    
    async def get_personalized_settings(self, user_id: str) -> Dict[str, Any]:
        """Get personalized settings for a user."""
        try:
            response_style = await self.profile_manager.get_personalized_response_style(user_id)
            privacy_settings = await self.profile_manager.get_privacy_settings(user_id)
            expertise_domains = await self.profile_manager.get_user_expertise_domains(user_id)
            
            return {
                "user_id": user_id,
                "response_style": response_style,
                "privacy_settings": privacy_settings,
                "expertise_domains": expertise_domains
            }
        except Exception as e:
            self.logger.error(f"Error getting personalized settings: {e}")
            return {"error": f"Error getting personalized settings: {str(e)}"}
    
    def to_param(self) -> Dict[str, Any]:
        """Convert to parameter format for tool registration."""
        return {
            "type": "function",
            "function": {
                "name": "user_profile_tool",
                "description": "Manage user profiles and preferences",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["get_profile", "get_preferences", "update_preference", "get_personalized_settings"],
                            "description": "Action to perform"
                        },
                        "user_id": {
                            "type": "string",
                            "description": "ID of the user"
                        },
                        "category": {
                            "type": "string",
                            "description": "Preference category (for update action)"
                        },
                        "key": {
                            "type": "string",
                            "description": "Preference key (for update action)"
                        },
                        "value": {
                            "type": "any",
                            "description": "Preference value (for update action)"
                        }
                    },
                    "required": ["action", "user_id"]
                }
            }
        }


# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def example():
        # Create a profile manager with in-memory storage
        storage = InMemoryUserProfileStorage()
        profile_manager = UserProfileManager(storage)
        
        print("Creating user profile...")
        
        # Create a sample user profile
        user_profile = await profile_manager.create_profile(
            user_id="user_123",
            profile_type=UserProfileType.PROFESSIONAL,
            name="John Doe",
            email="john.doe@example.com",
            initial_preferences={
                PreferenceCategory.COMMUNICATION_STYLE: {
                    "tone": "casual",
                    "detail_level": "detailed"
                },
                PreferenceCategory.CONTENT_PREFERENCES: {
                    "preferred_sources": ["academic", "official"],
                    "depth_preference": "deep"
                }
            }
        )
        
        print(f"Created profile for user: {user_profile.name}")
        print(f"Profile type: {user_profile.profile_type.value}")
        print(f"Preferred domains: {user_profile.preferred_domains}")
        
        # Add an interaction
        interaction = UserInteraction(
            interaction_id="int_001",
            interaction_type=InteractionType.QUERY,
            timestamp=datetime.now(),
            content="Research the latest developments in AI",
            context={"topic": "AI", "depth": "comprehensive"},
            satisfaction_score=0.9
        )
        
        success = await profile_manager.add_interaction("user_123", interaction)
        print(f"Added interaction: {success}")
        
        # Update a preference
        success = await profile_manager.update_preference(
            user_id="user_123",
            category=PreferenceCategory.NOTIFICATION_PREFERENCES,
            key="email_notifications",
            value=False,
            confidence=1.0
        )
        print(f"Updated preference: {success}")
        
        # Get personalized settings
        settings = await profile_manager.get_personalized_response_style("user_123")
        print(f"Personalized settings: {settings}")
        
        # Calculate affinity for a domain
        affinity = await profile_manager.calculate_user_affinity("user_123", "AI")
        print(f"Affinity for AI: {affinity:.2f}")
        
        # Get privacy settings
        privacy = await profile_manager.get_privacy_settings("user_123")
        print(f"Privacy settings: {privacy}")
        
        print("\nExample completed successfully!")
    
    asyncio.run(example())