"""
Customized Suggestions System for Weebot

This module provides capabilities for generating personalized suggestions
based on user profiles, preferences, and interaction history.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol
import logging
from abc import ABC, abstractmethod
import uuid
import math
from collections import defaultdict

from weebot.user_profile_model import UserProfile, UserProfileManager, PreferenceCategory
from weebot.nlp_understanding import IntentRecognitionResult, IntentType
from weebot.workflow_planner import WorkflowPlan, PlannedTask
from weebot.multi_source_research import ResearchResult
from weebot.information_synthesis import SynthesizedInformation


class SuggestionType(Enum):
    """Types of suggestions that can be made."""
    TASK_SUGGESTION = "task_suggestion"
    RESEARCH_TOPIC = "research_topic"
    CONTENT_IDEA = "content_idea"
    TOOL_RECOMMENDATION = "tool_recommendation"
    WORKFLOW_OPTIMIZATION = "workflow_optimization"
    LEARNING_PATH = "learning_path"
    CONNECTION_SUGGESTION = "connection_suggestion"
    GOAL_RECOMMENDATION = "goal_recommendation"


class SuggestionQuality(Enum):
    """Quality levels for suggestions."""
    EXCELLENT = "excellent"  # 0.9-1.0
    GOOD = "good"           # 0.7-0.89
    FAIR = "fair"           # 0.5-0.69
    POOR = "poor"           # 0.3-0.49
    REJECTED = "rejected"   # 0.0-0.29


@dataclass
class Suggestion:
    """A personalized suggestion for a user."""
    suggestion_id: str
    suggestion_type: SuggestionType
    title: str
    description: str
    confidence_score: float  # 0.0 to 1.0
    quality_rating: SuggestionQuality
    relevance_score: float  # How relevant to user's interests/profile
    novelty_score: float   # How novel compared to previous suggestions
    context: Dict[str, Any]  # Context for the suggestion
    created_at: datetime
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)


class SuggestionGenerator(ABC):
    """Abstract base class for suggestion generators."""
    
    @abstractmethod
    async def generate_suggestions(
        self, 
        user_profile: UserProfile, 
        context: Optional[Dict[str, Any]] = None
    ) -> List[Suggestion]:
        """Generate suggestions for a user."""
        pass


class TaskSuggestionGenerator(SuggestionGenerator):
    """Generates task suggestions based on user profile and context."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Define common tasks by domain
        self.domain_tasks = {
            "technology": [
                "Research latest AI trends",
                "Analyze software architecture",
                "Compare programming languages",
                "Review tech documentation"
            ],
            "business": [
                "Analyze market trends",
                "Research competitors",
                "Create business plan",
                "Review financial reports"
            ],
            "education": [
                "Research academic papers",
                "Create study materials",
                "Analyze educational content",
                "Summarize course materials"
            ],
            "research": [
                "Literature review",
                "Data analysis",
                "Hypothesis testing",
                "Methodology review"
            ],
            "creative": [
                "Content ideation",
                "Writing assistance",
                "Design inspiration",
                "Creative brainstorming"
            ]
        }
    
    async def generate_suggestions(
        self, 
        user_profile: UserProfile, 
        context: Optional[Dict[str, Any]] = None
    ) -> List[Suggestion]:
        """Generate task suggestions for a user."""
        suggestions = []
        
        # Get user's preferred domains
        preferred_domains = user_profile.preferred_domains or ["general"]
        
        # Generate suggestions based on domains
        for domain in preferred_domains:
            domain_tasks = self.domain_tasks.get(domain, self.domain_tasks.get("general", []))
            
            for i, task_desc in enumerate(domain_tasks[:3]):  # Limit to 3 per domain
                # Calculate relevance based on domain match
                relevance = 0.8 if domain in user_profile.preferred_domains else 0.5
                
                # Add some randomness to novelty
                novelty = 0.7 + (hash(f"{task_desc}{user_profile.user_id}{i}") % 10) / 100
                
                # Calculate overall score
                confidence = min(1.0, (relevance + novelty) / 2)
                
                quality_rating = self._score_to_quality(confidence)
                
                suggestion = Suggestion(
                    suggestion_id=f"task_{uuid.uuid4().hex[:8]}",
                    suggestion_type=SuggestionType.TASK_SUGGESTION,
                    title=f"Task: {task_desc}",
                    description=f"Suggested task based on your interest in {domain}",
                    confidence_score=confidence,
                    quality_rating=quality_rating,
                    relevance_score=relevance,
                    novelty_score=novelty,
                    context={
                        "domain": domain,
                        "task_description": task_desc,
                        "user_expertise": user_profile.expertise_level
                    },
                    created_at=datetime.now(),
                    tags=["task", domain, user_profile.expertise_level]
                )
                
                suggestions.append(suggestion)
        
        # If context is provided, generate more specific suggestions
        if context:
            # Look for specific needs in context
            if "current_project" in context:
                project = context["current_project"]
                suggestion = Suggestion(
                    suggestion_id=f"proj_task_{uuid.uuid4().hex[:8]}",
                    suggestion_type=SuggestionType.TASK_SUGGESTION,
                    title=f"Next Step for {project.get('name', 'your project')}",
                    description=f"Suggested next task based on your current project: {project.get('description', 'project')}",
                    confidence_score=0.85,
                    quality_rating=SuggestionQuality.GOOD,
                    relevance_score=0.9,
                    novelty_score=0.6,
                    context={
                        "project": project,
                        "suggestion_basis": "current_project"
                    },
                    created_at=datetime.now(),
                    tags=["project", "next_step"]
                )
                suggestions.append(suggestion)
        
        return suggestions
    
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


class ResearchTopicSuggestionGenerator(SuggestionGenerator):
    """Generates research topic suggestions based on user interests."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Define trending topics by domain
        self.trending_topics = {
            "technology": [
                "AI ethics and governance",
                "Quantum computing applications",
                "Blockchain beyond cryptocurrency",
                "Edge computing trends",
                "Cybersecurity in AI systems"
            ],
            "business": [
                "Remote work productivity",
                "Sustainable business practices",
                "Digital transformation strategies",
                "Supply chain resilience",
                "Customer experience innovation"
            ],
            "science": [
                "Climate change mitigation",
                "Renewable energy advances",
                "Space exploration developments",
                "Biotechnology breakthroughs",
                "Neuroscience discoveries"
            ]
        }
    
    async def generate_suggestions(
        self, 
        user_profile: UserProfile, 
        context: Optional[Dict[str, Any]] = None
    ) -> List[Suggestion]:
        """Generate research topic suggestions for a user."""
        suggestions = []
        
        # Get user's preferred domains
        preferred_domains = user_profile.preferred_domains or ["general"]
        
        # Generate suggestions based on domains and trending topics
        for domain in preferred_domains:
            trending_in_domain = self.trending_topics.get(domain, [])
            
            for i, topic in enumerate(trending_in_domain[:2]):  # Limit to 2 per domain
                # Calculate relevance based on domain match and user expertise
                base_relevance = 0.7 if domain in user_profile.preferred_domains else 0.4
                expertise_factor = {"beginner": 0.5, "intermediate": 0.7, "advanced": 0.9, "expert": 1.0}.get(
                    user_profile.expertise_level, 0.7
                )
                relevance = base_relevance * expertise_factor
                
                # Calculate novelty (avoid suggesting topics already researched)
                novelty = 0.8  # Default high novelty
                if context and "previous_research" in context:
                    prev_topics = context["previous_research"]
                    if topic.lower() in [t.lower() for t in prev_topics]:
                        novelty = 0.2  # Low novelty if already researched
                
                # Calculate overall score
                confidence = min(1.0, (relevance + novelty) / 2)
                
                quality_rating = self._score_to_quality(confidence)
                
                suggestion = Suggestion(
                    suggestion_id=f"research_{uuid.uuid4().hex[:8]}",
                    suggestion_type=SuggestionType.RESEARCH_TOPIC,
                    title=f"Research: {topic}",
                    description=f"Trending research topic in {domain} that aligns with your interests",
                    confidence_score=confidence,
                    quality_rating=quality_rating,
                    relevance_score=relevance,
                    novelty_score=novelty,
                    context={
                        "domain": domain,
                        "topic": topic,
                        "user_expertise": user_profile.expertise_level,
                        "trending": True
                    },
                    created_at=datetime.now(),
                    tags=["research", "trending", domain, user_profile.expertise_level]
                )
                
                suggestions.append(suggestion)
        
        return suggestions
    
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


class ToolRecommendationSuggestionGenerator(SuggestionGenerator):
    """Generates tool recommendations based on user needs."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Define tools by use case
        self.use_case_tools = {
            "research": ["web_search", "advanced_browser", "document_reader"],
            "analysis": ["python_tool", "data_analyzer", "chart_creator"],
            "writing": ["document_editor", "grammar_checker", "outline_tool"],
            "automation": ["bash_tool", "scheduler", "notification_tool"],
            "development": ["code_editor", "debugger", "testing_tool"]
        }
    
    async def generate_suggestions(
        self, 
        user_profile: UserProfile, 
        context: Optional[Dict[str, Any]] = None
    ) -> List[Suggestion]:
        """Generate tool recommendation suggestions for a user."""
        suggestions = []
        
        # Determine user's likely needs based on interaction history
        needs = self._infer_user_needs(user_profile, context)
        
        for need in needs:
            tools_for_need = self.use_case_tools.get(need, [])
            
            for tool in tools_for_need[:2]:  # Limit to 2 tools per need
                # Calculate relevance based on user's past tool usage and preferences
                relevance = 0.7
                
                # Check if user has used similar tools before
                if context and "used_tools" in context:
                    if tool in context["used_tools"]:
                        relevance = 0.3  # Lower relevance if already used
                    else:
                        relevance = 0.8  # Higher relevance if new
                
                # Calculate novelty
                novelty = 0.9 if tool not in (context.get("used_tools", [])) else 0.2
                
                # Calculate overall score
                confidence = min(1.0, (relevance + novelty) / 2)
                
                quality_rating = self._score_to_quality(confidence)
                
                suggestion = Suggestion(
                    suggestion_id=f"tool_{uuid.uuid4().hex[:8]}",
                    suggestion_type=SuggestionType.TOOL_RECOMMENDATION,
                    title=f"Tool: {tool.replace('_', ' ').title()}",
                    description=f"Recommended tool for {need}-related tasks",
                    confidence_score=confidence,
                    quality_rating=quality_rating,
                    relevance_score=relevance,
                    novelty_score=novelty,
                    context={
                        "need": need,
                        "tool": tool,
                        "use_case": f"tasks related to {need}"
                    },
                    created_at=datetime.now(),
                    tags=["tool", "recommendation", need]
                )
                
                suggestions.append(suggestion)
        
        return suggestions
    
    def _infer_user_needs(self, user_profile: UserProfile, context: Optional[Dict[str, Any]]) -> List[str]:
        """Infer user needs based on profile and context."""
        needs = set()
        
        # Infer from preferred domains
        for domain in user_profile.preferred_domains:
            if domain in ["technology", "engineering"]:
                needs.add("development")
            elif domain in ["research", "science", "academia"]:
                needs.add("research")
            elif domain in ["business", "marketing", "management"]:
                needs.add("analysis")
            elif domain in ["writing", "content", "media"]:
                needs.add("writing")
            elif domain in ["operations", "process", "automation"]:
                needs.add("automation")
        
        # Infer from interaction history
        if user_profile.interaction_history:
            recent_interactions = user_profile.interaction_history[-10:]  # Last 10 interactions
            for interaction in recent_interactions:
                if "research" in interaction.content.lower():
                    needs.add("research")
                elif "analyze" in interaction.content.lower() or "data" in interaction.content.lower():
                    needs.add("analysis")
                elif "write" in interaction.content.lower() or "document" in interaction.content.lower():
                    needs.add("writing")
                elif "automate" in interaction.content.lower():
                    needs.add("automation")
        
        # Add from context if available
        if context:
            if "current_task_type" in context:
                task_type = context["current_task_type"]
                if task_type in self.use_case_tools:
                    needs.add(task_type)
        
        return list(needs)[:3]  # Limit to top 3 needs
    
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


class SuggestionAggregator:
    """Aggregates suggestions from multiple generators."""
    
    def __init__(self):
        self.generators: List[SuggestionGenerator] = []
        self.logger = logging.getLogger(f"{__name__}.SuggestionAggregator")
    
    async def add_generator(self, generator: SuggestionGenerator):
        """Add a suggestion generator."""
        self.generators.append(generator)
    
    async def generate_all_suggestions(
        self, 
        user_profile: UserProfile, 
        context: Optional[Dict[str, Any]] = None,
        max_suggestions: int = 10
    ) -> List[Suggestion]:
        """Generate suggestions from all registered generators."""
        all_suggestions = []
        
        # Run all generators concurrently
        tasks = [
            gen.generate_suggestions(user_profile, context) 
            for gen in self.generators
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.error(f"Error in generator {i}: {result}")
                continue
            
            if isinstance(result, list):
                all_suggestions.extend(result)
        
        # Sort suggestions by confidence score (descending)
        all_suggestions.sort(key=lambda s: s.confidence_score, reverse=True)
        
        # Remove duplicates based on title and type
        unique_suggestions = []
        seen = set()
        for suggestion in all_suggestions:
            key = (suggestion.title.lower(), suggestion.suggestion_type.value)
            if key not in seen:
                seen.add(key)
                unique_suggestions.append(suggestion)
        
        # Return top suggestions
        return unique_suggestions[:max_suggestions]


class PersonalizedSuggestionEngine:
    """Main engine for generating personalized suggestions."""
    
    def __init__(self, profile_manager: UserProfileManager):
        self.profile_manager = profile_manager
        self.aggregator = SuggestionAggregator()
        self.logger = logging.getLogger(f"{__name__}.PersonalizedSuggestionEngine")
        
        # Add default generators
        self.default_generators = [
            TaskSuggestionGenerator(),
            ResearchTopicSuggestionGenerator(),
            ToolRecommendationSuggestionGenerator()
        ]
        
        # Initialize with default generators
        for gen in self.default_generators:
            asyncio.create_task(self.aggregator.add_generator(gen))
    
    async def add_suggestion_generator(self, generator: SuggestionGenerator):
        """Add a custom suggestion generator."""
        await self.aggregator.add_generator(generator)
    
    async def get_personalized_suggestions(
        self,
        user_id: str,
        context: Optional[Dict[str, Any]] = None,
        max_suggestions: int = 10,
        suggestion_types: Optional[List[SuggestionType]] = None
    ) -> List[Suggestion]:
        """Get personalized suggestions for a user."""
        # Get user profile
        profile = await self.profile_manager.get_profile(user_id)
        if not profile:
            self.logger.warning(f"No profile found for user {user_id}")
            return []
        
        # Generate suggestions
        suggestions = await self.aggregator.generate_all_suggestions(
            profile, context, max_suggestions
        )
        
        # Filter by suggestion types if specified
        if suggestion_types:
            suggestions = [s for s in suggestions if s.suggestion_type in suggestion_types]
        
        # Apply personalization based on user preferences
        personalized_suggestions = await self._apply_personalization(
            suggestions, profile, context
        )
        
        self.logger.info(f"Generated {len(personalized_suggestions)} personalized suggestions for user {user_id}")
        return personalized_suggestions
    
    async def _apply_personalization(
        self,
        suggestions: List[Suggestion],
        profile: UserProfile,
        context: Optional[Dict[str, Any]]
    ) -> List[Suggestion]:
        """Apply personalization to suggestions based on user profile."""
        personalized = []
        
        for suggestion in suggestions:
            # Adjust relevance based on user preferences
            adjusted_suggestion = await self._adjust_suggestion_for_user(
                suggestion, profile, context
            )
            personalized.append(adjusted_suggestion)
        
        # Re-sort after personalization adjustments
        personalized.sort(key=lambda s: s.confidence_score, reverse=True)
        
        return personalized
    
    async def _adjust_suggestion_for_user(
        self,
        suggestion: Suggestion,
        profile: UserProfile,
        context: Optional[Dict[str, Any]]
    ) -> Suggestion:
        """Adjust a single suggestion based on user profile."""
        # Create a copy of the suggestion to modify
        adj_suggestion = Suggestion(
            suggestion_id=suggestion.suggestion_id,
            suggestion_type=suggestion.suggestion_type,
            title=suggestion.title,
            description=suggestion.description,
            confidence_score=suggestion.confidence_score,
            quality_rating=suggestion.quality_rating,
            relevance_score=suggestion.relevance_score,
            novelty_score=suggestion.novelty_score,
            context=suggestion.context,
            created_at=suggestion.created_at,
            expires_at=suggestion.expires_at,
            metadata=suggestion.metadata,
            tags=suggestion.tags
        )
        
        # Adjust relevance based on user preferences
        relevance_boost = 1.0
        
        # Check if suggestion aligns with user's preferred domains
        if "domain" in suggestion.context:
            domain = suggestion.context["domain"]
            if domain in profile.preferred_domains:
                relevance_boost *= 1.2  # 20% boost for preferred domains
        
        # Check if suggestion aligns with user's expertise level
        if "user_expertise" in suggestion.context:
            suggested_expertise = suggestion.context["user_expertise"]
            user_expertise = profile.expertise_level
            
            # Adjust based on expertise alignment
            expertise_levels = ["beginner", "intermediate", "advanced", "expert"]
            user_idx = expertise_levels.index(user_expertise) if user_expertise in expertise_levels else 1
            suggestion_idx = expertise_levels.index(suggested_expertise) if suggested_expertise in expertise_levels else 1
            
            # If suggestion is appropriately challenging (one level above) or matching
            if suggestion_idx == user_idx or suggestion_idx == user_idx + 1:
                relevance_boost *= 1.1  # 10% boost for appropriately challenging suggestions
        
        # Apply boost to relevance and confidence
        adj_suggestion.relevance_score = min(1.0, adj_suggestion.relevance_score * relevance_boost)
        adj_suggestion.confidence_score = min(1.0, (adj_suggestion.confidence_score + adj_suggestion.relevance_score) / 2)
        
        # Update quality rating based on new confidence
        adj_suggestion.quality_rating = self._score_to_quality(adj_suggestion.confidence_score)
        
        return adj_suggestion
    
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
    
    async def record_suggestion_interaction(
        self,
        user_id: str,
        suggestion_id: str,
        interaction_type: str,  # "viewed", "accepted", "rejected", "implemented"
        feedback: Optional[str] = None
    ):
        """Record user interaction with a suggestion for learning purposes."""
        # This would typically update user profile with feedback
        # For now, we'll just log the interaction
        self.logger.info(f"User {user_id} {interaction_type} suggestion {suggestion_id}")
        
        # In a full implementation, this would update the user's profile
        # to reflect their preferences based on their interaction with suggestions


class SuggestionTool:
    """Tool for generating personalized suggestions."""
    
    def __init__(self, suggestion_engine: PersonalizedSuggestionEngine):
        self.suggestion_engine = suggestion_engine
        self.logger = logging.getLogger(f"{__name__}.SuggestionTool")
    
    async def get_suggestions(
        self,
        user_id: str,
        context: Optional[Dict[str, Any]] = None,
        max_suggestions: int = 5
    ) -> Dict[str, Any]:
        """Get personalized suggestions for a user."""
        try:
            suggestions = await self.suggestion_engine.get_personalized_suggestions(
                user_id=user_id,
                context=context,
                max_suggestions=max_suggestions
            )
            
            # Format suggestions for output
            formatted_suggestions = []
            for suggestion in suggestions:
                formatted_suggestions.append({
                    "suggestion_id": suggestion.suggestion_id,
                    "type": suggestion.suggestion_type.value,
                    "title": suggestion.title,
                    "description": suggestion.description,
                    "confidence_score": suggestion.confidence_score,
                    "quality_rating": suggestion.quality_rating.value,
                    "relevance_score": suggestion.relevance_score,
                    "novelty_score": suggestion.novelty_score,
                    "context": suggestion.context,
                    "created_at": suggestion.created_at.isoformat(),
                    "tags": suggestion.tags
                })
            
            return {
                "user_id": user_id,
                "suggestions_count": len(formatted_suggestions),
                "suggestions": formatted_suggestions,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            self.logger.error(f"Error getting suggestions: {e}")
            return {
                "error": f"Error getting suggestions: {str(e)}",
                "user_id": user_id
            }
    
    async def record_interaction(
        self,
        user_id: str,
        suggestion_id: str,
        interaction_type: str,
        feedback: Optional[str] = None
    ) -> Dict[str, Any]:
        """Record user interaction with a suggestion."""
        try:
            await self.suggestion_engine.record_suggestion_interaction(
                user_id, suggestion_id, interaction_type, feedback
            )
            
            return {
                "success": True,
                "message": f"Recorded {interaction_type} interaction for suggestion {suggestion_id}",
                "user_id": user_id,
                "suggestion_id": suggestion_id
            }
        except Exception as e:
            self.logger.error(f"Error recording interaction: {e}")
            return {
                "error": f"Error recording interaction: {str(e)}",
                "user_id": user_id,
                "suggestion_id": suggestion_id
            }
    
    def to_param(self) -> Dict[str, Any]:
        """Convert to parameter format for tool registration."""
        return {
            "type": "function",
            "function": {
                "name": "get_personalized_suggestions",
                "description": "Get personalized suggestions based on user profile and context",
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
                        "max_suggestions": {
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
        # This example would require a profile manager
        # For demonstration, we'll create a simplified version
        
        # Create a basic suggestion engine
        from weebot.user_profile_model import InMemoryUserProfileStorage, UserProfileManager
        
        storage = InMemoryUserProfileStorage()
        profile_manager = UserProfileManager(storage)
        
        # Create a sample user profile
        user_profile = await profile_manager.create_profile(
            user_id="user_123",
            name="Jane Smith",
            email="jane@example.com"
        )
        
        # Add some preferences to the profile
        await profile_manager.update_preference(
            user_id="user_123",
            category=PreferenceCategory.CONTENT_PREFERENCES,
            key="preferred_domains",
            value=["technology", "research"]
        )
        
        # Create the suggestion engine
        suggestion_engine = PersonalizedSuggestionEngine(profile_manager)
        
        print("Generating personalized suggestions...")
        
        # Generate suggestions
        suggestions = await suggestion_engine.get_personalized_suggestions(
            user_id="user_123",
            context={
                "current_project": {
                    "name": "AI Research",
                    "description": "Researching latest AI developments"
                }
            },
            max_suggestions=5
        )
        
        print(f"\nGenerated {len(suggestions)} suggestions:")
        for i, suggestion in enumerate(suggestions, 1):
            print(f"\n{i}. {suggestion.title}")
            print(f"   Type: {suggestion.suggestion_type.value}")
            print(f"   Description: {suggestion.description}")
            print(f"   Confidence: {suggestion.confidence_score:.2f}")
            print(f"   Quality: {suggestion.quality_rating.value}")
            print(f"   Relevance: {suggestion.relevance_score:.2f}")
            print(f"   Tags: {suggestion.tags}")
        
        print("\nExample completed successfully!")
    
    asyncio.run(example())