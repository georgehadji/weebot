#!/usr/bin/env python3

# ═══════════════════════════════════════════════════════════════════════
# ⚠️ LEGACY — Frozen. No new features.
# Superseded by PlanActFlow / Session domain model.
# Target sunset: 2027-03-01
# ═══════════════════════════════════════════════════════════════════════
"""agent_core_v2.py - Enhanced Agent με όλες τις νέες δυνατότητες

Βελτιώσεις από v1:
------------------
1. Security integration (sandboxed execution)
2. Plugin system (extensible hooks)
3. Vector memory (RAG support)
4. Parallel task execution
5. Advanced error recovery
6. Cost optimization
7. Web dashboard integration
8. Enhanced natural language understanding
"""
import asyncio
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from .ai_router import ModelRouter, TaskType
from .notifications import NotificationManager
from .state_manager import StateManager, ResumableTask, ProjectStatus
from .nlp_understanding import NaturalLanguageProcessor, IntentRecognitionResult

logger = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    """Configuration for weebot Agent."""
    project_id: str
    description: str
    auto_resume: bool = True
    notification_channels: list = None
    daily_budget: float = 10.0
    max_retries: int = 3
    
    def __post_init__(self) -> None:
        if self.notification_channels is None:
            self.notification_channels = []


class WeebotAgent:
    """
    Advanced autonomous agent with:
    - Intelligent AI model selection
    - Multi-channel notifications
    - Resumable project execution
    - Cost optimization
    """
    
    def __init__(self, config: AgentConfig) -> None:
        import warnings
        warnings.warn(
            "WeebotAgent is deprecated; use AgentRunner from weebot.interfaces.cli.agent_runner",
            DeprecationWarning,
            stacklevel=2,
        )
        self.config = config
        self.router = ModelRouter(daily_budget=config.daily_budget)
        self.notifier = NotificationManager()
        self.state_manager = StateManager()
        self.tools = {}  # Registered tools
        self.nlp_processor = NaturalLanguageProcessor()  # Enhanced NLP capabilities

        # Load existing state or create new
        self.state = self.state_manager.load_state(config.project_id)
        if not self.state:
            self.state = self.state_manager.create_project(
                config.project_id, config.description
            )
    
    def register_tool(self, name: str, handler: Any) -> None:
        """Register a tool for the agent to use."""
        self.tools[name] = handler
    
    async def run(self, task_plan: List[Dict[str, Any]]) -> None:
        """Execute task plan with resume capability."""

        # Notify start
        await self.notifier.notify_project_start(
            self.config.project_id,
            self.config.description
        )
        
        try:
            for task in task_plan:
                task_name = task["name"]
                
                # Check if already completed
                if task_name in self.state.completed_tasks:
                    continue
                
                async with ResumableTask(
                    self.state_manager,
                    self.config.project_id,
                    task_name
                ) as task_ctx:
                    if task_ctx is None:
                        continue  # Already completed
                    
                    # Execute task
                    result = await self._execute_task(task)
                    
                    # Handle checkpoint if needed
                    if task.get("checkpoint"):
                        checkpoint_id = await task_ctx.checkpoint(
                            task.get("checkpoint_desc", "Review required"),
                            task.get("input_prompt", "Continue? (yes/no)")
                        )
                        
                        await self.notifier.notify_checkpoint(
                            self.config.project_id,
                            f"Checkpoint {checkpoint_id} requires input"
                        )
                        
                        # Wait for user input (in real implementation)
                        # For now, auto-resolve
                        self.state_manager.resolve_checkpoint(checkpoint_id, "yes")
            
            # Notify completion
            await self.notifier.notify_completion(
                self.config.project_id,
                f"All {len(task_plan)} tasks completed"
            )
            
        except Exception as e:
            await self.notifier.notify_error(
                self.config.project_id,
                str(e),
                critical=True
            )
            raise
    
    async def _execute_task(self, task: dict) -> dict:
        """Execute single task"""
        task_type = TaskType(task.get("type", "chat"))
        
        # Select optimal model
        model_id = self.router.select_model(
            task_type,
            budget_constraint=None
        )
        
        # Generate with AI
        prompt = task.get("prompt", "")
        result = await self.router.generate_with_fallback(
            prompt=prompt,
            task_type=task_type,
            use_cache=True
        )
        
        # Execute tool if specified
        if "tool" in task and task["tool"] in self.tools:
            tool_result = self.tools[task["tool"]](result["content"])
            return {"ai_result": result, "tool_result": tool_result}
        
        return result
    
    def get_status(self) -> Dict[str, Any]:
        """Get current agent status"""
        return {
            "status": self.state.status.value,
            "progress": len(self.state.completed_tasks),
            "current_task": self.state.current_task,
            "pending_checkpoints": len(
                self.state_manager.get_pending_checkpoints(self.config.project_id)
            ),
            "cost_stats": self.router.cost_tracker.get_stats()
        }

    def process_user_request(self, user_input: str) -> IntentRecognitionResult:
        """
        Process user request with enhanced natural language understanding.
        
        Args:
            user_input: Raw user input text
            
        Returns:
            Structured understanding of the user's request
        """
        return self.nlp_processor.process_user_request(user_input)

    async def handle_user_request(self, user_input: str) -> Dict[str, Any]:
        """
        Handle a user request from start to finish with enhanced understanding.
        
        Args:
            user_input: Natural language request from user
            
        Returns:
            Dictionary with response and execution details
        """
        # Process the request with enhanced understanding
        understanding = self.process_user_request(user_input)
        
        # Log the understanding for debugging
        logger.info(f"User request understanding: {understanding.intent.value} "
                   f"with confidence {understanding.confidence:.2f}")
        
        # Generate an appropriate response based on the intent
        response = await self._generate_response_for_intent(understanding, user_input)
        
        return {
            "understanding": understanding,
            "response": response,
            "success": True
        }

    async def _generate_response_for_intent(
        self, 
        understanding: IntentRecognitionResult, 
        original_request: str
    ) -> str:
        """
        Generate an appropriate response based on the understood intent.
        
        Args:
            understanding: The processed understanding of the user's request
            original_request: The original user request
            
        Returns:
            Generated response string
        """
        # For now, return a basic response based on intent
        # In a full implementation, this would connect to appropriate workflows
        responses = {
            "research": f"I understand you want me to research about {', '.join(understanding.entities.get('topic', ['this']))}. I'll create a research plan for you.",
            "analysis": f"I'll help analyze the data or topic you mentioned. I detected these entities: {', '.join(understanding.entities.values())}.",
            "task_execution": f"I'll execute the requested task. Keywords detected: {', '.join(understanding.keywords)}.",
            "information_request": f"I can provide information about that. I detected intent: {understanding.intent.value}.",
            "content_creation": f"I'll help create content based on your request. Detected action items: {', '.join(understanding.action_items)}.",
            "automation": f"I can help automate processes. I detected these potential automations: {', '.join(understanding.action_items)}.",
            "unknown": f"I received your request: '{original_request}'. I'm working on understanding it better."
        }
        
        return responses.get(understanding.intent.value, responses["unknown"])

    async def spawn_child_agent(
        self,
        role: str,
        description: Optional[str] = None,
        context: Optional[Any] = None
    ) -> "WeebotAgent":
        """Spawn a specialized child agent in a multi-agent workflow.

        Uses AgentFactory to create a new agent with role-based tool access.
        Requires multi-agent context support (see AgentContext).

        Args:
            role: Role/specialization of child agent (researcher, analyst, etc.)
            description: Optional description of the agent's purpose
            context: Optional AgentContext for sharing data with sibling agents

        Returns:
            Spawned WeebotAgent instance with role-based configuration

        Raises:
            ImportError: If multi-agent support not available
        """
        try:
            from weebot.core.agent_factory import AgentFactory
            from weebot.core.agent_context import AgentContext
        except ImportError as e:
            raise ImportError(
                "Multi-agent support requires agent_factory and agent_context modules"
            ) from e

        # Create root context if not provided
        if context is None:
            context = AgentContext.create_orchestrator(
                activity_stream=None,
            )

        # Use factory to spawn child
        factory = AgentFactory()
        child_agent = await factory.spawn_agent(
            parent_agent_id=self.config.project_id,
            parent_context=context,
            role=role,
            description=description
        )

        logger.info(
            f"Spawned child agent with role='{role}' from parent='{self.config.project_id}'"
        )

        return child_agent
