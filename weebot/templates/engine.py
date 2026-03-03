"""Template execution engine."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TypeVar

from weebot.templates.parser import WorkflowTemplate, TemplateValidationError
from weebot.templates.parameters import ParameterResolver, ParameterValidationError
from weebot.templates.registry import TemplateRegistry

_log = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass
class TemplateExecutionResult:
    """Result of template execution."""
    success: bool
    template_name: str
    parameters: Dict[str, Any]
    output: Any = None
    error: Optional[str] = None
    execution_time_ms: Optional[float] = None
    task_results: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ExecutionContext:
    """Context for template execution."""
    template: WorkflowTemplate
    parameters: Dict[str, Any]
    variables: Dict[str, Any] = field(default_factory=dict)
    
    def resolve_template_string(self, template_str: str) -> str:
        """
        Resolve a template string with {{variable}} syntax.
        
        Args:
            template_str: String with {{parameter}} placeholders
            
        Returns:
            Resolved string with placeholders replaced
        """
        result = template_str
        
        # Replace parameters
        for name, value in self.parameters.items():
            placeholder = f"{{{{{name}}}}}"
            result = result.replace(placeholder, str(value))
        
        # Replace variables
        for name, value in self.variables.items():
            placeholder = f"{{{{{name}}}}}"
            result = result.replace(placeholder, str(value))
        
        return result


class TemplateEngine:
    """
    Main engine for executing workflow templates.
    
    Features:
    - Load and validate templates
    - Resolve parameters
    - Execute workflow tasks
    - Handle dependencies between tasks
    - Collect and return results
    """
    
    def __init__(self):
        self._registry = TemplateRegistry()
        self._resolver = ParameterResolver()
        self._task_handlers: Dict[str, Callable] = {}
    
    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    
    @property
    def registry(self) -> TemplateRegistry:
        """Access the template registry."""
        return self._registry
    
    # ------------------------------------------------------------------
    # Task Handlers
    # ------------------------------------------------------------------
    
    def register_task_handler(self, task_type: str, 
                              handler: Callable[[Dict[str, Any], ExecutionContext], Any]) -> None:
        """
        Register a handler for a task type.
        
        Args:
            task_type: Type identifier for the task (e.g., "agent_task", "web_search")
            handler: Function that executes the task
        """
        self._task_handlers[task_type] = handler
        _log.debug(f"Registered task handler: {task_type}")
    
    def has_task_handler(self, task_type: str) -> bool:
        """Check if a task handler is registered."""
        return task_type in self._task_handlers
    
    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    
    def execute(self, template_name: str, 
                parameters: Optional[Dict[str, Any]] = None,
                dry_run: bool = False) -> TemplateExecutionResult:
        """
        Execute a template by name with given parameters.
        
        Args:
            template_name: Name of registered template to execute
            parameters: Parameter values to use
            dry_run: If True, validate only without executing
            
        Returns:
            TemplateExecutionResult with success status and output
        """
        import time
        start_time = time.time()
        
        parameters = parameters or {}
        
        # Step 1: Get template
        template = self._registry.get(template_name)
        if not template:
            return TemplateExecutionResult(
                success=False,
                template_name=template_name,
                parameters=parameters,
                error=f"Template '{template_name}' not found in registry"
            )
        
        # Step 2: Resolve parameters
        try:
            resolved_params = self._resolver.resolve(template, parameters)
        except ParameterValidationError as e:
            return TemplateExecutionResult(
                success=False,
                template_name=template_name,
                parameters=parameters,
                error=f"Parameter validation failed: {e}"
            )
        
        # Step 3: Create execution context
        context = ExecutionContext(
            template=template,
            parameters=resolved_params
        )
        
        # Step 4: Dry run - just validate
        if dry_run:
            execution_time = (time.time() - start_time) * 1000
            return TemplateExecutionResult(
                success=True,
                template_name=template_name,
                parameters=resolved_params,
                output={"status": "validated", "tasks": list(template.workflow.keys())},
                execution_time_ms=round(execution_time, 2)
            )
        
        # Step 5: Execute workflow
        try:
            result = self._execute_workflow(template, context)
            execution_time = (time.time() - start_time) * 1000
            result.execution_time_ms = round(execution_time, 2)
            return result
        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            _log.exception(f"Template execution failed: {e}")
            return TemplateExecutionResult(
                success=False,
                template_name=template_name,
                parameters=resolved_params,
                error=f"Execution failed: {e}",
                execution_time_ms=round(execution_time, 2)
            )
    
    def execute_template(self, template: WorkflowTemplate,
                        parameters: Optional[Dict[str, Any]] = None,
                        dry_run: bool = False) -> TemplateExecutionResult:
        """
        Execute a template object directly (without registry lookup).
        
        Args:
            template: The workflow template to execute
            parameters: Parameter values to use
            dry_run: If True, validate only without executing
            
        Returns:
            TemplateExecutionResult with success status and output
        """
        # Temporarily register the template
        temp_name = f"__temp_{template.name}"
        
        # Check if already registered with this name
        existing = self._registry.get(temp_name)
        if existing:
            self._registry.unregister(temp_name)
        
        # Create a copy with temp name to avoid conflicts
        from dataclasses import replace
        temp_template = replace(template, name=temp_name)
        
        try:
            self._registry.register(temp_template)
            return self.execute(temp_name, parameters, dry_run)
        finally:
            self._registry.unregister(temp_name)
    
    def validate(self, template_name: str, 
                 parameters: Optional[Dict[str, Any]] = None) -> List[str]:
        """
        Validate a template execution without running it.
        
        Args:
            template_name: Name of template to validate
            parameters: Parameters to validate
            
        Returns:
            List of validation error messages (empty if valid)
        """
        parameters = parameters or {}
        errors = []
        
        # Check template exists
        template = self._registry.get(template_name)
        if not template:
            return [f"Template '{template_name}' not found"]
        
        # Validate parameters
        param_errors = self._resolver.validate_only(template, parameters)
        errors.extend(param_errors)
        
        # Check for task handler availability
        for task_id, task_def in template.workflow.items():
            task_type = task_def.get("type", "agent_task")
            if not self.has_task_handler(task_type):
                errors.append(f"Task '{task_id}': No handler registered for type '{task_type}'")
        
        return errors
    
    def _execute_workflow(self, template: WorkflowTemplate, 
                         context: ExecutionContext) -> TemplateExecutionResult:
        """
        Execute the workflow tasks.
        
        This is a simplified sequential executor.
        In production, this would use the workflow orchestrator for parallel execution.
        """
        task_results = []
        variables = {}
        
        for task_id, task_def in template.workflow.items():
            _log.debug(f"Executing task: {task_id}")
            
            # Resolve template strings in task definition
            resolved_def = self._resolve_task_definition(task_def, context)
            
            # Get task type
            task_type = resolved_def.get("type", "agent_task")
            
            # Execute task
            if task_type in self._task_handlers:
                handler = self._task_handlers[task_type]
                try:
                    result = handler(resolved_def, context)
                    task_results.append({
                        "task_id": task_id,
                        "success": True,
                        "result": result
                    })
                    # Store result as variable for later tasks
                    variables[task_id] = result
                except Exception as e:
                    task_results.append({
                        "task_id": task_id,
                        "success": False,
                        "error": str(e)
                    })
                    # Continue with other tasks for now
            else:
                # No handler - simulate execution
                task_results.append({
                    "task_id": task_id,
                    "success": True,
                    "result": {"status": "simulated", "task": task_id},
                    "note": f"No handler for type '{task_type}'"
                })
                variables[task_id] = {"status": "simulated"}
        
        # Build output
        output = self._build_output(template, context, variables)
        
        # Check if any task failed
        all_success = all(r["success"] for r in task_results)
        
        return TemplateExecutionResult(
            success=all_success,
            template_name=template.name,
            parameters=context.parameters,
            output=output,
            task_results=task_results
        )
    
    def _resolve_task_definition(self, task_def: Dict[str, Any], 
                                  context: ExecutionContext) -> Dict[str, Any]:
        """Resolve template strings in task definition."""
        resolved = {}
        
        for key, value in task_def.items():
            if isinstance(value, str):
                resolved[key] = context.resolve_template_string(value)
            elif isinstance(value, dict):
                resolved[key] = self._resolve_task_definition(value, context)
            elif isinstance(value, list):
                resolved[key] = [
                    context.resolve_template_string(item) if isinstance(item, str) else item
                    for item in value
                ]
            else:
                resolved[key] = value
        
        return resolved
    
    def _build_output(self, template: WorkflowTemplate, 
                     context: ExecutionContext,
                     variables: Dict[str, Any]) -> Dict[str, Any]:
        """Build the final output based on template output definition."""
        if not template.output:
            return {"variables": variables}
        
        output = {}
        
        for key, value in template.output.items():
            if isinstance(value, str):
                output[key] = context.resolve_template_string(value)
            else:
                output[key] = value
        
        return output
    
    # ------------------------------------------------------------------
    # Convenience Methods
    # ------------------------------------------------------------------
    
    def quick_execute(self, template_yaml: str, 
                      parameters: Optional[Dict[str, Any]] = None) -> TemplateExecutionResult:
        """
        Quick execution from YAML string without registry.
        
        Args:
            template_yaml: YAML template content
            parameters: Parameter values
            
        Returns:
            Execution result
        """
        from weebot.templates.parser import TemplateParser
        
        parser = TemplateParser()
        template = parser.parse(template_yaml)
        
        return self.execute_template(template, parameters)
