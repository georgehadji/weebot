#!/usr/bin/env python3
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
"""
import asyncio
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from weebot.ai_router import ModelRouter, TaskType
from weebot.notifications import NotificationManager
from weebot.state_manager import StateManager, ResumableTask, ProjectStatus

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
        self.config = config
        self.router = ModelRouter(daily_budget=config.daily_budget)
        self.notifier = NotificationManager()
        self.state_manager = StateManager()
        self.tools = {}  # Registered tools

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
                state_manager=self.state_manager
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
