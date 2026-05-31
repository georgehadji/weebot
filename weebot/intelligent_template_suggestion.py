"""
Intelligent Template Suggestion System for Weebot

This module provides capabilities for intelligently suggesting templates
based on user needs, context, and usage patterns.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol
import logging
from abc import ABC, abstractmethod
from pathlib import Path
import re
from collections import defaultdict, Counter

from weebot.user_profile_model import UserProfile, UserProfileManager
from weebot.nlp_understanding import IntentRecognitionResult, IntentType
from weebot.workflow_planner import WorkflowPlan, PlannedTask, TaskCategory
from weebot.templates.registry import TemplateRegistry
from weebot.templates.parser import WorkflowTemplate
from weebot.templates.adaptive import AdaptiveSuggestionEngine, ParameterSuggestion


class TemplateSuggestionType(Enum):
    """Types of template suggestions."""
    CONTEXTUAL = "contextual"
    USAGE_BASED = "usage_based"
    COLLABORATIVE = "collaborative"
    EXPERTISE_MATCH = "expertise_match"
    RECENTLY_USED = "recently_used"
    POPULAR = "popular"
    TRENDS_BASED = "trends_based"


class SuggestionQuality(Enum):
    """Quality levels for template suggestions."""
    EXCELLENT = "excellent"  # 0.9-1.0
    GOOD = "good"           # 0.7-0.89
    FAIR = "fair"           # 0.5-0.69
    POOR = "poor"           # 0.3-0.49
    REJECTED = "rejected"   # 0.0-0.29


@dataclass
class TemplateSuggestion:
    """A suggested template with relevance information."""
    template_id: str
    template_name: str
    description: str
    relevance_score: float  # 0.0 to 1.0
    quality_rating: SuggestionQuality
    suggestion_type: TemplateSuggestionType
    parameters: Dict[str, Any]  # Suggested parameter values
    usage_frequency: int  # How often this template is used
    last_used: Optional[datetime] = None
    confidence_score: float = 1.0  # Confidence in the suggestion
    reason: str = ""  # Reason for the suggestion
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class TemplateSuggestionEngine(ABC):
    """Abstract base class for template suggestion engines."""
    
    @abstractmethod
    async def suggest_templates(
        self,
        user_profile: UserProfile,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 5
    ) -> List[TemplateSuggestion]:
        """Suggest templates for a user based on their profile and context."""
        pass


class ContextualTemplateSuggester(TemplateSuggestionEngine):
    """Suggests templates based on current context and user intent."""
    
    def __init__(self, template_registry: TemplateRegistry):
        self.template_registry = template_registry
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Define template mappings based on intent
        self.intent_template_mappings = {
            IntentType.RESEARCH: [
                "Research Analysis Workflow",
                "Literature Review Workflow", 
                "Competitive Analysis Workflow"
            ],
            IntentType.ANALYSIS: [
                "Data Processing Workflow",
                "Statistical Analysis Workflow",
                "Market Analysis Workflow"
            ],
            IntentType.CONTENT_CREATION: [
                "Content Creation Workflow",
                "Blog Writing Workflow",
                "Documentation Generation Workflow"
            ],
            IntentType.AUTOMATION: [
                "Process Automation Workflow",
                "Task Automation Workflow",
                "Workflow Optimization Workflow"
            ],
            IntentType.TASK_EXECUTION: [
                "Simple Task Execution Workflow",
                "Multi-Step Task Workflow",
                "Parallel Task Workflow"
            ],
            IntentType.INFORMATION_REQUEST: [
                "Information Gathering Workflow",
                "Fact Checking Workflow",
                "Knowledge Extraction Workflow"
            ]
        }
    
    async def suggest_templates(
        self,
        user_profile: UserProfile,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 5
    ) -> List[TemplateSuggestion]:
        """Suggest templates based on context and intent."""
        suggestions = []
        
        # Get intent from context if available
        intent_type = None
        if context and "intent" in context:
            intent_str = context["intent"]
            try:
                intent_type = IntentType(intent_str)
            except ValueError:
                self.logger.warning(f"Unknown intent type: {intent_str}")
        
        # Get relevant templates based on intent
        relevant_templates = []
        if intent_type:
            relevant_template_names = self.intent_template_mappings.get(intent_type, [])
            for template_name in relevant_template_names:
                template = self.template_registry.get(template_name)
                if template:
                    relevant_templates.append(template)
        
        # If no intent-based templates found, fall back to domain-based
        if not relevant_templates and user_profile.preferred_domains:
            relevant_templates = await self._get_domain_relevant_templates(user_profile.preferred_domains)
        
        # If still no templates found, get all templates
        if not relevant_templates:
            all_templates = self.template_registry.list_templates()
            for template_name in all_templates:
                template = self.template_registry.get(template_name)
                if template:
                    relevant_templates.append(template)
        
        # Create suggestions
        for template in relevant_templates[:limit]:
            # Calculate relevance based on various factors
            relevance = await self._calculate_contextual_relevance(
                template, user_profile, context, intent_type
            )
            
            quality_rating = self._score_to_quality(relevance)
            
            # Get suggested parameters if available
            suggested_params = await self._suggest_parameters_for_context(
                template, user_profile, context
            )
            
            suggestion = TemplateSuggestion(
                template_id=template.name,  # Using name as ID for simplicity
                template_name=template.name,
                description=template.description,
                relevance_score=relevance,
                quality_rating=quality_rating,
                suggestion_type=TemplateSuggestionType.CONTEXTUAL,
                parameters=suggested_params,
                usage_frequency=0,  # Would come from usage statistics
                reason=f"Contextually relevant to {intent_type.value if intent_type else 'current context'}",
                tags=template.metadata.get("tags", []) if hasattr(template, 'metadata') else [],
                confidence_score=relevance
            )
            
            suggestions.append(suggestion)
        
        # Sort by relevance score
        suggestions.sort(key=lambda s: s.relevance_score, reverse=True)
        
        return suggestions[:limit]
    
    async def _get_domain_relevant_templates(self, domains: List[str]) -> List[WorkflowTemplate]:
        """Get templates relevant to user's preferred domains."""
        relevant_templates = []
        
        all_templates = self.template_registry.list_templates()
        for template_name in all_templates:
            template = self.template_registry.get(template_name)
            if template:
                # Check if template is relevant to any of the user's domains
                template_domains = getattr(template, 'domains', [])  # Assuming templates have domains attribute
                if not template_domains:  # If no specific domains, check description/tags
                    desc_lower = template.description.lower()
                    template_domains = [domain for domain in domains if domain.lower() in desc_lower]
                
                if any(domain in domains for domain in template_domains):
                    relevant_templates.append(template)
        
        return relevant_templates
    
    async def _calculate_contextual_relevance(
        self,
        template: WorkflowTemplate,
        user_profile: UserProfile,
        context: Optional[Dict[str, Any]],
        intent_type: Optional[IntentType]
    ) -> float:
        """Calculate contextual relevance score for a template."""
        score = 0.0
        
        # Base score on intent match
        if intent_type:
            intent_templates = self.intent_template_mappings.get(intent_type, [])
            if template.name in intent_templates:
                score += 0.4  # Strong intent match
        
        # Score based on domain match
        if user_profile.preferred_domains:
            template_domains = getattr(template, 'domains', [])
            if not template_domains and hasattr(template, 'description'):
                desc_lower = template.description.lower()
                template_domains = [
                    domain for domain in user_profile.preferred_domains 
                    if domain.lower() in desc_lower
                ]
            
            if any(domain in user_profile.preferred_domains for domain in template_domains):
                score += 0.3  # Domain match
        
        # Score based on context keywords
        if context and "keywords" in context:
            keywords = context["keywords"]
            desc_lower = template.description.lower()
            matches = sum(1 for keyword in keywords if keyword.lower() in desc_lower)
            if matches > 0:
                score += min(0.3, matches * 0.1)  # Up to 0.3 for keyword matches
        
        # Score based on user expertise level
        expertise_level = user_profile.expertise_level
        if expertise_level == "beginner":
            # Prefer simpler templates
            complexity_score = 1.0 - min(1.0, len(template.workflow) * 0.1)  # Simpler workflows get higher score
            score += complexity_score * 0.1
        elif expertise_level == "expert":
            # Prefer more complex templates
            complexity_score = min(1.0, len(template.workflow) * 0.1)  # More complex workflows get higher score
            score += complexity_score * 0.1
        
        # Ensure score is between 0 and 1
        return min(1.0, max(0.0, score))
    
    async def _suggest_parameters_for_context(
        self,
        template: WorkflowTemplate,
        user_profile: UserProfile,
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Suggest parameter values based on context."""
        suggested_params = {}
        
        if context:
            # Look for context values that match template parameters
            for param_name, param_def in template.parameters.items():
                # Check if there's a matching value in context
                if param_name in context:
                    suggested_params[param_name] = context[param_name]
                elif param_name in ["topic", "subject", "query", "research_topic"]:
                    # Common parameter names for research topics
                    if "query" in context:
                        suggested_params[param_name] = context["query"]
                    elif "topic" in context:
                        suggested_params[param_name] = context["topic"]
                    elif "research_topic" in context:
                        suggested_params[param_name] = context["research_topic"]
                elif param_name in ["output_format", "format"]:
                    if "output_format" in context:
                        suggested_params[param_name] = context["output_format"]
                    elif "format" in context:
                        suggested_params[param_name] = context["format"]
                elif param_name in ["depth", "detail_level"]:
                    if "depth" in context:
                        suggested_params[param_name] = context["depth"]
                    elif "detail_level" in context:
                        suggested_params[param_name] = context["detail_level"]
        
        return suggested_params
    
    def _score_to_quality(self, score: float) -> SuggestionQuality:
        """Convert numerical score to quality rating."""
        if score >= 0.9:
            return SuggestionQuality.EXCELLENT
        elif score >= 0.7:
            return SuggestionQuality.GOOD
        elif score >= 0.5:
            return SuggestionQuality.FAIR
        elif score >= 0.3:
            return SuggestionQuality.POOR
        else:
            return SuggestionQuality.REJECTED


class UsageBasedTemplateSuggester(TemplateSuggestionEngine):
    """Suggests templates based on usage patterns and popularity."""
    
    def __init__(self, template_registry: TemplateRegistry):
        self.template_registry = template_registry
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # In-memory usage statistics (in a real system, this would be persisted)
        self.template_usage_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "usage_count": 0,
            "success_rate": 0.0,
            "avg_completion_time": 0.0,
            "recent_users": [],
            "last_used": None
        })
    
    async def suggest_templates(
        self,
        user_profile: UserProfile,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 5
    ) -> List[TemplateSuggestion]:
        """Suggest templates based on usage patterns."""
        suggestions = []
        
        # Get all templates
        all_template_names = self.template_registry.list_templates()
        
        # Calculate usage-based scores
        template_scores = []
        for template_name in all_template_names:
            template = self.template_registry.get(template_name)
            if template:
                score = await self._calculate_usage_score(template_name, user_profile)
                template_scores.append((template, score))
        
        # Sort by score
        template_scores.sort(key=lambda x: x[1], reverse=True)
        
        # Create suggestions for top templates
        for template, score in template_scores[:limit]:
            usage_stats = self.template_usage_stats[template.name]
            
            quality_rating = self._score_to_quality(score)
            
            suggestion = TemplateSuggestion(
                template_id=template.name,
                template_name=template.name,
                description=template.description,
                relevance_score=score,
                quality_rating=quality_rating,
                suggestion_type=TemplateSuggestionType.USAGE_BASED,
                parameters={},  # No specific parameter suggestions from usage alone
                usage_frequency=usage_stats["usage_count"],
                last_used=usage_stats["last_used"],
                reason=f"Popular template with {usage_stats['usage_count']} uses and {usage_stats['success_rate']:.2f} success rate",
                tags=getattr(template, 'tags', []),
                confidence_score=score
            )
            
            suggestions.append(suggestion)
        
        return suggestions
    
    async def _calculate_usage_score(self, template_name: str, user_profile: UserProfile) -> float:
        """Calculate usage-based score for a template."""
        stats = self.template_usage_stats[template_name]
        
        # Base score on usage count (with diminishing returns)
        usage_score = min(0.5, stats["usage_count"] * 0.05)  # Max 0.5 from usage count
        
        # Add success rate component
        success_score = stats["success_rate"] * 0.3  # Max 0.3 from success rate
        
        # Add recency component (prefer recently used templates)
        recency_score = 0.2
        if stats["last_used"]:
            days_since_use = (datetime.now() - stats["last_used"]).days
            if days_since_use <= 7:  # Used in last week
                recency_score = 0.2
            elif days_since_use <= 30:  # Used in last month
                recency_score = 0.15
            elif days_since_use <= 90:  # Used in last 3 months
                recency_score = 0.1
            else:
                recency_score = 0.05
        
        # Combine scores
        total_score = usage_score + success_score + recency_score
        
        # Normalize to 0-1 range
        return min(1.0, total_score)
    
    def record_template_usage(
        self, 
        template_name: str, 
        user_id: str, 
        success: bool = True,
        completion_time: Optional[float] = None
    ):
        """Record template usage for statistics."""
        stats = self.template_usage_stats[template_name]
        
        stats["usage_count"] += 1
        stats["last_used"] = datetime.now()
        
        # Update success rate
        current_success_rate = stats["success_rate"]
        total_runs = stats["usage_count"]
        successful_runs = int(current_success_rate * (total_runs - 1)) + (1 if success else 0)
        stats["success_rate"] = successful_runs / total_runs
        
        # Update average completion time
        if completion_time is not None:
            current_avg = stats["avg_completion_time"]
            if current_avg == 0:
                stats["avg_completion_time"] = completion_time
            else:
                # Moving average
                stats["avg_completion_time"] = (current_avg * (total_runs - 1) + completion_time) / total_runs
        
        # Track recent users (limit to last 10)
        stats["recent_users"] = (stats["recent_users"] + [user_id])[-10:]
    
    def _score_to_quality(self, score: float) -> SuggestionQuality:
        """Convert numerical score to quality rating."""
        if score >= 0.9:
            return SuggestionQuality.EXCELLENT
        elif score >= 0.7:
            return SuggestionQuality.GOOD
        elif score >= 0.5:
            return SuggestionQuality.FAIR
        elif score >= 0.3:
            return SuggestionQuality.POOR
        else:
            return SuggestionQuality.REJECTED


class CollaborativeTemplateSuggester(TemplateSuggestionEngine):
    """Suggests templates based on collaborative filtering."""
    
    def __init__(self, template_registry: TemplateRegistry):
        self.template_registry = template_registry
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # User-template interaction matrix (in a real system, this would be persisted)
        self.user_template_interactions: Dict[str, List[str]] = defaultdict(list)  # user_id -> [template_names]
        self.template_similarities: Dict[str, Dict[str, float]] = {}  # template_name -> {similar_template: similarity}
    
    async def suggest_templates(
        self,
        user_profile: UserProfile,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 5
    ) -> List[TemplateSuggestion]:
        """Suggest templates based on collaborative filtering."""
        suggestions = []
        
        # Get templates used by similar users
        similar_user_templates = await self._get_templates_for_similar_users(user_profile.user_id)
        
        # Rank templates by collaborative score
        template_scores = await self._rank_templates_collaboratively(
            user_profile.user_id, similar_user_templates
        )
        
        # Create suggestions for top templates
        for template_name, score in list(template_scores.items())[:limit]:
            template = self.template_registry.get(template_name)
            if template:
                quality_rating = self._score_to_quality(score)
                
                suggestion = TemplateSuggestion(
                    template_id=template.name,
                    template_name=template.name,
                    description=template.description,
                    relevance_score=score,
                    quality_rating=quality_rating,
                    suggestion_type=TemplateSuggestionType.COLLABORATIVE,
                    parameters={},  # No specific parameter suggestions from collaboration alone
                    usage_frequency=0,  # Would come from usage stats
                    reason=f"Suggested based on similar users' preferences",
                    tags=getattr(template, 'tags', []),
                    confidence_score=score
                )
                
                suggestions.append(suggestion)
        
        return suggestions
    
    async def _get_templates_for_similar_users(self, user_id: str) -> List[str]:
        """Get templates used by users with similar profiles."""
        # In a real implementation, this would find users with similar profiles
        # For now, we'll return templates used by other users
        all_templates = []
        for other_user, templates in self.user_template_interactions.items():
            if other_user != user_id:
                all_templates.extend(templates)
        
        return all_templates
    
    async def _rank_templates_collaboratively(
        self, 
        user_id: str, 
        similar_user_templates: List[str]
    ) -> Dict[str, float]:
        """Rank templates based on collaborative filtering."""
        # Count how many similar users used each template
        template_counts = Counter(similar_user_templates)
        
        # Calculate scores based on frequency and other factors
        scores = {}
        if template_counts:
            max_count = max(template_counts.values())
            for template_name, count in template_counts.items():
                # Normalize count to 0-0.8 range
                normalized_count = (count / max_count) * 0.8
                
                # Additional factors could be added here
                scores[template_name] = normalized_count
        
        return scores
    
    def record_user_template_interaction(self, user_id: str, template_name: str):
        """Record that a user interacted with a template."""
        if template_name not in self.user_template_interactions[user_id]:
            self.user_template_interactions[user_id].append(template_name)
    
    def _score_to_quality(self, score: float) -> SuggestionQuality:
        """Convert numerical score to quality rating."""
        if score >= 0.9:
            return SuggestionQuality.EXCELLENT
        elif score >= 0.7:
            return SuggestionQuality.GOOD
        elif score >= 0.5:
            return SuggestionQuality.FAIR
        elif score >= 0.3:
            return SuggestionQuality.POOR
        else:
            return SuggestionQuality.REJECTED


class IntelligentTemplateSuggestionEngine:
    """Main engine for intelligent template suggestions."""
    
    def __init__(
        self, 
        template_registry: TemplateRegistry,
        profile_manager: UserProfileManager,
        adaptive_engine: Optional[AdaptiveSuggestionEngine] = None
    ):
        self.template_registry = template_registry
        self.profile_manager = profile_manager
        self.adaptive_engine = adaptive_engine
        self.logger = logging.getLogger(f"{__name__}.IntelligentTemplateSuggestionEngine")
        
        # Initialize suggesters
        self.contextual_suggester = ContextualTemplateSuggester(template_registry)
        self.usage_suggester = UsageBasedTemplateSuggester(template_registry)
        self.collaborative_suggester = CollaborativeTemplateSuggester(template_registry)
        
        self.suggesters = [
            (self.contextual_suggester, 0.5),    # 50% weight
            (self.usage_suggester, 0.3),         # 30% weight
            (self.collaborative_suggester, 0.2)  # 20% weight
        ]
    
    async def get_template_suggestions(
        self,
        user_id: str,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 5
    ) -> List[TemplateSuggestion]:
        """Get intelligent template suggestions for a user."""
        # Get user profile
        profile = await self.profile_manager.get_profile(user_id)
        if not profile:
            self.logger.warning(f"No profile found for user {user_id}")
            return []
        
        # Get suggestions from all suggesters
        all_suggestions = []
        for suggester, weight in self.suggesters:
            try:
                suggestions = await suggester.suggest_templates(profile, context, limit * 2)  # Get more to rank
                
                # Apply weight to scores
                for suggestion in suggestions:
                    suggestion.relevance_score *= weight
                    suggestion.confidence_score *= weight
                
                all_suggestions.extend(suggestions)
            except Exception as e:
                self.logger.error(f"Error in suggester {type(suggester).__name__}: {e}")
                continue
        
        # Remove duplicates and merge scores
        merged_suggestions = self._merge_suggestions(all_suggestions)
        
        # Sort by relevance score
        merged_suggestions.sort(key=lambda s: s.relevance_score, reverse=True)
        
        # Apply adaptive suggestions if available
        if self.adaptive_engine:
            try:
                adaptive_suggestions = await self._get_adaptive_suggestions(
                    user_id, profile, context
                )
                merged_suggestions = self._integrate_adaptive_suggestions(
                    merged_suggestions, adaptive_suggestions
                )
            except Exception as e:
                self.logger.error(f"Error in adaptive suggestions: {e}")
        
        # Return top suggestions
        return merged_suggestions[:limit]
    
    def _merge_suggestions(self, suggestions: List[TemplateSuggestion]) -> List[TemplateSuggestion]:
        """Merge suggestions from different suggesters."""
        merged = {}
        
        for suggestion in suggestions:
            template_id = suggestion.template_id
            
            if template_id not in merged:
                # Create new merged suggestion
                merged[template_id] = TemplateSuggestion(
                    template_id=suggestion.template_id,
                    template_name=suggestion.template_name,
                    description=suggestion.description,
                    relevance_score=suggestion.relevance_score,
                    quality_rating=suggestion.quality_rating,
                    suggestion_type=suggestion.suggestion_type,
                    parameters=suggestion.parameters,
                    usage_frequency=suggestion.usage_frequency,
                    last_used=suggestion.last_used,
                    confidence_score=suggestion.confidence_score,
                    reason=suggestion.reason,
                    tags=suggestion.tags,
                    metadata=suggestion.metadata
                )
            else:
                # Merge with existing suggestion
                existing = merged[template_id]
                
                # Combine relevance scores (weighted average)
                total_weight = existing.confidence_score + suggestion.confidence_score
                if total_weight > 0:
                    existing.relevance_score = (
                        (existing.relevance_score * existing.confidence_score) +
                        (suggestion.relevance_score * suggestion.confidence_score)
                    ) / total_weight
                
                # Update quality rating based on new score
                existing.quality_rating = self._score_to_quality(existing.relevance_score)
                
                # Combine reasons
                if suggestion.reason not in existing.reason:
                    existing.reason += f"; {suggestion.reason}"
                
                # Combine tags
                for tag in suggestion.tags:
                    if tag not in existing.tags:
                        existing.tags.append(tag)
        
        return list(merged.values())
    
    async def _get_adaptive_suggestions(
        self,
        user_id: str,
        profile: UserProfile,
        context: Optional[Dict[str, Any]]
    ) -> List[ParameterSuggestion]:
        """Get adaptive parameter suggestions if available."""
        if not self.adaptive_engine:
            return []
        
        # Get adaptive suggestions for template parameters
        # This would typically happen when user selects a template
        # For now, we'll return empty list as adaptive suggestions are
        # more about parameter values than template selection
        return []
    
    def _integrate_adaptive_suggestions(
        self,
        template_suggestions: List[TemplateSuggestion],
        adaptive_suggestions: List[ParameterSuggestion]
    ) -> List[TemplateSuggestion]:
        """Integrate adaptive parameter suggestions with template suggestions."""
        # For now, we'll just return the template suggestions
        # Adaptive suggestions would be applied when a template is selected
        return template_suggestions
    
    async def record_template_selection(
        self,
        user_id: str,
        template_name: str,
        success: bool = True,
        completion_time: Optional[float] = None
    ):
        """Record that a user selected and used a template."""
        # Record in usage-based suggester
        self.usage_suggester.record_template_usage(
            template_name, user_id, success, completion_time
        )
        
        # Record in collaborative suggester
        self.collaborative_suggester.record_user_template_interaction(user_id, template_name)
        
        self.logger.info(f"Recorded template selection: {template_name} by user {user_id}")
    
    async def get_template_recommendation_reasons(
        self,
        user_id: str,
        template_name: str
    ) -> List[str]:
        """Get reasons why a template was recommended to a user."""
        reasons = []
        
        # Get user profile
        profile = await self.profile_manager.get_profile(user_id)
        if not profile:
            return reasons
        
        # Check if template matches user's preferred domains
        template = self.template_registry.get(template_name)
        if template:
            # Check domain match
            template_domains = getattr(template, 'domains', [])
            if not template_domains and hasattr(template, 'description'):
                desc_lower = template.description.lower()
                template_domains = [
                    domain for domain in profile.preferred_domains 
                    if domain.lower() in desc_lower
                ]
            
            if template_domains:
                reasons.append(f"Matches your interest in {', '.join(template_domains)}")
            
            # Check if it's popular
            usage_stats = self.usage_suggester.template_usage_stats.get(template_name, {})
            if usage_stats.get("usage_count", 0) > 10:
                reasons.append(f"Used by {usage_stats['usage_count']} other users")
            
            if usage_stats.get("success_rate", 0) > 0.8:
                reasons.append(f"Has high success rate ({usage_stats['success_rate']:.1%})")
        
        return reasons


class TemplateSuggestionTool:
    """Tool for getting template suggestions."""
    
    def __init__(self, suggestion_engine: IntelligentTemplateSuggestionEngine):
        self.suggestion_engine = suggestion_engine
        self.logger = logging.getLogger(f"{__name__}.TemplateSuggestionTool")
    
    async def get_suggestions(
        self,
        user_id: str,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 5
    ) -> Dict[str, Any]:
        """Get template suggestions for a user."""
        try:
            suggestions = await self.suggestion_engine.get_template_suggestions(
                user_id, context, limit
            )
            
            # Format suggestions for output
            formatted_suggestions = []
            for suggestion in suggestions:
                formatted_suggestions.append({
                    "template_id": suggestion.template_id,
                    "template_name": suggestion.template_name,
                    "description": suggestion.description,
                    "relevance_score": suggestion.relevance_score,
                    "quality_rating": suggestion.quality_rating.value,
                    "suggestion_type": suggestion.suggestion_type.value,
                    "usage_frequency": suggestion.usage_frequency,
                    "reason": suggestion.reason,
                    "tags": suggestion.tags,
                    "confidence_score": suggestion.confidence_score
                })
            
            return {
                "user_id": user_id,
                "suggestions_count": len(formatted_suggestions),
                "suggestions": formatted_suggestions,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            self.logger.error(f"Error getting template suggestions: {e}")
            return {
                "error": f"Error getting template suggestions: {str(e)}",
                "user_id": user_id
            }
    
    async def record_selection(
        self,
        user_id: str,
        template_name: str,
        success: bool = True,
        completion_time: Optional[float] = None
    ) -> Dict[str, Any]:
        """Record that a user selected a template."""
        try:
            await self.suggestion_engine.record_template_selection(
                user_id, template_name, success, completion_time
            )
            
            return {
                "success": True,
                "message": f"Recorded selection of template {template_name} by user {user_id}",
                "user_id": user_id,
                "template_name": template_name
            }
        except Exception as e:
            self.logger.error(f"Error recording template selection: {e}")
            return {
                "error": f"Error recording template selection: {str(e)}",
                "user_id": user_id,
                "template_name": template_name
            }
    
    async def get_recommendation_reasons(
        self,
        user_id: str,
        template_name: str
    ) -> Dict[str, Any]:
        """Get reasons why a template was recommended."""
        try:
            reasons = await self.suggestion_engine.get_template_recommendation_reasons(
                user_id, template_name
            )
            
            return {
                "user_id": user_id,
                "template_name": template_name,
                "reasons": reasons,
                "reasons_count": len(reasons)
            }
        except Exception as e:
            self.logger.error(f"Error getting recommendation reasons: {e}")
            return {
                "error": f"Error getting recommendation reasons: {str(e)}",
                "user_id": user_id,
                "template_name": template_name
            }
    
    def to_param(self) -> Dict[str, Any]:
        """Convert to parameter format for tool registration."""
        return {
            "type": "function",
            "function": {
                "name": "get_template_suggestions",
                "description": "Get intelligent template suggestions based on user profile and context",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "ID of the user to get suggestions for"
                        },
                        "context": {
                            "type": "object",
                            "description": "Additional context for personalization"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of suggestions to return (default: 5)",
                            "default": 5
                        }
                    },
                    "required": ["user_id"]
                }
            }
        }


# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def example():
        # This example would require a template registry and profile manager
        # For demonstration, we'll create a simplified version
        
        # Create a basic template registry (mock)
        class MockTemplateRegistry:
            def __init__(self):
                self.templates = {
                    "Research Analysis Workflow": type('Template', (), {
                        'name': 'Research Analysis Workflow',
                        'description': 'Comprehensive research and analysis workflow',
                        'parameters': {'topic': {'type': 'string'}},
                        'workflow': {'step1': {'type': 'task'}}
                    })(),
                    "Content Creation Workflow": type('Template', (), {
                        'name': 'Content Creation Workflow',
                        'description': 'Workflow for creating content',
                        'parameters': {'topic': {'type': 'string'}},
                        'workflow': {'step1': {'type': 'task'}}
                    })(),
                    "Data Processing Workflow": type('Template', (), {
                        'name': 'Data Processing Workflow',
                        'description': 'Workflow for processing data',
                        'parameters': {'dataset': {'type': 'string'}},
                        'workflow': {'step1': {'type': 'task'}}
                    })()
                }
            
            def get(self, name):
                return self.templates.get(name)
            
            def list_templates(self):
                return list(self.templates.keys())
        
        # Create a basic profile manager (mock)
        from weebot.user_profile_model import InMemoryUserProfileStorage, UserProfileManager
        
        storage = InMemoryUserProfileStorage()
        profile_manager = UserProfileManager(storage)
        
        # Create a sample user profile
        user_profile = await profile_manager.create_profile(
            user_id="user_123",
            name="Sam Taylor",
            email="sam@example.com"
        )
        
        # Add some preferences to the profile
        await profile_manager.update_preference(
            user_id="user_123",
            category=PreferenceCategory.CONTENT_PREFERENCES,
            key="preferred_domains",
            value=["technology", "research"]
        )
        
        # Create template registry and suggestion engine
        template_registry = MockTemplateRegistry()
        suggestion_engine = IntelligentTemplateSuggestionEngine(
            template_registry=template_registry,
            profile_manager=profile_manager
        )
        
        print("Getting intelligent template suggestions...")
        
        # Get suggestions
        suggestions = await suggestion_engine.get_template_suggestions(
            user_id="user_123",
            context={
                "intent": "RESEARCH",
                "query": "AI developments in 2026",
                "keywords": ["AI", "technology", "research"]
            },
            limit=3
        )
        
        print(f"\nGenerated {len(suggestions)} template suggestions:")
        for i, suggestion in enumerate(suggestions, 1):
            print(f"\n{i}. {suggestion.template_name}")
            print(f"   Description: {suggestion.description}")
            print(f"   Relevance: {suggestion.relevance_score:.2f}")
            print(f"   Quality: {suggestion.quality_rating.value}")
            print(f"   Type: {suggestion.suggestion_type.value}")
            print(f"   Reason: {suggestion.reason}")
            print(f"   Tags: {suggestion.tags}")
        
        # Record a selection
        await suggestion_engine.record_template_selection(
            user_id="user_123",
            template_name="Research Analysis Workflow",
            success=True,
            completion_time=120.5
        )
        
        # Get recommendation reasons
        reasons = await suggestion_engine.get_template_recommendation_reasons(
            user_id="user_123",
            template_name="Research Analysis Workflow"
        )
        print(f"\nRecommendation reasons: {reasons}")
        
        print("\nExample completed successfully!")
    
    asyncio.run(example())