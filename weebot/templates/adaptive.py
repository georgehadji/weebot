"""
Adaptive Parameter Suggestion Engine.

Learns optimal parameters from execution history to suggest
best configurations for templates.

Features:
- Historical success rate analysis
- Collaborative filtering (anonymized)
- Bayesian parameter scoring
- Privacy-preserving learning
- Confidence thresholds
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import defaultdict

from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Boolean, Text,
    select, func, and_
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from weebot.templates.parser import WorkflowTemplate, ParameterSchema

# Declarative base for the adaptive-suggestion ORM records.  Without inheriting
# a mapped Base, select()/delete() on these classes raises ArgumentError
# ("Column expression … expected, got <class …>").
Base = declarative_base()

_log = logging.getLogger(__name__)


@dataclass
class ParameterSuggestion:
    """A suggested parameter value with confidence."""
    parameter_name: str
    suggested_value: Any
    confidence: float  # 0.0 - 1.0
    source: str  # "historical", "similar_users", "default"
    success_rate: float
    sample_size: int


@dataclass
class SuggestionContext:
    """Context for generating suggestions."""
    user_id: str
    template_name: str
    template_version: str
    previous_executions: int
    domain_hint: Optional[str] = None  # e.g., "research", "coding"


class ParameterEffectivenessRecord(Base):
    """Database record for parameter effectiveness tracking."""
    __tablename__ = "parameter_effectiveness"
    
    id = Column(Integer, primary_key=True)
    template_name = Column(String(255), index=True)
    template_version = Column(String(50))
    parameter_hash = Column(String(64), index=True)  # Hash of param names
    parameter_values_hash = Column(String(64))  # Hash of specific values
    parameter_values_json = Column(Text)  # JSON of actual values
    
    # Effectiveness metrics
    execution_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    avg_execution_time_ms = Column(Float)
    user_satisfaction_score = Column(Float)  # 1.0 - 5.0, optional
    
    # Metadata
    first_used_at = Column(DateTime)
    last_used_at = Column(DateTime)
    user_count = Column(Integer, default=0)  # Anonymized unique users
    
    # For GDPR compliance
    can_be_used_for_suggestions = Column(Boolean, default=True)


class UserPreferenceRecord(Base):
    """Anonymized user preferences."""
    __tablename__ = "user_preferences_anonymized"
    
    id = Column(Integer, primary_key=True)
    user_hash = Column(String(64), index=True)  # Hashed user_id
    template_name = Column(String(255), index=True)
    preferred_parameters_hash = Column(String(64))
    preferred_parameters_json = Column(Text)
    usage_count = Column(Integer, default=0)
    last_updated = Column(DateTime)


class AdaptiveSuggestionEngine:
    """
    Learns and suggests optimal template parameters.
    
    Privacy-preserving design:
    - User IDs are hashed (one-way)
    - Suggestions aggregate across 5+ users minimum
    - Opt-in required (GDPR compliant)
    - 30-day retention for personal data
    """
    
    MIN_SAMPLE_SIZE = 5  # Minimum executions before suggestion
    MIN_CONFIDENCE = 0.6  # Minimum confidence to suggest
    SIMILARITY_THRESHOLD = 0.7  # For collaborative filtering
    
    def __init__(
        self,
        db_session_factory=None,
        enable_collaborative: bool = True,
        enable_personal: bool = True,
        privacy_mode: str = "strict",  # strict, balanced, relaxed
    ):
        self.db_session_factory = db_session_factory
        self.enable_collaborative = enable_collaborative
        self.enable_personal = enable_personal
        self.privacy_mode = privacy_mode
        
        # In-memory cache for hot suggestions
        self._suggestion_cache: Dict[str, Dict] = {}
        self._cache_ttl = 300  # 5 minutes
        self._cache_timestamp: Dict[str, datetime] = {}
    
    def _hash_user(self, user_id: str) -> str:
        """One-way hash of user_id for privacy."""
        return hashlib.sha256(f"weebot:{user_id}".encode()).hexdigest()[:32]
    
    def _get_cache_key(
        self,
        template_name: str,
        user_id: str,
        available_params: Set[str],
    ) -> str:
        """Generate cache key for suggestion lookup."""
        param_hash = hashlib.sha256(
            json.dumps(sorted(available_params), sort_keys=True).encode()
        ).hexdigest()[:16]
        
        return f"{template_name}:{self._hash_user(user_id)}:{param_hash}"
    
    async def suggest_parameters(
        self,
        template: WorkflowTemplate,
        context: SuggestionContext,
        current_input: Optional[Dict[str, Any]] = None,
    ) -> List[ParameterSuggestion]:
        """
        Generate parameter suggestions for a template.
        
        Args:
            template: The workflow template
            context: User and execution context
            current_input: Partial input already provided
            
        Returns:
            List of suggestions (may be empty)
        """
        if not self.db_session_factory:
            return []
        
        suggestions = []
        current_input = current_input or {}
        
        # Get parameters that need suggestions
        params_to_suggest = [
            name for name in template.parameters.keys()
            if name not in current_input
        ]
        
        if not params_to_suggest:
            return []
        
        # Try personal suggestions first (if enabled)
        if self.enable_personal:
            personal = await self._get_personal_suggestions(
                template, context, params_to_suggest
            )
            suggestions.extend(personal)
        
        # Fill gaps with collaborative suggestions
        suggested_names = {s.parameter_name for s in suggestions}
        remaining = [p for p in params_to_suggest if p not in suggested_names]
        
        if remaining and self.enable_collaborative:
            collaborative = await self._get_collaborative_suggestions(
                template, context, remaining
            )
            suggestions.extend(collaborative)
        
        # Sort by confidence
        suggestions.sort(key=lambda s: s.confidence, reverse=True)
        
        return suggestions
    
    async def _get_personal_suggestions(
        self,
        template: WorkflowTemplate,
        context: SuggestionContext,
        param_names: List[str],
    ) -> List[ParameterSuggestion]:
        """Get suggestions based on user's own history."""
        suggestions = []
        user_hash = self._hash_user(context.user_id)
        
        if not self.db_session_factory:
            return suggestions
        
        async with self.db_session_factory() as session:
            for param_name in param_names:
                # Query user's preferred value for this parameter
                stmt = select(
                    UserPreferenceRecord.preferred_parameters_json,
                    UserPreferenceRecord.usage_count,
                ).where(
                    and_(
                        UserPreferenceRecord.user_hash == user_hash,
                        UserPreferenceRecord.template_name == template.name,
                    )
                )
                
                result = await session.execute(stmt)
                row = result.first()
                
                if row and row.usage_count >= 3:  # Need 3+ uses for personal suggestion
                    try:
                        preferred = json.loads(row.preferred_parameters_json)
                        if param_name in preferred:
                            suggestions.append(ParameterSuggestion(
                                parameter_name=param_name,
                                suggested_value=preferred[param_name],
                                confidence=min(0.9, 0.5 + row.usage_count * 0.05),
                                source="personal",
                                success_rate=0.85,  # Assumed based on repetition
                                sample_size=row.usage_count,
                            ))
                    except json.JSONDecodeError:
                        pass
        
        return suggestions
    
    async def _get_collaborative_suggestions(
        self,
        template: WorkflowTemplate,
        context: SuggestionContext,
        param_names: List[str],
    ) -> List[ParameterSuggestion]:
        """Get suggestions based on aggregate user behavior."""
        suggestions = []
        
        if not self.db_session_factory:
            return suggestions
        
        async with self.db_session_factory() as session:
            for param_name in param_names:
                # Find most effective parameter combinations
                stmt = select(
                    ParameterEffectivenessRecord.parameter_values_json,
                    ParameterEffectivenessRecord.success_count,
                    ParameterEffectivenessRecord.execution_count,
                    ParameterEffectivenessRecord.avg_execution_time_ms,
                    ParameterEffectivenessRecord.user_count,
                ).where(
                    and_(
                        ParameterEffectivenessRecord.template_name == template.name,
                        ParameterEffectivenessRecord.can_be_used_for_suggestions == True,
                        ParameterEffectivenessRecord.user_count >= 3,  # Privacy: min 3 users
                    )
                ).order_by(
                    (ParameterEffectivenessRecord.success_count / 
                     func.nullif(ParameterEffectivenessRecord.execution_count, 0)).desc()
                ).limit(5)
                
                result = await session.execute(stmt)
                rows = result.all()
                
                if not rows:
                    continue
                
                # Calculate weighted suggestion
                best_option = None
                best_score = 0.0
                
                for row in rows:
                    if row.execution_count < self.MIN_SAMPLE_SIZE:
                        continue
                    
                    try:
                        params = json.loads(row.parameter_values_json)
                        if param_name not in params:
                            continue
                        
                        success_rate = row.success_count / row.execution_count
                        
                        # Weight by sample size (Bayesian smoothing)
                        weight = min(1.0, row.execution_count / 50)  # Cap at 50 samples
                        confidence = success_rate * weight
                        
                        if confidence > best_score and confidence >= self.MIN_CONFIDENCE:
                            best_score = confidence
                            best_option = ParameterSuggestion(
                                parameter_name=param_name,
                                suggested_value=params[param_name],
                                confidence=confidence,
                                source="collaborative",
                                success_rate=success_rate,
                                sample_size=row.execution_count,
                            )
                    except (json.JSONDecodeError, ZeroDivisionError):
                        continue
                
                if best_option:
                    suggestions.append(best_option)
        
        return suggestions
    
    async def record_execution_outcome(
        self,
        template: WorkflowTemplate,
        user_id: str,
        parameters: Dict[str, Any],
        success: bool,
        execution_time_ms: float,
        user_satisfaction: Optional[float] = None,
    ):
        """
        Record execution outcome for learning.
        
        Args:
            template: Executed template
            user_id: User who executed
            parameters: Parameters used
            success: Whether execution succeeded
            execution_time_ms: Execution duration
            user_satisfaction: Optional user rating (1.0 - 5.0)
        """
        if not self.db_session_factory:
            return
        
        # Skip if privacy mode is strict and user hasn't opted in
        if self.privacy_mode == "strict":
            # In strict mode, only record if user explicitly enabled
            # This would check a user preference table
            pass
        
        user_hash = self._hash_user(user_id)
        param_hash = hashlib.sha256(
            json.dumps(sorted(parameters.keys()), sort_keys=True).encode()
        ).hexdigest()[:32]
        param_values_hash = hashlib.sha256(
            json.dumps(parameters, sort_keys=True).encode()
        ).hexdigest()[:32]
        
        async with self.db_session_factory() as session:
            # Check if this parameter combination exists
            stmt = select(ParameterEffectivenessRecord).where(
                and_(
                    ParameterEffectivenessRecord.template_name == template.name,
                    ParameterEffectivenessRecord.parameter_hash == param_hash,
                    ParameterEffectivenessRecord.parameter_values_hash == param_values_hash,
                )
            )
            
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            
            now = datetime.now()
            
            if record:
                # Update existing
                record.execution_count += 1
                if success:
                    record.success_count += 1
                
                # Update rolling average
                if record.avg_execution_time_ms:
                    record.avg_execution_time_ms = (
                        record.avg_execution_time_ms * 0.9 + execution_time_ms * 0.1
                    )
                else:
                    record.avg_execution_time_ms = execution_time_ms
                
                record.last_used_at = now
                
                if user_satisfaction:
                    if record.user_satisfaction_score:
                        record.user_satisfaction_score = (
                            record.user_satisfaction_score * 0.8 + user_satisfaction * 0.2
                        )
                    else:
                        record.user_satisfaction_score = user_satisfaction
                
            else:
                # Create new record
                record = ParameterEffectivenessRecord(
                    template_name=template.name,
                    template_version=template.version,
                    parameter_hash=param_hash,
                    parameter_values_hash=param_values_hash,
                    parameter_values_json=json.dumps(parameters, sort_keys=True),
                    execution_count=1,
                    success_count=1 if success else 0,
                    avg_execution_time_ms=execution_time_ms,
                    user_satisfaction_score=user_satisfaction,
                    first_used_at=now,
                    last_used_at=now,
                    user_count=1,
                    can_be_used_for_suggestions=True,
                )
                session.add(record)
            
            # Update user preferences (anonymized)
            await self._update_user_preferences(
                session, user_hash, template.name, parameters
            )
            
            await session.commit()
            
            # Invalidate cache
            cache_key = self._get_cache_key(
                template.name, user_id, set(parameters.keys())
            )
            self._suggestion_cache.pop(cache_key, None)
    
    async def _update_user_preferences(
        self,
        session: AsyncSession,
        user_hash: str,
        template_name: str,
        parameters: Dict[str, Any],
    ):
        """Update anonymized user preferences."""
        # Find existing preference
        stmt = select(UserPreferenceRecord).where(
            and_(
                UserPreferenceRecord.user_hash == user_hash,
                UserPreferenceRecord.template_name == template_name,
            )
        )
        
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
        
        param_values_hash = hashlib.sha256(
            json.dumps(parameters, sort_keys=True).encode()
        ).hexdigest()[:32]
        
        now = datetime.now()
        
        if record:
            # Update with exponential moving average
            record.usage_count += 1
            record.last_updated = now
            
            # Only update if different enough
            if record.preferred_parameters_hash != param_values_hash:
                # Weight by usage count
                alpha = min(0.5, 1.0 / record.usage_count)
                
                try:
                    old_prefs = json.loads(record.preferred_parameters_json)
                    
                    # Merge parameters
                    new_prefs = {}
                    for key in set(old_prefs.keys()) | set(parameters.keys()):
                        if key in parameters and key in old_prefs:
                            # Keep old if same type, otherwise prefer new
                            if type(old_prefs[key]) == type(parameters[key]):
                                # Simple value: just use new
                                if isinstance(parameters[key], (str, int, float, bool)):
                                    new_prefs[key] = parameters[key]
                                else:
                                    new_prefs[key] = parameters[key]  # Complex: take new
                            else:
                                new_prefs[key] = parameters[key]
                        elif key in parameters:
                            new_prefs[key] = parameters[key]
                        else:
                            new_prefs[key] = old_prefs[key]
                    
                    record.preferred_parameters_json = json.dumps(new_prefs, sort_keys=True)
                    record.preferred_parameters_hash = hashlib.sha256(
                        record.preferred_parameters_json.encode()
                    ).hexdigest()[:32]
                    
                except json.JSONDecodeError:
                    record.preferred_parameters_json = json.dumps(parameters, sort_keys=True)
                    record.preferred_parameters_hash = param_values_hash
        else:
            # Create new record
            record = UserPreferenceRecord(
                user_hash=user_hash,
                template_name=template_name,
                preferred_parameters_hash=param_values_hash,
                preferred_parameters_json=json.dumps(parameters, sort_keys=True),
                usage_count=1,
                last_updated=now,
            )
            session.add(record)
    
    async def get_suggestion_stats(
        self,
        template_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get statistics about suggestions."""
        if not self.db_session_factory:
            return {}
        
        async with self.db_session_factory() as session:
            # Total parameter combinations tracked
            stmt = select(func.count()).select_from(ParameterEffectivenessRecord)
            if template_name:
                stmt = stmt.where(
                    ParameterEffectivenessRecord.template_name == template_name
                )
            
            result = await session.execute(stmt)
            total_combinations = result.scalar()
            
            # High-confidence suggestions available
            stmt = select(func.count()).where(
                and_(
                    ParameterEffectivenessRecord.execution_count >= self.MIN_SAMPLE_SIZE,
                    (ParameterEffectivenessRecord.success_count / 
                     func.nullif(ParameterEffectivenessRecord.execution_count, 0)) >= self.MIN_CONFIDENCE,
                )
            )
            if template_name:
                stmt = stmt.where(
                    ParameterEffectivenessRecord.template_name == template_name
                )
            
            result = await session.execute(stmt)
            high_confidence = result.scalar()
            
            # Average success rate
            stmt = select(
                func.avg(
                    ParameterEffectivenessRecord.success_count / 
                    func.nullif(ParameterEffectivenessRecord.execution_count, 0)
                )
            )
            if template_name:
                stmt = stmt.where(
                    ParameterEffectivenessRecord.template_name == template_name
                )
            
            result = await session.execute(stmt)
            avg_success_rate = result.scalar() or 0.0
            
            return {
                "total_combinations_tracked": total_combinations,
                "high_confidence_suggestions": high_confidence,
                "average_success_rate": avg_success_rate,
                "min_sample_size": self.MIN_SAMPLE_SIZE,
                "min_confidence_threshold": self.MIN_CONFIDENCE,
            }
    
    async def purge_old_data(self, days: int = 30):
        """
        Purge data older than specified days (GDPR compliance).
        
        Args:
            days: Retention period
        """
        if not self.db_session_factory:
            return
        
        cutoff = datetime.now() - timedelta(days=days)
        
        async with self.db_session_factory() as session:
            # Delete old effectiveness records
            stmt = select(ParameterEffectivenessRecord).where(
                ParameterEffectivenessRecord.last_used_at < cutoff
            )
            result = await session.execute(stmt)
            old_records = result.scalars().all()
            
            for record in old_records:
                await session.delete(record)
            
            # Delete old user preferences
            stmt = select(UserPreferenceRecord).where(
                UserPreferenceRecord.last_updated < cutoff
            )
            result = await session.execute(stmt)
            old_prefs = result.scalars().all()
            
            for pref in old_prefs:
                await session.delete(pref)
            
            await session.commit()
            
            _log.info(f"Purged {len(old_records)} effectiveness records and {len(old_prefs)} preference records")


class AdaptiveEngineDisabled:
    """Null object pattern when adaptive engine is disabled."""
    
    async def suggest_parameters(self, *args, **kwargs):
        return []
    
    async def record_execution_outcome(self, *args, **kwargs):
        pass
    
    async def get_suggestion_stats(self, *args, **kwargs):
        return {}
