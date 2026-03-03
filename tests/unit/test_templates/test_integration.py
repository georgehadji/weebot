"""Tests for template integration with core systems."""
from __future__ import annotations

import pytest
from unittest.mock import Mock, patch

from weebot.templates.integration import (
    TemplateOrchestratorIntegration,
    TemplateCLI,
    create_integrated_engine,
)
from weebot.templates.engine import TemplateEngine
from weebot.templates.parser import WorkflowTemplate, ParameterSchema


class TestTemplateOrchestratorIntegration:
    """Test integration with orchestrator."""
    
    @pytest.fixture
    def mock_engine(self):
        engine = Mock(spec=TemplateEngine)
        engine.registry = Mock()
        engine.registry.get = Mock(return_value=None)
        return engine
    
    def test_integration_initialization(self, mock_engine):
        """Test integration initializes correctly."""
        integration = TemplateOrchestratorIntegration(mock_engine)
        
        assert integration.engine == mock_engine
        assert integration.orchestrator is not None or not hasattr(integration, 'orchestrator')
    
    def test_handle_agent_task_simulated(self, mock_engine):
        """Agent task handler simulates when no agent manager."""
        # Force simulation mode
        with patch("weebot.templates.agent_integration.HAS_AGENT_SYSTEM", False):
            integration = TemplateOrchestratorIntegration(mock_engine)
            
            from weebot.templates.engine import ExecutionContext
            
            template = WorkflowTemplate(name="Test", version="1.0", workflow={})
            context = ExecutionContext(template=template, parameters={})
            
            task_def = {
                "agent_role": "researcher",
                "task": "Research AI technology",
            }
            
            result = integration._handle_agent_task(task_def, context)
            
            assert result["success"] is True
            assert result["agent_role"] == "researcher"
    
    def test_handle_tool_task_simulated(self, mock_engine):
        """Tool task handler simulates when no tool registry."""
        integration = TemplateOrchestratorIntegration(mock_engine)
        
        from weebot.templates.engine import ExecutionContext
        
        template = WorkflowTemplate(name="Test", version="1.0", workflow={})
        context = ExecutionContext(template=template, parameters={})
        
        task_def = {
            "tool": "web_search",
            "parameters": {"query": "AI news"},
        }
        
        result = integration._handle_tool_task(task_def, context)
        
        assert result["success"] is True
        assert result["tool"] == "web_search"
        assert "simulated" in result.get("note", "").lower()
    
    def test_handle_parallel_tasks_sequential_fallback(self, mock_engine):
        """Parallel tasks fall back to sequential without orchestrator."""
        # Force simulation mode for agent tasks
        with patch("weebot.templates.agent_integration.HAS_AGENT_SYSTEM", False):
            integration = TemplateOrchestratorIntegration(mock_engine)
            integration.orchestrator = None  # Force no orchestrator
            
            from weebot.templates.engine import ExecutionContext
            
            template = WorkflowTemplate(name="Test", version="1.0", workflow={})
            context = ExecutionContext(template=template, parameters={})
            
            task_def = {
                "subtasks": [
                    {"agent_role": "agent1", "task": "Task 1"},
                    {"agent_role": "agent2", "task": "Task 2"},
                ]
            }
            
            result = integration._handle_parallel_tasks(task_def, context)
            
            assert result["success"] is True
            assert len(result["results"]) == 2
    
    def test_execute_template_not_found(self, mock_engine):
        """Execute returns error when template not found."""
        mock_engine.registry.get.return_value = None
        
        integration = TemplateOrchestratorIntegration(mock_engine)
        result = integration.execute_workflow_template("NonExistent")
        
        assert result["success"] is False
        assert "not found" in result["error"].lower()
    
    def test_resolve_template_in_dict(self, mock_engine):
        """Template resolution replaces placeholders."""
        integration = TemplateOrchestratorIntegration(mock_engine)
        
        data = {
            "task": "Research {{topic}}",
            "nested": {
                "description": "About {{topic}}",
            },
            "list": ["{{topic}}", "static"],
        }
        
        parameters = {"topic": "AI"}
        
        resolved = integration._resolve_template_in_dict(data, parameters)
        
        assert resolved["task"] == "Research AI"
        assert resolved["nested"]["description"] == "About AI"
        assert resolved["list"] == ["AI", "static"]


class TestTemplateCLI:
    """Test CLI interface."""
    
    @pytest.fixture
    def mock_integration(self):
        integration = Mock(spec=TemplateOrchestratorIntegration)
        integration.engine = Mock()
        integration.engine.registry = Mock()
        return integration
    
    def test_list_templates(self, mock_integration):
        """CLI lists templates from registry."""
        mock_integration.engine.registry.list_templates.return_value = [
            "Template A", "Template B"
        ]
        
        cli = TemplateCLI(mock_integration)
        templates = cli.list_templates()
        
        assert templates == ["Template A", "Template B"]
    
    def test_show_template(self, mock_integration):
        """CLI shows template metadata."""
        metadata = {"name": "Test", "version": "1.0"}
        mock_integration.engine.registry.get_metadata.return_value = metadata
        
        cli = TemplateCLI(mock_integration)
        result = cli.show_template("Test")
        
        assert result == metadata
    
    def test_execute(self, mock_integration):
        """CLI executes template."""
        expected_result = {"success": True, "output": "done"}
        mock_integration.execute_workflow_template.return_value = expected_result
        
        cli = TemplateCLI(mock_integration)
        result = cli.execute("Test Template", {"param": "value"})
        
        assert result == expected_result
        mock_integration.execute_workflow_template.assert_called_once_with(
            "Test Template", {"param": "value"}
        )
    
    def test_execute_dry_run(self, mock_integration):
        """CLI supports dry run execution."""
        expected_result = {"success": True, "status": "validated"}
        mock_integration.engine.execute.return_value = expected_result
        
        cli = TemplateCLI(mock_integration)
        result = cli.execute("Test Template", {"param": "value"}, dry_run=True)
        
        assert result == expected_result
        mock_integration.engine.execute.assert_called_once_with(
            "Test Template", {"param": "value"}, dry_run=True
        )
    
    def test_validate(self, mock_integration):
        """CLI validates template."""
        mock_integration.engine.validate.return_value = []
        
        cli = TemplateCLI(mock_integration)
        errors = cli.validate("Test Template", {"param": "value"})
        
        assert errors == []
        mock_integration.engine.validate.assert_called_once_with(
            "Test Template", {"param": "value"}
        )


class TestCreateIntegratedEngine:
    """Test factory function."""
    
    def test_create_with_defaults(self):
        """Create integrated engine with default settings."""
        integration = create_integrated_engine(
            load_builtin=True,
            use_orchestrator=False,  # Disable to avoid dependency issues
        )
        
        assert isinstance(integration, TemplateOrchestratorIntegration)
        assert integration.engine is not None
    
    def test_create_without_builtin(self):
        """Create without loading built-in templates."""
        integration = create_integrated_engine(
            load_builtin=False,
            use_orchestrator=False,
        )
        
        # Registry should be empty
        assert len(integration.engine.registry) == 0


class TestIntegrationWithRealEngine:
    """Integration tests with real TemplateEngine."""
    
    def test_end_to_end_simulated_execution(self):
        """End-to-end test with simulated execution."""
        engine = TemplateEngine()
        
        # Register a test template
        template = WorkflowTemplate(
            name="Integration Test",
            version="1.0",
            parameters={
                "topic": ParameterSchema(name="topic", type="string", required=True)
            },
            workflow={
                "research": {
                    "type": "agent_task",
                    "agent_role": "researcher",
                    "task": "Research {{topic}}",
                }
            },
            output={
                "summary": "Research on {{topic}} completed"
            }
        )
        
        engine.registry.register(template)
        
        # Create integration
        integration = TemplateOrchestratorIntegration(engine)
        
        # Execute
        result = integration.execute_workflow_template(
            "Integration Test",
            {"topic": "AI"}
        )
        
        # Result should be a dict with success
        assert "success" in result
        assert result["success"] is True
        assert result["parameters"]["topic"] == "AI"
