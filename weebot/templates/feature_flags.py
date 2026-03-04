"""
Feature Flag System for Template Engine.

Controls rollout of adaptive suggestions and other features.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Callable
from enum import Enum

_log = logging.getLogger(__name__)


class FeatureState(Enum):
    """Feature states."""
    DISABLED = "disabled"
    ENABLED = "enabled"
    SHADOW = "shadow"  # Record but don't show (testing)
    PERCENTAGE = "percentage"  # Gradual rollout


@dataclass
class FeatureConfig:
    """Configuration for a feature."""
    name: str
    state: FeatureState
    percentage: int = 0  # For PERCENTAGE state
    allowed_users: Optional[set] = None  # None = all users


class FeatureFlagManager:
    """
    Manages feature flags for template engine.
    
    Thread-safe (assumes single-process usage with async).
    """
    
    def __init__(self):
        self._flags: Dict[str, FeatureConfig] = {}
        self._user_overrides: Dict[str, Dict[str, bool]] = {}  # user -> {feature: enabled}
    
    def register(self, config: FeatureConfig):
        """Register a feature flag."""
        self._flags[config.name] = config
        _log.info(f"Registered feature flag: {config.name} = {config.state.value}")
    
    def is_enabled(
        self,
        feature_name: str,
        user_id: Optional[str] = None,
    ) -> bool:
        """
        Check if feature is enabled for user.
        
        Args:
            feature_name: Name of feature
            user_id: Optional user ID for personalized checks
            
        Returns:
            True if feature is enabled
        """
        config = self._flags.get(feature_name)
        if not config:
            return False
        
        # Check user override
        if user_id and user_id in self._user_overrides:
            override = self._user_overrides[user_id].get(feature_name)
            if override is not None:
                return override
        
        # Check allowed users list
        if config.allowed_users is not None:
            if user_id not in config.allowed_users:
                return False
        
        # Check state
        if config.state == FeatureState.DISABLED:
            return False
        elif config.state == FeatureState.ENABLED:
            return True
        elif config.state == FeatureState.SHADOW:
            return True  # Recording happens, UI doesn't show
        elif config.state == FeatureState.PERCENTAGE:
            if user_id is None:
                return False
            # Deterministic based on user_id hash
            import hashlib
            hash_val = int(hashlib.md5(f"{feature_name}:{user_id}".encode()).hexdigest(), 16)
            return (hash_val % 100) < config.percentage
        
        return False
    
    def enable_for_user(self, feature_name: str, user_id: str):
        """Manually enable feature for a user."""
        if user_id not in self._user_overrides:
            self._user_overrides[user_id] = {}
        self._user_overrides[user_id][feature_name] = True
    
    def disable_for_user(self, feature_name: str, user_id: str):
        """Manually disable feature for a user."""
        if user_id not in self._user_overrides:
            self._user_overrides[user_id] = {}
        self._user_overrides[user_id][feature_name] = False
    
    def get_feature_states(self) -> Dict[str, str]:
        """Get all feature states."""
        return {name: config.state.value for name, config in self._flags.items()}


# Global feature flag manager
_feature_flags = FeatureFlagManager()


def get_feature_flags() -> FeatureFlagManager:
    """Get global feature flag manager."""
    return _feature_flags


def register_default_features():
    """Register default feature flags."""
    _feature_flags.register(FeatureConfig(
        name="adaptive_suggestions",
        state=FeatureState.DISABLED,  # Opt-in by default
    ))
    
    _feature_flags.register(FeatureConfig(
        name="template_composition",
        state=FeatureState.ENABLED,
    ))
    
    _feature_flags.register(FeatureConfig(
        name="hot_reload",
        state=FeatureState.DISABLED,  # Dev only
    ))
    
    _feature_flags.register(FeatureConfig(
        name="execution_analytics",
        state=FeatureState.ENABLED,
    ))
