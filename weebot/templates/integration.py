"""
Integration between Template Engine and Weebot core systems.

Connects the Template Engine with:
- WorkflowOrchestrator for multi-agent execution
- Agent system for task execution
- Tool system for tool-based tasks
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from weebot.templates.engine import TemplateEngine, ExecutionContext
from weebot.templates.parser import WorkflowTemplate

# Import core systems (may not be available in all environments)
try:
    from weebot.core.workflow_orchestrator import WorkflowOrchestrator, TaskStatus
    from weebot.core.circuit_breaker import CircuitBreaker
    HAS_ORCHESTRATOR = True
except ImportError:
    HAS_ORCHESTRATOR = False

try:
    from weebot.flow.agent_manager import AgentManager
    HAS_AGENT_MANAGER = True
except ImportError:
    HAS_AGENT_MANAGER = False

try:
    from weebot.tools.tool_registry import ToolRegistry
    HAS_TOOL_REGISTRY = True
except ImportError:
    HAS_TOOL_REGISTRY = False

_log = logging.getLogger(__name__)


class TemplateOrchestratorIntegration:
    """
    Integrates Template Engine with WorkflowOrchestrator.
    
    Enables templates to be executed as multi-agent workflows
    with proper dependency management and parallel execution.
    """
    
    def __init__(
        self,
        engine: TemplateEngine,
        orchestrator: Optional[Any] = None,
        agent_manager: Optional[Any] = None,
    ):
        self.engine = engine
        self.orchestrator = orchestrator
        self.agent_manager = agent_manager
        
        # Create default orchestrator if not provided
        if self.orchestrator is None and HAS_ORCHESTRATOR:
            self.orchestrator = WorkflowOrchestrator()
        
        # Create default agent manager if not provided
        if self.agent_manager is None and HAS_AGENT_MANAGER:
            self.agent_manager = AgentManager()
        
        # Register task handlers
        self._register_default_handlers()
    
    def _register_default_handlers(self) -> None:
        """Register default task handlers with the engine."""
        # Agent task handler
        self.engine.register_task_handler("agent_task", self._handle_agent_task)
        
        # Tool task handler
        self.engine.register_task_handler("tool_task", self._handle_tool_task)
        
        # Parallel task handler (uses orchestrator)
        self.engine.register_task_handler("parallel_tasks", self._handle_parallel_tasks)
    
    def _handle_agent_task(
        self, 
        task_def: Dict[str, Any], 
        context: ExecutionContext
    ) -> Dict[str, Any]:
        """
        Handle agent task execution.
        
        Args:
            task_def: Task definition from template
            context: Execution context with resolved parameters
            
        Returns:
            Task execution result
        """
        agent_role = task_def.get("agent_role", "default")
        task_description = task_def.get("task", "")
        
        _log.info(f"Executing agent task: {agent_role} - {task_description[:50]}...")
        
        # Try to use new agent integration if available
        try:
            from weebot.templates.agent_integration import TemplateAgentTaskHandler
            handler = TemplateAgentTaskHandler()
            
            # Run async handler
            import asyncio
            try:
                # Try to get existing event loop
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We're in an async context, create task
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        future = pool.submit(
                            asyncio.run,
                            handler.handle_agent_task(task_def, context)
                        )
                        return future.result()
                else:
                    return loop.run_until_complete(
                        handler.handle_agent_task(task_def, context)
                    )
            except RuntimeError:
                # No event loop, use asyncio.run
                return asyncio.run(handler.handle_agent_task(task_def, context))
                
        except (ImportError, RuntimeError) as e:
            _log.debug(f"New agent integration not available: {e}")
            # Fall back to old behavior
            return self._handle_agent_task_legacy(task_def, context)
    
    def _handle_agent_task_legacy(
        self, 
        task_def: Dict[str, Any], 
        context: ExecutionContext
    ) -> Dict[str, Any]:
        """Legacy agent task handler for fallback."""
        agent_role = task_def.get("agent_role", "default")
        task_description = task_def.get("task", "")
        
        # If we have an agent manager, use it
        if self.agent_manager:
            try:
                # Get or create agent for role
                agent = self._get_agent_for_role(agent_role)
                
                # Execute task
                result = agent.execute(task_description)
                
                return {
                    "success": True,
                    "agent_role": agent_role,
                    "task": task_description,
                    "result": result,
                }
            except Exception as e:
                _log.exception(f"Agent task failed: {e}")
                return {
                    "success": False,
                    "agent_role": agent_role,
                    "task": task_description,
                    "error": str(e),
                }
        else:
            # Simulate execution when no agent manager available
            return {
                "success": True,
                "agent_role": agent_role,
                "task": task_description,
                "result": f"[Simulated] Agent '{agent_role}' executed: {task_description}",
                "note": "No AgentManager available - simulated execution",
            }
    
    def _handle_tool_task(
        self,
        task_def: Dict[str, Any],
        context: ExecutionContext
    ) -> Dict[str, Any]:
        """
        Handle tool-based task execution.
        
        Args:
            task_def: Task definition with tool name and parameters
            context: Execution context
            
        Returns:
            Tool execution result
        """
        tool_name = task_def.get("tool")
        tool_params = task_def.get("parameters", {})
        
        _log.info(f"Executing tool: {tool_name}")
        
        if HAS_TOOL_REGISTRY:
            try:
                # Get tool from registry
                tool = ToolRegistry.get_tool(tool_name)
                
                # Execute tool
                result = tool.execute(**tool_params)
                
                return {
                    "success": result.success if hasattr(result, 'success') else True,
                    "tool": tool_name,
                    "result": result,
                }
            except Exception as e:
                _log.exception(f"Tool execution failed: {e}")
                return {
                    "success": False,
                    "tool": tool_name,
                    "error": str(e),
                }
        else:
            return {
                "success": True,
                "tool": tool_name,
                "result": f"[Simulated] Tool '{tool_name}' executed",
                "note": "No ToolRegistry available - simulated execution",
            }
    
    def _handle_parallel_tasks(
        self,
        task_def: Dict[str, Any],
        context: ExecutionContext
    ) -> Dict[str, Any]:
        """
        Handle parallel task execution using orchestrator.
        
        Args:
            task_def: Definition with subtasks to execute in parallel
            context: Execution context
            
        Returns:
            Combined results from all parallel tasks
        """
        subtasks = task_def.get("subtasks", [])
        
        if not subtasks:
            return {"success": True, "results": []}
        
        _log.info(f"Executing {len(subtasks)} parallel tasks")
        
        if self.orchestrator and HAS_ORCHESTRATOR:
            # Build task graph for orchestrator
            task_graph = {}
            for i, subtask in enumerate(subtasks):
                task_id = subtask.get("id", f"parallel_task_{i}")
                task_graph[task_id] = {
                    "agent_role": subtask.get("agent_role", "default"),
                    "task": subtask.get("task", ""),
                    "dependencies": subtask.get("depends_on", []),
                }
            
            # Execute via orchestrator
            try:
                workflow_result = asyncio.run(
                    self.orchestrator.execute(task_graph)
                )
                
                return {
                    "success": workflow_result.success,
                    "task_results": workflow_result.task_results,
                    "execution_time_ms": workflow_result.execution_time_ms,
                }
            except Exception as e:
                _log.exception(f"Parallel execution failed: {e}")
                return {
                    "success": False,
                    "error": str(e),
                }
        else:
            # Sequential fallback
            results = []
            for subtask in subtasks:
                result = self._handle_agent_task(subtask, context)
                results.append(result)
            
            return {
                "success": all(r.get("success", True) for r in results),
                "results": results,
                "note": "Sequential execution (no orchestrator available)",
            }
    
    def _get_agent_for_role(self, role: str) -> Any:
        """Get or create an agent for the specified role."""
        if not self.agent_manager:
            raise RuntimeError("No AgentManager available")
        
        # Try to get existing agent
        agent = self.agent_manager.get_agent(role)
        if agent:
            return agent
        
        # Create new agent for role
        return self.agent_manager.create_agent(role=role)
    
    def execute_workflow_template(
        self,
        template_name: str,
        parameters: Optional[Dict[str, Any]] = None,
        use_orchestrator: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute a workflow template with full orchestrator integration.
        
        Args:
            template_name: Name of registered template
            parameters: Template parameters
            use_orchestrator: Whether to use orchestrator for parallel execution
            
        Returns:
            Execution result with workflow details
        """
        parameters = parameters or {}
        
        # Get template
        template = self.engine.registry.get(template_name)
        if not template:
            return {
                "success": False,
                "error": f"Template '{template_name}' not found",
            }
        
        # If using orchestrator and template has complex dependencies
        if use_orchestrator and self.orchestrator and HAS_ORCHESTRATOR:
            return self._execute_with_orchestrator(template, parameters)
        else:
            # Use standard engine execution
            return self.engine.execute(template_name, parameters)
    
    def _execute_with_orchestrator(
        self,
        template: WorkflowTemplate,
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute template using WorkflowOrchestrator.
        
        This enables true parallel execution of independent tasks.
        """
        from weebot.templates.parameters import ParameterResolver
        
        # Resolve parameters
        resolver = ParameterResolver()
        try:
            resolved_params = resolver.resolve(template, parameters)
        except Exception as e:
            return {
                "success": False,
                "error": f"Parameter resolution failed: {e}",
            }
        
        # Build task graph from template workflow
        task_graph = {}
        for task_id, task_def in template.workflow.items():
            # Resolve template strings in task definition
            resolved_def = self._resolve_template_in_dict(task_def, resolved_params)
            
            task_graph[task_id] = {
                "agent_role": resolved_def.get("agent_role", "default"),
                "task": resolved_def.get("task", ""),
                "dependencies": resolved_def.get("depends_on", []),
                "type": resolved_def.get("type", "agent_task"),
            }
        
        # Execute via orchestrator
        try:
            workflow_result = asyncio.run(
                self.orchestrator.execute(task_graph)
            )
            
            return {
                "success": workflow_result.success,
                "template_name": template.name,
                "parameters": resolved_params,
                "task_results": workflow_result.task_results,
                "execution_time_ms": workflow_result.execution_time_ms,
                "parallel_tasks": len(task_graph),
            }
        except Exception as e:
            _log.exception(f"Orchestrator execution failed: {e}")
            return {
                "success": False,
                "error": f"Execution failed: {e}",
            }
    
    def _resolve_template_in_dict(
        self,
        data: Dict[str, Any],
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Resolve {{parameter}} placeholders in dictionary values."""
        resolved = {}
        for key, value in data.items():
            if isinstance(value, str):
                # Replace {{param}} with actual value
                resolved_value = value
                for param_name, param_value in parameters.items():
                    placeholder = f"{{{{{param_name}}}}}"
                    resolved_value = resolved_value.replace(
                        placeholder, str(param_value)
                    )
                resolved[key] = resolved_value
            elif isinstance(value, dict):
                resolved[key] = self._resolve_template_in_dict(value, parameters)
            elif isinstance(value, list):
                resolved_list = []
                for item in value:
                    if isinstance(item, str):
                        resolved_item = item
                        for param_name, param_value in parameters.items():
                            placeholder = f"{{{{{param_name}}}}}"
                            resolved_item = resolved_item.replace(
                                placeholder, str(param_value)
                            )
                        resolved_list.append(resolved_item)
                    else:
                        resolved_list.append(item)
                resolved[key] = resolved_list
            else:
                resolved[key] = value
        return resolved


class TemplateCLI:
    """
    Command-line interface for template execution.
    
    Provides easy CLI access to template functionality.
    """
    
    def __init__(self, integration: Optional[TemplateOrchestratorIntegration] = None):
        self.integration = integration or self._create_default_integration()
    
    def _create_default_integration(self) -> TemplateOrchestratorIntegration:
        """Create default integration with new engine."""
        engine = TemplateEngine()
        engine.registry.load_builtin_templates()
        return TemplateOrchestratorIntegration(engine)
    
    def list_templates(self) -> List[str]:
        """List all available templates."""
        return self.integration.engine.registry.list_templates()
    
    def show_template(self, name: str) -> Optional[Dict[str, Any]]:
        """Show template details."""
        return self.integration.engine.registry.get_metadata(name)
    
    def execute(
        self,
        template_name: str,
        parameters: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute a template.
        
        Args:
            template_name: Name of template to execute
            parameters: Template parameters
            dry_run: If True, validate only
            
        Returns:
            Execution result
        """
        if dry_run:
            return self.integration.engine.execute(
                template_name, parameters, dry_run=True
            )
        else:
            return self.integration.execute_workflow_template(
                template_name, parameters
            )
    
    def validate(self, template_name: str, parameters: Optional[Dict[str, Any]] = None) -> List[str]:
        """Validate template execution."""
        return self.integration.engine.validate(template_name, parameters)


def create_integrated_engine(
    load_builtin: bool = True,
    use_orchestrator: bool = True,
) -> TemplateOrchestratorIntegration:
    """
    Factory function to create a fully integrated template engine.
    
    Args:
        load_builtin: Whether to load built-in templates
        use_orchestrator: Whether to integrate with WorkflowOrchestrator
        
    Returns:
        Configured TemplateOrchestratorIntegration
    """
    engine = TemplateEngine()
    
    if load_builtin:
        engine.registry.load_builtin_templates()
    
    # Create integration with optional orchestrator
    orchestrator = None
    if use_orchestrator and HAS_ORCHESTRATOR:
        orchestrator = WorkflowOrchestrator()
    
    integration = TemplateOrchestratorIntegration(
        engine=engine,
        orchestrator=orchestrator,
    )
    
    return integration
