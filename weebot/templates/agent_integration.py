"""
Agent System Integration for Template Engine.

Connects template engine with Weebot's agent system including:
- AgentFactory for creating role-based agents
- WeebotAgent for task execution
- AgentContext for state management
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from weebot.templates.engine import ExecutionContext

# Import Weebot agent system
try:
    from weebot.agent_core_v2 import WeebotAgent, AgentConfig
    from weebot.core.agent_factory import AgentFactory
    from weebot.core.agent_context import AgentContext
    from weebot.core.agent_profile import AgentProfile
    HAS_AGENT_SYSTEM = True
except ImportError:
    HAS_AGENT_SYSTEM = False

_log = logging.getLogger(__name__)


class TemplateAgentManager:
    """
    Manages agent lifecycle for template execution.
    
    Features:
    - Create agents on-demand for template tasks
    - Cache and reuse agents by role
    - Handle agent context and state
    - Manage agent cleanup
    """
    
    # Role-to-profile mapping for template tasks
    ROLE_PROFILES = {
        "researcher": {
            "description": "Research specialist that gathers and analyzes information",
            "tools": ["web_search", "browser", "file_reader"],
        },
        "analyst": {
            "description": "Data analyst that processes and interprets information",
            "tools": ["calculator", "data_processor", "visualization"],
        },
        "writer": {
            "description": "Technical writer that creates documentation and reports",
            "tools": ["file_writer", "markdown_formatter"],
        },
        "reviewer": {
            "description": "Quality reviewer that checks work for accuracy",
            "tools": ["file_reader", "comparator"],
        },
        "developer": {
            "description": "Software developer that writes and modifies code",
            "tools": ["file_writer", "bash", "code_editor"],
        },
        "tester": {
            "description": "QA engineer that tests and validates solutions",
            "tools": ["test_runner", "bash", "file_reader"],
        },
        "default": {
            "description": "General purpose agent",
            "tools": ["web_search", "file_reader", "file_writer"],
        },
    }
    
    def __init__(self, agent_factory: Optional[AgentFactory] = None):
        """
        Initialize the agent manager.
        
        Args:
            agent_factory: Optional AgentFactory instance. If None, creates default.
        """
        if not HAS_AGENT_SYSTEM:
            raise RuntimeError("Agent system not available. Cannot create TemplateAgentManager.")
        
        self.agent_factory = agent_factory or AgentFactory()
        self._agent_cache: Dict[str, WeebotAgent] = {}
        self._parent_context: Optional[AgentContext] = None
    
    def set_parent_context(self, context: AgentContext) -> None:
        """Set the parent context for all spawned agents."""
        self._parent_context = context
    
    def get_or_create_agent(
        self,
        role: str,
        task_description: Optional[str] = None,
    ) -> WeebotAgent:
        """
        Get cached agent or create new one for role.
        
        Args:
            role: Agent role (e.g., "researcher", "analyst")
            task_description: Optional description for the agent
            
        Returns:
            WeebotAgent instance
        """
        # Check cache first
        if role in self._agent_cache:
            _log.debug(f"Using cached agent for role: {role}")
            return self._agent_cache[role]
        
        # Create new agent
        agent = self._create_agent_for_role(role, task_description)
        self._agent_cache[role] = agent
        return agent
    
    def _create_agent_for_role(
        self,
        role: str,
        task_description: Optional[str] = None,
    ) -> WeebotAgent:
        """Create a new agent configured for the specified role."""
        profile = self.ROLE_PROFILES.get(role, self.ROLE_PROFILES["default"])
        
        # Create agent configuration
        import uuid
        config = AgentConfig(
            project_id=f"template_{role}_{uuid.uuid4().hex[:8]}",
            description=task_description or profile["description"],
            auto_resume=False,
            daily_budget=5.0,  # Lower budget for template tasks
        )
        
        # Create agent
        agent = WeebotAgent(config=config)
        
        _log.info(f"Created agent for role: {role}")
        return agent
    
    def _get_system_prompt_for_role(self, role: str) -> str:
        """Get system prompt for agent role."""
        prompts = {
            "researcher": (
                "You are a research specialist. Your task is to gather, analyze, and synthesize "
                "information on given topics. Use web search and data analysis tools effectively. "
                "Provide comprehensive, well-sourced findings."
            ),
            "analyst": (
                "You are a data analyst. Your task is to process data, identify patterns, "
                "and derive insights. Use analytical tools and provide clear, actionable conclusions."
            ),
            "writer": (
                "You are a technical writer. Your task is to create clear, well-structured "
                "documentation and reports. Use proper formatting and ensure accuracy."
            ),
            "reviewer": (
                "You are a quality reviewer. Your task is to check work for accuracy, "
                "completeness, and quality. Provide constructive feedback."
            ),
            "developer": (
                "You are a software developer. Your task is to write, review, and modify code. "
                "Follow best practices and ensure code quality."
            ),
            "tester": (
                "You are a QA engineer. Your task is to test solutions and validate they meet "
                "requirements. Identify bugs and edge cases."
            ),
            "default": (
                "You are a helpful AI assistant executing workflow tasks. Use available tools "
                "effectively and provide clear, actionable results."
            ),
        }
        return prompts.get(role, prompts["default"])
    
    async def execute_task(
        self,
        role: str,
        task: str,
        context: Optional[ExecutionContext] = None,
    ) -> Dict[str, Any]:
        """
        Execute a task with an agent.
        
        Args:
            role: Agent role to use
            task: Task description
            context: Optional execution context
            
        Returns:
            Task execution result
        """
        try:
            agent = self.get_or_create_agent(role, task)
            
            # Create a simple task plan
            task_plan = [{
                "name": f"{role}_task",
                "type": "chat",
                "prompt": task,
            }]
            
            # Execute task plan
            await agent.run(task_plan)
            
            # Get status for results
            status = agent.get_status()
            
            return {
                "success": True,
                "agent_role": role,
                "task": task,
                "status": status,
            }
        except Exception as e:
            _log.exception(f"Agent task execution failed: {e}")
            return {
                "success": False,
                "agent_role": role,
                "task": task,
                "error": str(e),
            }
    
    def clear_cache(self) -> None:
        """Clear the agent cache."""
        self._agent_cache.clear()
        _log.info("Agent cache cleared")
    
    def get_agent_info(self) -> Dict[str, Any]:
        """Get information about managed agents."""
        return {
            "cached_agents": list(self._agent_cache.keys()),
            "available_roles": list(self.ROLE_PROFILES.keys()),
        }


class TemplateAgentTaskHandler:
    """
    Task handler that routes to actual Weebot agents.
    
    This is the bridge between template engine and agent system.
    """
    
    def __init__(self, agent_manager: Optional[TemplateAgentManager] = None):
        self.agent_manager = agent_manager
        self._simulation_mode = not HAS_AGENT_SYSTEM
        
        if not self._simulation_mode and self.agent_manager is None:
            self.agent_manager = TemplateAgentManager()
    
    async def handle_agent_task(
        self,
        task_def: Dict[str, Any],
        context: ExecutionContext,
    ) -> Dict[str, Any]:
        """
        Handle agent task execution.
        
        Args:
            task_def: Task definition with agent_role and task
            context: Execution context with resolved parameters
            
        Returns:
            Execution result
        """
        agent_role = task_def.get("agent_role", "default")
        task_description = task_def.get("task", "")
        
        _log.info(f"Executing agent task: {agent_role} - {task_description[:50]}...")
        
        if self._simulation_mode:
            # Simulation mode - no real agents
            return self._simulate_execution(agent_role, task_description)
        
        # Real agent execution
        return await self.agent_manager.execute_task(
            role=agent_role,
            task=task_description,
            context=context,
        )
    
    def _simulate_execution(
        self,
        role: str,
        task: str,
    ) -> Dict[str, Any]:
        """Simulate agent execution when real agents unavailable."""
        _log.warning(f"SIMULATION MODE: Agent task for role '{role}'")
        
        return {
            "success": True,
            "agent_role": role,
            "task": task,
            "result": {
                "status": "simulated",
                "message": f"Agent '{role}' would execute: {task}",
                "note": "Running in simulation mode - no real agents available",
            },
            "simulation": True,
        }
    
    def is_simulation_mode(self) -> bool:
        """Check if running in simulation mode."""
        return self._simulation_mode


def register_agent_handlers(engine, agent_manager: Optional[TemplateAgentManager] = None) -> None:
    """
    Register agent task handlers with template engine.
    
    Args:
        engine: TemplateEngine instance
        agent_manager: Optional TemplateAgentManager instance
    """
    handler = TemplateAgentTaskHandler(agent_manager)
    
    # Register the handler
    engine.register_task_handler("agent_task", handler.handle_agent_task)
    
    _log.info("Agent handlers registered with template engine")


# Convenience function for full setup
def create_agent_enabled_engine(
    load_builtin: bool = True,
    agent_manager: Optional[TemplateAgentManager] = None,
):
    """
    Create a template engine with full agent integration.
    
    Args:
        load_builtin: Whether to load built-in templates
        agent_manager: Optional agent manager instance
        
    Returns:
        Tuple of (TemplateEngine, TemplateAgentManager)
    """
    from weebot.templates import TemplateEngine
    
    engine = TemplateEngine()
    
    if load_builtin:
        engine.registry.load_builtin_templates()
    
    # Setup agent integration
    if agent_manager is None and HAS_AGENT_SYSTEM:
        agent_manager = TemplateAgentManager()
    
    if agent_manager:
        register_agent_handlers(engine, agent_manager)
    
    return engine, agent_manager
