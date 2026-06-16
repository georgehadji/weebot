"""
Jinja2 Template Renderer for advanced templating.

Features:
- Conditionals ({% if %})
- Loops ({% for %})
- Filters ({{ value | filter }})
- Includes ({% include %})
- Custom functions
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union

from jinja2 import Environment, BaseLoader, TemplateError, UndefinedError
from jinja2.filters import FILTERS

from weebot.templates.parser import WorkflowTemplate, ParameterSchema

_log = logging.getLogger(__name__)


class TemplateRenderError(Exception):
    """Raised when template rendering fails."""
    
    def __init__(self, message: str, template: str = None, line: int = None):
        super().__init__(message)
        self.template = template
        self.line = line


class JinjaTemplateRenderer:
    """
    Advanced template renderer using Jinja2.
    
    Extends basic {{parameter}} substitution with:
    - Conditionals
    - Loops
    - Filters
    - Functions
    """
    
    def __init__(self):
        # Create Jinja environment with strict undefined handling
        self.env = Environment(
            loader=BaseLoader(),
            undefined=self._make_strict_undefined(),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        
        # Register custom filters
        self._register_filters()
        
        # Register custom functions
        self._register_functions()
    
    def _make_strict_undefined(self):
        """Create a strict undefined class that raises on ANY use.

        Subclasses jinja2's StrictUndefined (which already fails on string
        rendering, iteration, truthiness, etc. via UndefinedError) rather than
        the base Undefined — the previous version only overrode __getattr__/
        __getitem__/__call__, so a bare ``{{undefined_var}}`` (which triggers
        __str__) rendered as an empty string instead of erroring.

        UndefinedError is a TemplateError subclass, so render() catches it and
        wraps it as TemplateRenderError.
        """
        from jinja2 import StrictUndefined

        return StrictUndefined
    
    def _register_filters(self):
        """Register custom Jinja2 filters."""
        # String filters
        self.env.filters['upper'] = str.upper
        self.env.filters['lower'] = str.lower
        self.env.filters['title'] = str.title
        self.env.filters['capitalize'] = str.capitalize
        
        # List filters
        self.env.filters['join'] = self._join_filter
        self.env.filters['sort'] = sorted
        self.env.filters['reverse'] = lambda x: list(reversed(x))
        self.env.filters['unique'] = lambda x: list(dict.fromkeys(x))
        
        # Date/time filters
        self.env.filters['date'] = self._date_filter
        self.env.filters['datetime'] = self._datetime_filter
        
        # Format filters
        self.env.filters['json'] = self._json_filter
        self.env.filters['yaml'] = self._yaml_filter
        
        # Template filters
        self.env.filters['indent'] = self._indent_filter
        self.env.filters['quote'] = self._quote_filter
    
    def _register_functions(self):
        """Register custom Jinja2 functions."""
        self.env.globals['env'] = self._env_function
        self.env.globals['now'] = self._now_function
        self.env.globals['uuid'] = self._uuid_function
        self.env.globals['range'] = range
        self.env.globals['len'] = len
        self.env.globals['zip'] = zip
        self.env.globals['enumerate'] = enumerate
    
    def render(
        self,
        template_str: str,
        context: Dict[str, Any],
        safe_mode: bool = True,
    ) -> str:
        """
        Render a Jinja2 template string.
        
        Args:
            template_str: Jinja2 template
            context: Variables for rendering
            safe_mode: If True, catch and report errors
            
        Returns:
            Rendered string
            
        Raises:
            TemplateRenderError: If rendering fails
        """
        try:
            template = self.env.from_string(template_str)
            return template.render(**context)
        except TemplateError as e:
            error_msg = f"Template error: {e}"
            if hasattr(e, 'lineno'):
                error_msg += f" (line {e.lineno})"
            _log.error(error_msg)
            if safe_mode:
                raise TemplateRenderError(error_msg, template_str, getattr(e, 'lineno', None))
            raise
        except Exception as e:
            error_msg = f"Rendering error: {e}"
            _log.error(error_msg)
            if safe_mode:
                raise TemplateRenderError(error_msg, template_str)
            raise
    
    def render_workflow(
        self,
        workflow: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Recursively render all strings in a workflow dict.
        
        Args:
            workflow: Workflow definition with Jinja2 templates
            context: Variables for rendering
            
        Returns:
            Workflow with all templates rendered
        """
        if isinstance(workflow, dict):
            return {
                key: self.render_workflow(value, context)
                for key, value in workflow.items()
            }
        elif isinstance(workflow, list):
            return [self.render_workflow(item, context) for item in workflow]
        elif isinstance(workflow, str):
            return self.render(workflow, context)
        else:
            return workflow
    
    def validate_template(self, template_str: str) -> List[str]:
        """
        Validate a template without rendering.
        
        Returns:
            List of error messages (empty if valid)
        """
        errors = []
        
        try:
            self.env.parse(template_str)
        except TemplateError as e:
            errors.append(str(e))
        
        # Check for potentially dangerous constructs
        dangerous_patterns = [
            '{% raw %}',
            '{% macro',
            '{% call',
            '{% do',
        ]
        
        for pattern in dangerous_patterns:
            if pattern in template_str.lower():
                errors.append(f"Potentially dangerous pattern: {pattern}")
        
        return errors
    
    # Custom Filters
    
    def _join_filter(self, value: List[str], separator: str = ", ") -> str:
        """Join list elements."""
        return separator.join(str(x) for x in value)
    
    def _date_filter(self, value, format_str: str = "%Y-%m-%d") -> str:
        """Format date."""
        from datetime import datetime
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        return value.strftime(format_str)
    
    def _datetime_filter(self, value, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
        """Format datetime."""
        return self._date_filter(value, format_str)
    
    def _json_filter(self, value, indent: int = 2) -> str:
        """Convert to JSON."""
        import json
        return json.dumps(value, indent=indent, ensure_ascii=False)
    
    def _yaml_filter(self, value) -> str:
        """Convert to YAML."""
        import yaml
        return yaml.dump(value, default_flow_style=False, allow_unicode=True)
    
    def _indent_filter(self, value: str, width: int = 4) -> str:
        """Indent text."""
        import textwrap
        return textwrap.indent(str(value), " " * width)
    
    def _quote_filter(self, value: str, quote: str = '"') -> str:
        """Quote string."""
        escaped = str(value).replace(quote, f"\\{quote}")
        return f"{quote}{escaped}{quote}"
    
    # Custom Functions
    
    def _env_function(self, var_name: str, default: Any = None) -> Any:
        """Get environment variable."""
        import os
        return os.environ.get(var_name, default)
    
    def _now_function(self, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
        """Get current datetime."""
        from datetime import datetime
        return datetime.now().strftime(format_str)
    
    def _uuid_function(self) -> str:
        """Generate UUID."""
        import uuid
        return str(uuid.uuid4())


class ConditionalWorkflowBuilder:
    """
    Build workflows with conditional tasks.
    
    Uses Jinja2 conditionals to include/exclude tasks.
    """
    
    def __init__(self, renderer: Optional[JinjaTemplateRenderer] = None):
        self.renderer = renderer or JinjaTemplateRenderer()
    
    def build_workflow(
        self,
        template_workflow: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Build workflow with conditionals resolved.
        
        Example:
            {% if include_security %}
            security_scan:
              agent_role: security
            {% endif %}
        """
        workflow = {}
        
        for task_id, task_def in template_workflow.items():
            # Check if task has condition
            condition = task_def.get('condition')
            
            if condition:
                # Evaluate condition
                try:
                    result = self.renderer.render(
                        f"{{% if {condition} %}}true{{% endif %}}",
                        context
                    )
                    if result != "true":
                        continue  # Skip this task
                except Exception as e:
                    _log.warning(f"Condition evaluation failed for {task_id}: {e}")
                    # Include task by default on error
            
            # Add task to workflow
            workflow[task_id] = task_def
        
        return workflow


class LoopWorkflowBuilder:
    """
    Build workflows with loop-generated tasks.
    
    Expands loops into individual tasks.
    """
    
    def __init__(self, renderer: Optional[JinjaTemplateRenderer] = None):
        self.renderer = renderer or JinjaTemplateRenderer()
    
    def expand_loops(
        self,
        template_workflow: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Expand loop constructs in workflow.
        
        Example:
            {% for item in items %}
            process_{{item}}:
              task: "Process {{item}}"
            {% endfor %}
        """
        workflow = {}
        
        for task_id, task_def in template_workflow.items():
            # Check if task_id contains loop syntax
            if "{% for" in task_id or "{%for" in task_id:
                # This is a loop - expand it
                expanded = self._expand_task_loop(task_id, task_def, context)
                workflow.update(expanded)
            else:
                workflow[task_id] = task_def
        
        return workflow
    
    def _expand_task_loop(
        self,
        task_id_template: str,
        task_def: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Expand a single loop task."""
        # Parse the for loop
        # Format: "{% for var in iterable %}prefix_{{var}}_suffix{% endfor %}"
        
        try:
            # Extract loop variable and iterable
            import re
            match = re.search(r'{%\s*for\s+(\w+)\s+in\s+(\w+)\s*%}', task_id_template)
            if not match:
                _log.warning(f"Could not parse loop: {task_id_template}")
                return {task_id_template: task_def}
            
            var_name = match.group(1)
            iterable_name = match.group(2)
            
            # Get iterable from context
            iterable = context.get(iterable_name, [])
            if not isinstance(iterable, (list, tuple)):
                _log.warning(f"Iterable {iterable_name} not found or not iterable")
                return {task_id_template: task_def}
            
            # Extract template parts
            parts = re.split(r'{%\s*for\s+\w+\s+in\s+\w+\s*%}|{%\s*endfor\s*%}', task_id_template)
            if len(parts) < 3:
                return {task_id_template: task_def}
            
            prefix = parts[0]
            template = parts[1]
            suffix = parts[2]
            
            # Generate tasks
            expanded = {}
            for item in iterable:
                loop_context = {**context, var_name: item}
                
                # Render task ID
                task_id = self.renderer.render(
                    f"{prefix}{template}{suffix}",
                    loop_context
                )
                
                # Render task definition
                task_def_rendered = self.renderer.render_workflow(task_def, loop_context)
                
                expanded[task_id] = task_def_rendered
            
            return expanded
            
        except Exception as e:
            _log.error(f"Failed to expand loop {task_id_template}: {e}")
            return {task_id_template: task_def}
