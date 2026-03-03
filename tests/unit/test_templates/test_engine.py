"""Tests for template engine."""
from __future__ import annotations

import pytest
from unittest.mock import Mock

from weebot.templates.engine import TemplateEngine, TemplateExecutionResult, ExecutionContext
from weebot.templates.parser import WorkflowTemplate, ParameterSchema
from weebot.templates.parameters import ParameterValidationError


class TestTemplateEngineBasic:
    """Test basic engine functionality."""
    
    @pytest.fixture
    def engine(self):
        return TemplateEngine()
    
    @pytest.fixture
    def sample_template(self):
        return WorkflowTemplate(
            name="Test Workflow",
            version="1.0.0",
            description="A test workflow",
            parameters={
                "topic": ParameterSchema(name="topic", type="string", required=True)
            },
            workflow={
                "task1": {
                    "type": "agent_task",
                    "task": "Research {{topic}}"
                }
            },
            output={
                "format": "markdown"
            }
        )
    
    def test_registry_property(self, engine):
        """Engine exposes registry."""
        registry = engine.registry
        assert registry is not None
        assert len(registry) == 0
    
    def test_register_task_handler(self, engine):
        """Register and check task handler."""
        def mock_handler(task_def, context):
            return {"result": "success"}
        
        engine.register_task_handler("custom_task", mock_handler)
        
        assert engine.has_task_handler("custom_task")
        assert not engine.has_task_handler("unknown_task")
    
    def test_execute_template_not_found(self, engine):
        """Execute non-existent template returns error."""
        result = engine.execute("NonExistent")
        
        assert result.success is False
        assert "not found" in result.error.lower()
    
    def test_execute_parameter_validation_failure(self, engine, sample_template):
        """Execute with invalid parameters returns error."""
        engine.registry.register(sample_template)
        
        result = engine.execute("Test Workflow", {"topic": 123})
        # 123 is valid string, so this should succeed
        # Let's test with missing required
        result = engine.execute("Test Workflow", {})
        
        assert result.success is False
        assert "parameter" in result.error.lower() or "required" in result.error.lower()


class TestTemplateEngineExecution:
    """Test template execution."""
    
    def test_execute_with_mock_handler(self):
        """Execute with a mock task handler."""
        engine = TemplateEngine()
        
        # Register mock handler
        mock_results = []
        def mock_handler(task_def, context):
            mock_results.append(task_def)
            return {"executed": task_def.get("task", "unknown")}
        
        engine.register_task_handler("agent_task", mock_handler)
        
        # Create and register template
        template = WorkflowTemplate(
            name="Mock Test",
            version="1.0",
            parameters={
                "topic": ParameterSchema(name="topic", type="string", required=True)
            },
            workflow={
                "research": {
                    "type": "agent_task",
                    "task": "Research {{topic}}"
                }
            },
            output={}
        )
        
        engine.registry.register(template)
        
        # Execute
        result = engine.execute("Mock Test", {"topic": "AI"})
        
        assert result.success is True
        assert len(mock_results) == 1
        assert mock_results[0]["task"] == "Research AI"  # Template resolved
    
    def test_dry_run_execution(self):
        """Dry run validates without executing."""
        engine = TemplateEngine()
        
        template = WorkflowTemplate(
            name="Dry Run Test",
            version="1.0",
            parameters={
                "value": ParameterSchema(name="value", type="int", required=True)
            },
            workflow={
                "task1": {"type": "agent_task"}
            },
            output={}
        )
        
        engine.registry.register(template)
        
        result = engine.execute("Dry Run Test", {"value": "42"}, dry_run=True)
        
        assert result.success is True
        assert result.output["status"] == "validated"
        assert "task1" in result.output["tasks"]
    
    def test_execute_template_direct(self):
        """Execute template object directly."""
        engine = TemplateEngine()
        
        template = WorkflowTemplate(
            name="Direct Test",
            version="1.0",
            parameters={},
            workflow={
                "task1": {"type": "agent_task"}
            },
            output={"result": "done"}
        )
        
        result = engine.execute_template(template)
        
        assert result.success is True
        assert result.template_name.startswith("__temp_")


class TestTemplateEngineValidation:
    """Test template validation."""
    
    def test_validate_success(self):
        """Validate valid template returns empty errors."""
        engine = TemplateEngine()
        
        template = WorkflowTemplate(
            name="Valid Test",
            version="1.0",
            parameters={
                "name": ParameterSchema(name="name", type="string", required=True)
            },
            workflow={
                "task1": {"type": "agent_task"}
            },
            output={}
        )
        
        engine.registry.register(template)
        engine.register_task_handler("agent_task", lambda d, c: None)
        
        errors = engine.validate("Valid Test", {"name": "test"})
        
        assert errors == []
    
    def test_validate_missing_template(self):
        """Validate non-existent template returns error."""
        engine = TemplateEngine()
        
        errors = engine.validate("NonExistent")
        
        assert len(errors) == 1
        assert "not found" in errors[0]
    
    def test_validate_missing_parameter(self):
        """Validate with missing required parameter."""
        engine = TemplateEngine()
        
        template = WorkflowTemplate(
            name="Param Test",
            version="1.0",
            parameters={
                "required_param": ParameterSchema(
                    name="required_param", 
                    type="string", 
                    required=True
                )
            },
            workflow={},
            output={}
        )
        
        engine.registry.register(template)
        
        errors = engine.validate("Param Test", {})
        
        assert len(errors) == 1
        assert "required" in errors[0].lower()
    
    def test_validate_missing_handler(self):
        """Validate warns about missing task handlers."""
        engine = TemplateEngine()
        
        template = WorkflowTemplate(
            name="Handler Test",
            version="1.0",
            parameters={},
            workflow={
                "task1": {"type": "unknown_type"}
            },
            output={}
        )
        
        engine.registry.register(template)
        
        errors = engine.validate("Handler Test")
        
        assert len(errors) == 1
        assert "unknown_type" in errors[0]


class TestExecutionContext:
    """Test execution context."""
    
    def test_resolve_template_string(self):
        """Resolve template strings with parameters."""
        template = WorkflowTemplate(
            name="Test",
            version="1.0",
            parameters={},
            workflow={}
        )
        
        context = ExecutionContext(
            template=template,
            parameters={"topic": "AI", "count": "5"},
            variables={"result": "success"}
        )
        
        # Resolve with parameter
        result = context.resolve_template_string("Research {{topic}}")
        assert result == "Research AI"
        
        # Resolve with variable
        result = context.resolve_template_string("Status: {{result}}")
        assert result == "Status: success"
        
        # Resolve with multiple placeholders
        result = context.resolve_template_string("{{topic}} ({{count}} items)")
        assert result == "AI (5 items)"
        
        # No placeholders
        result = context.resolve_template_string("No placeholders")
        assert result == "No placeholders"


class TestTemplateEngineIntegration:
    """Integration tests for the engine."""
    
    def test_full_workflow_execution(self):
        """Execute a complete workflow."""
        engine = TemplateEngine()
        
        execution_log = []
        
        def research_handler(task_def, context):
            topic = task_def.get("task", "")
            execution_log.append(f"research: {topic}")
            return {"topic": topic, "findings": ["finding1", "finding2"]}
        
        def analysis_handler(task_def, context):
            execution_log.append("analysis")
            return {"analysis": "completed"}
        
        engine.register_task_handler("research", research_handler)
        engine.register_task_handler("analysis", analysis_handler)
        
        template = WorkflowTemplate(
            name="Integration Test",
            version="1.0",
            parameters={
                "topic": ParameterSchema(name="topic", type="string", required=True)
            },
            workflow={
                "research_task": {
                    "type": "research",
                    "task": "Research {{topic}}"
                },
                "analysis_task": {
                    "type": "analysis",
                    "depends_on": ["research_task"]
                }
            },
            output={
                "summary": "Research on {{topic}} completed"
            }
        )
        
        engine.registry.register(template)
        
        result = engine.execute("Integration Test", {"topic": "Machine Learning"})
        
        assert result.success is True
        assert len(execution_log) == 2
        assert "research: Research Machine Learning" in execution_log
        assert "analysis" in execution_log
        assert result.output["summary"] == "Research on Machine Learning completed"
    
    def test_quick_execute(self):
        """Quick execute from YAML string."""
        engine = TemplateEngine()
        
        yaml_template = """
name: Quick Test
version: "1.0"
parameters:
  name:
    type: string
    required: true
workflow:
  greet:
    type: agent_task
    task: "Hello {{name}}"
output:
  greeting: "Completed for {{name}}"
"""
        
        result = engine.quick_execute(yaml_template, {"name": "World"})
        
        assert result.success is True
        assert result.template_name.startswith("__temp_")


class TestTemplateEngineErrorHandling:
    """Test error handling in engine."""
    
    def test_task_handler_exception(self):
        """Handle exception in task handler."""
        engine = TemplateEngine()
        
        def failing_handler(task_def, context):
            raise ValueError("Task failed!")
        
        engine.register_task_handler("failing_task", failing_handler)
        
        template = WorkflowTemplate(
            name="Failing Test",
            version="1.0",
            parameters={},
            workflow={
                "task1": {"type": "failing_task"}
            },
            output={}
        )
        
        engine.registry.register(template)
        
        result = engine.execute("Failing Test")
        
        # Currently continues on task failure
        # In production, this might stop execution
        assert result.success is False or any(
            not r["success"] for r in result.task_results
        )
