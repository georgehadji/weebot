"""Tests for Jinja2 template renderer."""
from __future__ import annotations

import pytest
from datetime import datetime

from weebot.templates.jinja_renderer import (
    JinjaTemplateRenderer,
    TemplateRenderError,
    ConditionalWorkflowBuilder,
    LoopWorkflowBuilder,
)


class TestJinjaTemplateRenderer:
    """Test Jinja2 template rendering."""
    
    @pytest.fixture
    def renderer(self):
        return JinjaTemplateRenderer()
    
    def test_basic_substitution(self, renderer):
        """Basic variable substitution."""
        result = renderer.render("Hello {{name}}!", {"name": "World"})
        assert result == "Hello World!"
    
    def test_conditional_if(self, renderer):
        """If conditional."""
        template = "{% if enabled %}ON{% else %}OFF{% endif %}"
        
        result = renderer.render(template, {"enabled": True})
        assert result == "ON"
        
        result = renderer.render(template, {"enabled": False})
        assert result == "OFF"
    
    def test_loop_for(self, renderer):
        """For loop."""
        template = "{% for item in items %}{{item}},{% endfor %}"
        result = renderer.render(template, {"items": ["a", "b", "c"]})
        assert result == "a,b,c,"
    
    def test_filter_upper(self, renderer):
        """Upper filter."""
        result = renderer.render("{{name | upper}}", {"name": "hello"})
        assert result == "HELLO"
    
    def test_filter_lower(self, renderer):
        """Lower filter."""
        result = renderer.render("{{name | lower}}", {"name": "HELLO"})
        assert result == "hello"
    
    def test_filter_join(self, renderer):
        """Join filter."""
        result = renderer.render("{{items | join(', ')}}", {"items": ["a", "b", "c"]})
        assert result == "a, b, c"
    
    def test_filter_json(self, renderer):
        """JSON filter."""
        result = renderer.render("{{data | json}}", {"data": {"key": "value"}})
        assert '"key": "value"' in result
    
    def test_function_now(self, renderer):
        """Now function."""
        result = renderer.render("{{now()}}", {})
        # Should return datetime string
        assert len(result) > 0
    
    def test_function_uuid(self, renderer):
        """UUID function."""
        result = renderer.render("{{uuid()}}", {})
        # Should return UUID format
        assert len(result) == 36
        assert result.count("-") == 4
    
    def test_function_env(self, renderer, monkeypatch):
        """Environment variable function."""
        monkeypatch.setenv("TEST_VAR", "test_value")
        result = renderer.render("{{env('TEST_VAR')}}", {})
        assert result == "test_value"
    
    def test_undefined_variable_error(self, renderer):
        """Undefined variables raise errors."""
        with pytest.raises(TemplateRenderError):
            renderer.render("{{undefined_var}}", {})
    
    def test_render_workflow_dict(self, renderer):
        """Render workflow dictionary."""
        workflow = {
            "task1": {
                "task": "Process {{name}}",
                "count": "{{count}}",
            }
        }
        
        result = renderer.render_workflow(workflow, {"name": "test", "count": 5})
        
        assert result["task1"]["task"] == "Process test"
        assert result["task1"]["count"] == "5"
    
    def test_validate_template_valid(self, renderer):
        """Validate valid template."""
        errors = renderer.validate_template("Hello {{name}}")
        assert errors == []
    
    def test_validate_template_invalid(self, renderer):
        """Validate invalid template."""
        errors = renderer.validate_template("{% if %}")  # Missing condition
        assert len(errors) > 0


class TestConditionalWorkflowBuilder:
    """Test conditional workflow building."""
    
    def test_include_task_when_condition_true(self):
        """Include task when condition is true."""
        builder = ConditionalWorkflowBuilder()
        
        workflow = {
            "always_task": {"agent_role": "test"},
            "conditional_task": {
                "agent_role": "test",
                "condition": "include_extra"
            }
        }
        
        result = builder.build_workflow(workflow, {"include_extra": True})
        
        assert "always_task" in result
        assert "conditional_task" in result
    
    def test_exclude_task_when_condition_false(self):
        """Exclude task when condition is false."""
        builder = ConditionalWorkflowBuilder()
        
        workflow = {
            "always_task": {"agent_role": "test"},
            "conditional_task": {
                "agent_role": "test",
                "condition": "include_extra"
            }
        }
        
        result = builder.build_workflow(workflow, {"include_extra": False})
        
        assert "always_task" in result
        assert "conditional_task" not in result
    
    def test_task_without_condition_always_included(self):
        """Tasks without condition are always included."""
        builder = ConditionalWorkflowBuilder()
        
        workflow = {
            "task1": {"agent_role": "test"},
        }
        
        result = builder.build_workflow(workflow, {})
        
        assert "task1" in result


class TestLoopWorkflowBuilder:
    """Test loop workflow building."""
    
    def test_expand_simple_loop(self):
        """Expand simple loop."""
        builder = LoopWorkflowBuilder()
        
        workflow = {
            "{% for item in items %}process_{{item}}{% endfor %}": {
                "task": "Process {{item}}"
            }
        }
        
        result = builder.expand_loops(workflow, {"items": ["a", "b"]})
        
        assert "process_a" in result
        assert "process_b" in result
        assert result["process_a"]["task"] == "Process a"
    
    def test_preserve_non_loop_tasks(self):
        """Preserve tasks without loops."""
        builder = LoopWorkflowBuilder()
        
        workflow = {
            "regular_task": {"task": "Regular"},
        }
        
        result = builder.expand_loops(workflow, {})
        
        assert "regular_task" in result


class TestAdvancedTemplates:
    """Test advanced template features."""
    
    def test_nested_conditionals(self):
        """Nested if statements."""
        renderer = JinjaTemplateRenderer()
        
        template = """
        {% if enabled %}
            {% if debug %}
                DEBUG MODE
            {% else %}
                PRODUCTION MODE
            {% endif %}
        {% else %}
            DISABLED
        {% endif %}
        """.strip()
        
        result = renderer.render(template, {"enabled": True, "debug": True})
        assert "DEBUG MODE" in result
        
        result = renderer.render(template, {"enabled": True, "debug": False})
        assert "PRODUCTION MODE" in result
    
    def test_loop_with_condition(self):
        """Loop with conditional inside."""
        renderer = JinjaTemplateRenderer()
        
        template = """
        {% for num in numbers %}
            {% if num > 5 %}
                {{num}} is large
            {% endif %}
        {% endfor %}
        """.strip()
        
        result = renderer.render(template, {"numbers": [3, 7, 2, 9]})
        assert "7 is large" in result
        assert "9 is large" in result
        assert "3 is large" not in result
    
    def test_complex_workflow_rendering(self):
        """Render complex workflow template."""
        renderer = JinjaTemplateRenderer()
        
        workflow_template = {
            "analyze": {
                "agent_role": "analyst",
                "task": "Analyze {{dataset | upper}} dataset",
                "parameters": {
                    "depth": "{% if thorough %}deep{% else %}shallow{% endif %}",
                    "metrics": "{{metrics | join(', ')}}"
                }
            }
        }
        
        context = {
            "dataset": "sales",
            "thorough": True,
            "metrics": ["revenue", "growth", "retention"]
        }
        
        result = renderer.render_workflow(workflow_template, context)
        
        assert result["analyze"]["task"] == "Analyze SALES dataset"
        assert result["analyze"]["parameters"]["depth"] == "deep"
        assert result["analyze"]["parameters"]["metrics"] == "revenue, growth, retention"
