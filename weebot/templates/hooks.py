"""
Custom Hooks for Template Execution.

Features:
- Pre-execution hooks
- Post-execution hooks
- Conditional hooks
- Hook registry
- Built-in hooks
"""
from __future__ import annotations

import functools
import inspect
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, TypeVar

from weebot.templates.engine import (
    TemplateEngine,
    ExecutionContext,
    TemplateExecutionResult,
)

_log = logging.getLogger(__name__)

T = TypeVar('T')
HookFunction = Callable[..., Any]


@dataclass
class Hook:
    """Represents a registered hook."""
    name: str
    function: HookFunction
    priority: int = 0
    condition: Optional[Callable] = None
    async_support: bool = False


class HookRegistry:
    """
    Registry for template execution hooks.
    
    Supports:
    - Multiple hooks per stage
    - Priority ordering
    - Conditional execution
    - Async hooks
    """
    
    PRE_EXECUTE = "pre_execute"
    POST_EXECUTE = "post_execute"
    PRE_TASK = "pre_task"
    POST_TASK = "post_task"
    ON_ERROR = "on_error"
    PRE_TOOL_CALL = "pre_tool_call"
    POST_TOOL_CALL = "post_tool_call"
    POST_PLAN_CREATED = "post_plan_created"
    POST_PLAN_UPDATED = "post_plan_updated"
    POST_VERIFICATION = "post_verification"
    POST_BASH_GUARD = "post_bash_guard"
    POST_COMPLETE = "post_complete"

    VALID_STAGES: frozenset[str] = frozenset({
        PRE_EXECUTE, POST_EXECUTE, PRE_TASK, POST_TASK, ON_ERROR,
        PRE_TOOL_CALL, POST_TOOL_CALL,
        POST_PLAN_CREATED, POST_PLAN_UPDATED,
        POST_VERIFICATION, POST_BASH_GUARD, POST_COMPLETE,
    })
    
    def get_valid_stages(self) -> frozenset[str]:
        return self.VALID_STAGES

    def __init__(self):
        self._hooks: Dict[str, List[Hook]] = {
            stage: [] for stage in self.VALID_STAGES
        }
    
    def register(
        self,
        stage: str,
        function: HookFunction,
        priority: int = 0,
        condition: Optional[Callable] = None,
        name: Optional[str] = None,
    ) -> Hook:
        """
        Register a hook.
        
        Args:
            stage: When to run (pre_execute, post_execute, etc.)
            function: Hook function
            priority: Execution order (higher = earlier)
            condition: Optional condition function
            name: Optional hook name
            
        Returns:
            Hook registration
        """
        if stage not in self.VALID_STAGES:
            raise ValueError(f"Invalid stage: {stage}. Valid: {self.VALID_STAGES}")
        
        # Detect async support
        async_support = inspect.iscoroutinefunction(function)
        
        hook = Hook(
            name=name or function.__name__,
            function=function,
            priority=priority,
            condition=condition,
            async_support=async_support,
        )
        
        self._hooks[stage].append(hook)
        
        # Sort by priority (descending)
        self._hooks[stage].sort(key=lambda h: h.priority, reverse=True)
        
        _log.info(f"Registered hook '{hook.name}' for stage '{stage}'")
        return hook
    
    def unregister(self, stage: str, name: str) -> bool:
        """
        Unregister a hook by name.
        
        Returns:
            True if removed, False if not found
        """
        if stage not in self.VALID_STAGES:
            return False
        
        hooks = self._hooks[stage]
        for i, hook in enumerate(hooks):
            if hook.name == name:
                hooks.pop(i)
                _log.info(f"Unregistered hook '{name}' from '{stage}'")
                return True
        
        return False
    
    def get_hooks(self, stage: str) -> List[Hook]:
        """Get all hooks for a stage."""
        return self._hooks.get(stage, [])
    
    def clear(self, stage: Optional[str] = None):
        """Clear all hooks or hooks for specific stage."""
        if stage:
            if stage in self._hooks:
                self._hooks[stage] = []
                _log.info(f"Cleared all hooks from '{stage}'")
        else:
            for s in self._hooks:
                self._hooks[s] = []
            _log.info("Cleared all hooks")
    
    async def execute_hooks(
        self,
        stage: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute all hooks for a stage.
        
        Args:
            stage: Execution stage
            context: Context data for hooks
            
        Returns:
            Modified context
        """
        hooks = self.get_hooks(stage)
        
        for hook in hooks:
            # Check condition
            if hook.condition and not hook.condition(context):
                continue
            
            try:
                if hook.async_support:
                    result = await hook.function(**context)
                else:
                    result = hook.function(**context)
                
                # If hook returns dict, merge into context
                if isinstance(result, dict):
                    context.update(result)
                
            except Exception as e:
                # Hooks are observers — their failures must never crash the host.
                _log.error(f"Hook '{hook.name}' failed at stage '{stage}': {e}")
        
        return context


# Decorator for easy hook registration

def hook(stage: str, priority: int = 0, condition: Optional[Callable] = None):
    """
    Decorator to register a function as a hook.
    
    Usage:
        @hook("pre_execute", priority=10)
        def my_hook(template, parameters, **kwargs):
            print("Before execution!")
            return {"extra": "data"}
    """
    def decorator(func: HookFunction) -> HookFunction:
        # Store hook info on function
        func._hook_info = {
            "stage": stage,
            "priority": priority,
            "condition": condition,
        }
        return func
    return decorator


class HookedTemplateEngine(TemplateEngine):
    """TemplateEngine with hook support for synchronous template execution.

    .. warning::
        **Not safe for async contexts.**  ``execute()`` is synchronous and
        internally calls ``asyncio.run()`` inside a ``ThreadPoolExecutor`` to
        invoke async hooks.  This pattern causes deadlocks when called from
        within a running event loop (e.g. FastAPI, PlanActFlow).

        When you need lifecycle hooks inside an async pipeline, instantiate
        ``HookRegistry`` directly and call ``await registry.execute_hooks(...)``
        — do **not** use this class.
    """
    
    def __init__(self):
        super().__init__()
        self.hooks = HookRegistry()
    
    def execute(self, template_name: str, parameters=None, dry_run=False):
        """Execute with hooks."""
        parameters = parameters or {}
        
        # Pre-execute hooks
        context = {
            "template_name": template_name,
            "parameters": parameters,
            "dry_run": dry_run,
            "registry": self.registry,
        }
        
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Schedule in background
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run,
                        self.hooks.execute_hooks(HookRegistry.PRE_EXECUTE, context)
                    )
                    context = future.result()
            else:
                context = loop.run_until_complete(
                    self.hooks.execute_hooks(HookRegistry.PRE_EXECUTE, context)
                )
        except RuntimeError:
            context = asyncio.run(
                self.hooks.execute_hooks(HookRegistry.PRE_EXECUTE, context)
            )
        
        # Execute
        result = super().execute(template_name, parameters, dry_run)
        
        # Post-execute hooks
        context["result"] = result
        
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run,
                        self.hooks.execute_hooks(HookRegistry.POST_EXECUTE, context)
                    )
                    context = future.result()
            else:
                context = loop.run_until_complete(
                    self.hooks.execute_hooks(HookRegistry.POST_EXECUTE, context)
                )
        except RuntimeError:
            context = asyncio.run(
                self.hooks.execute_hooks(HookRegistry.POST_EXECUTE, context)
            )
        
        return result


# Built-in Hooks

class BuiltinHooks:
    """Collection of built-in hooks."""
    
    @staticmethod
    @hook("pre_execute", priority=100)
    def validate_parameters(template_name, parameters, registry, **kwargs):
        """Validate parameters before execution."""
        template = registry.get(template_name)
        if not template:
            return {}
        
        from weebot.templates.parameters import ParameterResolver
        
        resolver = ParameterResolver()
        errors = resolver.validate_only(template, parameters)
        
        if errors:
            _log.warning(f"Parameter validation warnings: {errors}")
        
        return {"validation_errors": errors}
    
    @staticmethod
    @hook("post_execute", priority=50)
    def log_execution(template_name, parameters, result, **kwargs):
        """Log execution results."""
        _log.info(
            f"Template '{template_name}' executed: "
            f"success={result.success}, "
            f"time={result.execution_time_ms}ms"
        )
        return {}
    
    @staticmethod
    @hook("on_error", priority=0)
    def error_handler(template_name, parameters, result, **kwargs):
        """Handle execution errors."""
        if not result.success:
            _log.error(
                f"Template '{template_name}' failed: {result.error}"
            )
        return {}
    
    @staticmethod
    @hook("post_execute", priority=10)
    def notify_completion(template_name, result, **kwargs):
        """Send notification on completion."""
        # This is a placeholder - integrate with your notification system
        if result.success:
            _log.info(f"Template '{template_name}' completed successfully")
        return {}
    
    @staticmethod
    def register_all(engine: HookedTemplateEngine):
        """Register all built-in hooks."""
        for attr_name in dir(BuiltinHooks):
            attr = getattr(BuiltinHooks, attr_name)
            if callable(attr) and hasattr(attr, '_hook_info'):
                info = attr._hook_info
                engine.hooks.register(
                    stage=info["stage"],
                    function=attr,
                    priority=info["priority"],
                    condition=info.get("condition"),
                    name=attr_name,
                )


# Hook Conditions

class HookConditions:
    """Pre-built hook conditions."""
    
    @staticmethod
    def is_dry_run(context: Dict) -> bool:
        """Check if dry run mode."""
        return context.get("dry_run", False)
    
    @staticmethod
    def is_production(context: Dict) -> bool:
        """Check if production environment."""
        import os
        return os.environ.get("ENVIRONMENT") == "production"
    
    @staticmethod
    def has_errors(context: Dict) -> bool:
        """Check if execution had errors."""
        result = context.get("result")
        if result:
            return not result.success
        return False
    
    @staticmethod
    def template_matches(pattern: str):
        """Create condition that matches template name."""
        def condition(context: Dict) -> bool:
            import fnmatch
            name = context.get("template_name", "")
            return fnmatch.fnmatch(name, pattern)
        return condition
    
    @staticmethod
    def execution_time_exceeded(ms: int):
        """Create condition for slow executions."""
        def condition(context: Dict) -> bool:
            result = context.get("result")
            if result and result.execution_time_ms:
                return result.execution_time_ms > ms
            return False
        return condition

    # ── PlanActFlow-specific conditions ──────────────────────────────────

    @staticmethod
    def tool_name_is(*names: str):
        """Condition that matches when tool_name is one of the given names."""
        def condition(context: dict) -> bool:
            return context.get("tool_name", "") in names
        return condition

    @staticmethod
    def risk_level_at_least(level: str):
        """Fires when bash_guard risk_level >= the given level."""
        _order = {"SAFE": 0, "SUSPICIOUS": 1, "DANGEROUS": 2, "BLOCKED": 3}
        threshold = _order.get(level.upper(), 0)
        def condition(context: dict) -> bool:
            actual = _order.get(context.get("risk_level", "SAFE").upper(), 0)
            return actual >= threshold
        return condition

    @staticmethod
    def step_elapsed_exceeds(ms: int):
        """Fires when a step took longer than `ms` milliseconds."""
        def condition(context: dict) -> bool:
            return context.get("elapsed_ms", 0) > ms
        return condition

    @staticmethod
    def token_total_exceeds(n: int):
        """Fires when post_execute total_tokens > n."""
        def condition(context: dict) -> bool:
            return context.get("total_tokens", 0) > n
        return condition

    @staticmethod
    def gate_failed(gate_name: str):
        """Fires when post_verification gate_failures contains gate_name."""
        def condition(context: dict) -> bool:
            return gate_name in context.get("gate_failures", [])
        return condition


class BuiltinPlanActHooks:
    """Ready-made hook functions for PlanActFlow lifecycle stages.

    Usage::

        registry = HookRegistry()
        BuiltinPlanActHooks.register_all(registry)
    """

    @staticmethod
    def log_plan_created(session_id: str, step_count: int, elapsed_ms: float, **_):
        _log.info("[Hook] Plan created: %d steps in %.0fms (session=%s)",
                  step_count, elapsed_ms, session_id)

    @staticmethod
    def log_step_start(session_id: str, step_id: str, step_description: str,
                       step_index: int, total_steps: int, **_):
        _log.info("[Hook] Step %d/%d starting: %s (session=%s)",
                  step_index + 1, total_steps, step_description[:80], session_id)

    @staticmethod
    def log_step_done(session_id: str, step_id: str, elapsed_ms: float, **_):
        _log.info("[Hook] Step %s done in %.0fms (session=%s)",
                  step_id, elapsed_ms, session_id)

    @staticmethod
    def log_verification(session_id: str, scores: dict, gate_failures: list, **_):
        _log.info("[Hook] Verification: scores=%s gates_failed=%s (session=%s)",
                  scores, gate_failures, session_id)

    @staticmethod
    def log_complete(session_id: str, tool_count: int, error_count: int,
                     total_elapsed_ms: float, **_):
        _log.info("[Hook] Flow complete: %d tools, %d errors, %.0fms (session=%s)",
                  tool_count, error_count, total_elapsed_ms, session_id)

    @staticmethod
    def alert_on_blocked_command(session_id: str, command: str,
                                  risk_level: str, allowed: bool, **_):
        if not allowed:
            _log.warning("[SECURITY] Blocked command '%s...' (session=%s)",
                         command[:60], session_id)

    @staticmethod
    def register_all(registry: "HookRegistry") -> None:
        """Register all built-in hooks at sensible priorities."""
        registry.register("post_plan_created", BuiltinPlanActHooks.log_plan_created,
                          priority=0, name="log_plan_created")
        registry.register("pre_task", BuiltinPlanActHooks.log_step_start,
                          priority=0, name="log_step_start")
        registry.register("post_task", BuiltinPlanActHooks.log_step_done,
                          priority=0, name="log_step_done")
        registry.register("post_verification", BuiltinPlanActHooks.log_verification,
                          priority=0, name="log_verification")
        registry.register("post_complete", BuiltinPlanActHooks.log_complete,
                          priority=0, name="log_complete")
        registry.register("post_bash_guard", BuiltinPlanActHooks.alert_on_blocked_command,
                          priority=100, name="alert_blocked_command",
                          condition=HookConditions.risk_level_at_least("BLOCKED"))


# Example Usage

def example_hooks():
    """Example of using hooks."""
    
    # Create hooked engine
    engine = HookedTemplateEngine()
    
    # Register built-in hooks
    BuiltinHooks.register_all(engine)
    
    # Register custom hook
    @hook("post_execute", priority=5)
    def my_custom_hook(template_name, result, **kwargs):
        """Custom post-execution hook."""
        print(f"Template {template_name} finished!")
        return {}
    
    engine.hooks.register(
        stage="post_execute",
        function=my_custom_hook,
        priority=5,
        name="my_custom_hook",
    )
    
    # Register conditional hook
    engine.hooks.register(
        stage="post_execute",
        function=lambda **ctx: print("Slow execution detected!"),
        priority=1,
        condition=HookConditions.execution_time_exceeded(1000),
        name="slow_execution_alert",
    )
    
    return engine


if __name__ == "__main__":
    # Demo
    engine = example_hooks()
    print("HookedTemplateEngine created with built-in hooks")
    print(f"Registered hooks: {len(engine.hooks.get_hooks('pre_execute'))} pre-execute")
    print(f"Registered hooks: {len(engine.hooks.get_hooks('post_execute'))} post-execute")
