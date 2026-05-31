"""
Intelligent Agent Selection System for Weebot

This module provides intelligent agent selection capabilities
based on task requirements, user intent, and context.
"""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import re
from weebot.nlp_understanding import IntentRecognitionResult, IntentType
from weebot.workflow_planner import PlannedTask, TaskCategory
from weebot.core.agent_factory import AgentFactory
from weebot.core.agent_context import AgentContext


class AgentRole(Enum):
    """Roles that agents can specialize in."""
    RESEARCHER = "researcher"
    ANALYST = "analyst"
    WRITER = "writer"
    DEVELOPER = "developer"
    AUTOMATOR = "automator"
    COORDINATOR = "coordinator"
    SPECIALIST = "specialist"
    GENERALIST = "generalist"


@dataclass
class AgentProfile:
    """Profile of an agent with capabilities and expertise."""
    role: AgentRole
    expertise: List[str]  # Domains of expertise
    tools: List[str]  # Available tools
    experience_score: float  # 0.0 to 1.0
    availability: bool  # Whether the agent is available
    success_rate: float  # Historical success rate for similar tasks


class AgentSelector:
    """
    Intelligent selector that chooses the best agent for a task.
    
    Considers task requirements, user intent, and available agents
    to make optimal assignment decisions.
    """
    
    def __init__(self, agent_factory: AgentFactory):
        self.agent_factory = agent_factory
        self.agent_profiles: Dict[str, AgentProfile] = {}
        
        # Define role capabilities mapping
        self.role_capabilities = {
            AgentRole.RESEARCHER: {
                "categories": [TaskCategory.RESEARCH],
                "tools": ["web_search", "advanced_browser", "web_scraper"],
                "keywords": ["research", "find", "investigate", "explore", "discover", "analyze"]
            },
            AgentRole.ANALYST: {
                "categories": [TaskCategory.DATA_ANALYSIS],
                "tools": ["python_tool", "advanced_browser", "file_editor"],
                "keywords": ["analyze", "data", "statistics", "report", "metrics", "evaluate"]
            },
            AgentRole.WRITER: {
                "categories": [TaskCategory.CONTENT_CREATION],
                "tools": ["file_editor", "outline", "summarize"],
                "keywords": ["write", "create", "draft", "compose", "document", "blog"]
            },
            AgentRole.DEVELOPER: {
                "categories": [TaskCategory.OTHER],
                "tools": ["bash_tool", "python_tool", "file_editor"],
                "keywords": ["code", "develop", "program", "script", "implement"]
            },
            AgentRole.AUTOMATOR: {
                "categories": [TaskCategory.SYSTEM_AUTOMATION],
                "tools": ["bash_tool", "python_tool", "scheduler"],
                "keywords": ["automate", "schedule", "workflow", "process", "routine"]
            },
            AgentRole.COORDINATOR: {
                "categories": [TaskCategory.PLANNING],
                "tools": ["planning", "scheduler", "notification"],
                "keywords": ["plan", "organize", "coordinate", "schedule", "manage"]
            },
            AgentRole.SPECIALIST: {
                "categories": [TaskCategory.OTHER],
                "tools": ["web_search", "python_tool", "advanced_browser", "file_editor"],
                "keywords": ["specialize", "expert", "domain", "knowledge"]
            },
            AgentRole.GENERALIST: {
                "categories": [TaskCategory.OTHER],
                "tools": ["web_search", "python_tool", "bash_tool", "file_editor", "advanced_browser"],
                "keywords": ["general", "various", "multiple", "diverse"]
            }
        }
    
    def register_agent_profile(self, agent_id: str, profile: AgentProfile):
        """Register an agent profile for selection consideration."""
        self.agent_profiles[agent_id] = profile
    
    def select_best_agent_for_task(
        self,
        task: PlannedTask,
        intent_result: Optional[IntentRecognitionResult] = None,
        context: Optional[AgentContext] = None
    ) -> Optional[Tuple[str, AgentProfile]]:
        """
        Select the best agent for a specific task.
        
        Args:
            task: The task to assign
            intent_result: Optional intent analysis for additional context
            context: Optional agent context for hierarchical considerations
            
        Returns:
            Tuple of (agent_id, agent_profile) or None if no suitable agent found
        """
        # Calculate scores for each available agent
        scored_agents = []
        
        for agent_id, profile in self.agent_profiles.items():
            if not profile.availability:
                continue
                
            score = self._calculate_agent_score(task, profile, intent_result)
            if score > 0:  # Only consider agents with positive scores
                scored_agents.append((agent_id, profile, score))
        
        # Sort by score (highest first)
        scored_agents.sort(key=lambda x: x[2], reverse=True)
        
        if scored_agents:
            agent_id, profile, score = scored_agents[0]
            return agent_id, profile
        
        # If no registered agents are suitable, try to infer the best role
        best_role = self._infer_best_role(task, intent_result)
        if best_role:
            # Return the role as a recommendation
            dummy_profile = AgentProfile(
                role=best_role,
                expertise=["general"],
                tools=self.role_capabilities[best_role]["tools"],
                experience_score=0.5,
                availability=True,
                success_rate=0.7
            )
            return "recommended", dummy_profile
        
        return None
    
    def _calculate_agent_score(
        self,
        task: PlannedTask,
        profile: AgentProfile,
        intent_result: Optional[IntentRecognitionResult] = None
    ) -> float:
        """
        Calculate a suitability score for an agent to perform a task.
        
        Args:
            task: The task to be performed
            profile: The agent's profile
            intent_result: Optional intent analysis
            
        Returns:
            Score between 0.0 and 1.0 representing suitability
        """
        score = 0.0
        
        # Check category match
        if task.category in self.role_capabilities.get(profile.role, {}).get("categories", []):
            score += 0.3
        
        # Check tool availability
        required_tools = set(task.required_tools)
        available_tools = set(profile.tools)
        if required_tools.issubset(available_tools):
            score += 0.3
        else:
            # Partial match - score based on how many tools are available
            overlap = len(required_tools.intersection(available_tools))
            score += 0.3 * (overlap / len(required_tools)) if required_tools else 0.3
        
        # Check keyword relevance
        if intent_result:
            keywords = self.role_capabilities.get(profile.role, {}).get("keywords", [])
            intent_keywords = intent_result.keywords
            if intent_keywords:
                matching_keywords = [kw for kw in intent_keywords if 
                                   any(kw.lower() in keyword.lower() for keyword in keywords)]
                score += 0.2 * (len(matching_keywords) / len(intent_keywords))
        
        # Apply experience and success rate multipliers
        score *= profile.experience_score
        score *= profile.success_rate
        
        # Ensure score is between 0 and 1
        return min(1.0, max(0.0, score))
    
    def _infer_best_role(
        self,
        task: PlannedTask,
        intent_result: Optional[IntentRecognitionResult] = None
    ) -> Optional[AgentRole]:
        """
        Infer the best agent role for a task based on its characteristics.
        
        Args:
            task: The task to assign
            intent_result: Optional intent analysis
            
        Returns:
            Best matching AgentRole or None
        """
        # Score each role based on task characteristics
        role_scores = {}
        
        for role, capabilities in self.role_capabilities.items():
            score = 0.0
            
            # Category match
            if task.category in capabilities["categories"]:
                score += 0.4
            
            # Tool match
            required_tools = set(task.required_tools)
            available_tools = set(capabilities["tools"])
            if required_tools.issubset(available_tools):
                score += 0.3
            else:
                overlap = len(required_tools.intersection(available_tools))
                score += 0.3 * (overlap / len(required_tools)) if required_tools else 0.3
            
            # Keyword match if intent is available
            if intent_result:
                keywords = capabilities["keywords"]
                intent_keywords = intent_result.keywords
                if intent_keywords:
                    matching_keywords = [kw for kw in intent_keywords if 
                                       any(kw.lower() in keyword.lower() for keyword in keywords)]
                    score += 0.3 * (len(matching_keywords) / len(intent_keywords))
            
            role_scores[role] = score
        
        # Return the role with the highest score, if it meets minimum threshold
        best_role = max(role_scores.keys(), key=lambda r: role_scores[r])
        if role_scores[best_role] > 0.3:  # Minimum threshold for recommendation
            return best_role
        
        # Default to generalist if no role meets threshold
        return AgentRole.GENERALIST
    
    async def create_agent_for_task(
        self,
        parent_context: AgentContext,
        parent_agent_id: str,
        task: PlannedTask,
        intent_result: Optional[IntentRecognitionResult] = None
    ) -> Optional[Tuple[str, 'WeebotAgent']]:
        """
        Create or select an appropriate agent for a specific task.
        
        Args:
            parent_context: Context of the parent agent
            parent_agent_id: ID of the parent agent
            task: The task to assign
            intent_result: Optional intent analysis
            
        Returns:
            Tuple of (agent_id, agent_instance) or None if creation failed
        """
        # First, try to select an existing agent
        selection_result = self.select_best_agent_for_task(task, intent_result)
        
        if selection_result:
            agent_id, profile = selection_result
            
            if agent_id == "recommended":
                # Create a new agent with the recommended role
                agent = await self.agent_factory.spawn_agent(
                    parent_agent_id=parent_agent_id,
                    parent_context=parent_context,
                    role=profile.role.value,
                    description=f"Specialized agent for {task.name}: {task.description}"
                )
                
                # Register the new agent's profile
                new_profile = AgentProfile(
                    role=profile.role,
                    expertise=[task.category.value],
                    tools=profile.tools,
                    experience_score=0.5,  # New agent starts with moderate experience
                    availability=True,
                    success_rate=0.7  # Assume decent initial success rate
                )
                
                agent_key = f"dynamic_{profile.role.value}_{len(self.agent_profiles)}"
                self.register_agent_profile(agent_key, new_profile)
                
                return agent_key, agent
            else:
                # For now, we'll create a new agent based on the profile
                # In a full implementation, this would reuse existing agents
                agent = await self.agent_factory.spawn_agent(
                    parent_agent_id=parent_agent_id,
                    parent_context=parent_context,
                    role=profile.role.value,
                    description=f"Assigned agent for {task.name}: {task.description}"
                )
                
                return agent_id, agent
        
        # If no suitable agent found, create a generalist
        agent = await self.agent_factory.spawn_agent(
            parent_agent_id=parent_agent_id,
            parent_context=parent_context,
            role=AgentRole.GENERALIST.value,
            description=f"Generalist agent for {task.name}: {task.description}"
        )
        
        return "generalist", agent


# Example usage
if __name__ == "__main__":
    from weebot.nlp_understanding import NaturalLanguageProcessor
    from weebot.workflow_planner import WorkflowPlanner, TaskCategory
    
    # Create dependencies
    processor = NaturalLanguageProcessor()
    factory = AgentFactory()
    selector = AgentSelector(factory)
    
    # Register some example agent profiles
    researcher_profile = AgentProfile(
        role=AgentRole.RESEARCHER,
        expertise=["web_research", "data_collection"],
        tools=["web_search", "advanced_browser", "web_scraper"],
        experience_score=0.8,
        availability=True,
        success_rate=0.85
    )
    selector.register_agent_profile("researcher_1", researcher_profile)
    
    analyst_profile = AgentProfile(
        role=AgentRole.ANALYST,
        expertise=["data_analysis", "visualization"],
        tools=["python_tool", "advanced_browser", "file_editor"],
        experience_score=0.9,
        availability=True,
        success_rate=0.90
    )
    selector.register_agent_profile("analyst_1", analyst_profile)
    
    writer_profile = AgentProfile(
        role=AgentRole.WRITER,
        expertise=["content_creation", "documentation"],
        tools=["file_editor", "outline", "summarize"],
        experience_score=0.7,
        availability=True,
        success_rate=0.75
    )
    selector.register_agent_profile("writer_1", writer_profile)
    
    # Test with a sample task
    from weebot.workflow_planner import PlannedTask
    
    task = PlannedTask(
        id="task_1",
        name="research_trends",
        description="Research the latest trends in AI",
        category=TaskCategory.RESEARCH,
        required_tools=["web_search", "advanced_browser"],
        dependencies=[],
        estimated_duration_minutes=30,
        priority=1,
        parameters={"query": "AI trends 2026"}
    )
    
    # Process a sample request to get intent
    intent_result = processor.process_user_request("I need to research the latest trends in AI")
    
    # Select the best agent for the task
    result = selector.select_best_agent_for_task(task, intent_result)
    
    if result:
        agent_id, profile = result
        print(f"Best agent for task: {agent_id}")
        print(f"Role: {profile.role.value}")
        print(f"Expertise: {profile.expertise}")
        print(f"Tools: {profile.tools}")
        print(f"Experience: {profile.experience_score}")
        print(f"Success rate: {profile.success_rate}")
    else:
        print("No suitable agent found")
    
    # Test agent creation
    print("\nTesting agent creation...")
    # Create a mock parent context for testing
    parent_context = AgentContext.create_orchestrator()
    result = selector.create_agent_for_task(
        parent_context=parent_context,
        parent_agent_id="parent_1",
        task=task,
        intent_result=intent_result
    )
    print(f"Agent creation result: {result}")