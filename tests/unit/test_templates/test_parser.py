"""Tests for template parser."""
from __future__ import annotations

import pytest
from weebot.templates.parser import (
    TemplateParser,
    WorkflowTemplate,
    TemplateValidationError,
)


class TestTemplateParser:
    """Test template parsing functionality."""
    
    def test_parse_simple_template(self):
        """Parse minimal valid template."""
        parser = TemplateParser()
        yaml_content = """
name: "Test Workflow"
version: "1.0.0"
description: "A test workflow"
parameters: {}
workflow:
  task1:
    agent_role: "test"
"""
        template = parser.parse(yaml_content)
        
        assert template.name == "Test Workflow"
        assert template.version == "1.0.0"
        assert template.description == "A test workflow"
    
    def test_parse_with_parameters(self):
        """Parse template with parameters."""
        parser = TemplateParser()
        yaml_content = """
name: "Research Task"
parameters:
  topic:
    type: string
    description: "Research topic"
    required: true
  depth:
    type: enum
    values: ["brief", "deep"]
    default: "brief"
workflow:
  research:
    agent_role: "researcher"
"""
        template = parser.parse(yaml_content)
        
        assert "topic" in template.parameters
        assert template.parameters["topic"].type == "string"
        assert template.parameters["topic"].required is True
        
        assert "depth" in template.parameters
        assert template.parameters["depth"].type == "enum"
        assert template.parameters["depth"].default == "brief"
    
    def test_missing_name_raises_error(self):
        """Template without name should raise error."""
        parser = TemplateParser()
        yaml_content = """
workflow:
  task1: {}
"""
        with pytest.raises(TemplateValidationError, match="name"):
            parser.parse(yaml_content)
    
    def test_missing_workflow_raises_error(self):
        """Template without workflow should raise error."""
        parser = TemplateParser()
        yaml_content = """
name: "Test"
"""
        with pytest.raises(TemplateValidationError, match="workflow"):
            parser.parse(yaml_content)
    
    def test_invalid_yaml_raises_error(self):
        """Invalid YAML should raise error."""
        parser = TemplateParser()
        with pytest.raises(TemplateValidationError):
            parser.parse("invalid: yaml: content: [")
    
    def test_unsupported_parameter_type(self):
        """Unsupported parameter type should raise error."""
        parser = TemplateParser()
        yaml_content = """
name: "Test"
parameters:
  invalid_param:
    type: "unsupported_type"
workflow:
  task1: {}
"""
        with pytest.raises(TemplateValidationError, match="unsupported_type"):
            parser.parse(yaml_content)
    
    def test_default_values(self):
        """Test default values for optional fields."""
        parser = TemplateParser()
        yaml_content = """
name: "Minimal"
workflow:
  task1: {}
"""
        template = parser.parse(yaml_content)
        
        assert template.version == "1.0.0"
        assert template.description == ""
        assert template.author == ""
        assert template.parameters == {}
        assert template.output == {}


class TestTemplateParserFile:
    """Test parsing from files."""
    
    def test_parse_from_file(self, tmp_path):
        """Parse template from file."""
        parser = TemplateParser()
        template_file = tmp_path / "test_template.yaml"
        template_file.write_text("""
name: "File Test"
version: "2.0.0"
workflow:
  task1:
    agent_role: "test"
""")
        
        template = parser.parse_file(template_file)
        assert template.name == "File Test"
        assert template.version == "2.0.0"
    
    def test_file_not_found(self):
        """Non-existent file should raise FileNotFoundError."""
        parser = TemplateParser()
        with pytest.raises(FileNotFoundError):
            parser.parse_file("/nonexistent/path/template.yaml")
