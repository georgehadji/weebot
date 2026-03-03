#!/usr/bin/env python3
"""
Setup script for Phase 3 Template Engine.
Run this to create all necessary directories and files.
"""
import os
from pathlib import Path

# Define base paths
BASE_DIR = Path(__file__).parent
TEMPLATE_DIR = BASE_DIR / "weebot" / "templates"
BUILTIN_DIR = TEMPLATE_DIR / "builtin"
TEST_DIR = BASE_DIR / "tests" / "unit" / "test_templates"

def create_directories():
    """Create all required directories."""
    print("Creating directories...")
    
    directories = [
        TEMPLATE_DIR,
        BUILTIN_DIR,
        TEST_DIR,
    ]
    
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        print(f"  ✓ {directory}")
    
    print("\nAll directories created!\n")

def write_file(path: Path, content: str):
    """Write content to file."""
    path.write_text(content, encoding="utf-8")
    print(f"  ✓ {path}")

def create_init_files():
    """Create __init__.py files."""
    print("Creating __init__.py files...")
    
    # templates/__init__.py
    write_file(TEMPLATE_DIR / "__init__.py", '''\
"""Weebot Template Engine."""
from weebot.templates.parser import TemplateParser, WorkflowTemplate
from weebot.templates.parameters import ParameterResolver
from weebot.templates.registry import TemplateRegistry
from weebot.templates.engine import TemplateEngine

__all__ = [
    "TemplateParser",
    "WorkflowTemplate", 
    "ParameterResolver",
    "TemplateRegistry",
    "TemplateEngine",
]
''')
    
    # templates/builtin/__init__.py
    write_file(BUILTIN_DIR / "__init__.py", '''\
"""Built-in workflow templates."""
''')
    
    # tests/unit/test_templates/__init__.py
    write_file(TEST_DIR / "__init__.py", '''\
"""Tests for template engine."""
''')
    
    print()

def create_parser():
    """Create parser.py."""
    print("Creating parser.py...")
    
    content = '''\
"""Template parser for YAML/JSON workflow definitions."""
from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


@dataclass
class ParameterSchema:
    """Schema definition for a template parameter."""
    name: str
    type: str
    description: str = ""
    required: bool = True
    default: Any = None
    enum_values: Optional[List[str]] = None


@dataclass
class WorkflowTemplate:
    """Parsed workflow template."""
    name: str
    version: str
    description: str = ""
    author: str = ""
    parameters: Dict[str, ParameterSchema] = field(default_factory=dict)
    workflow: Dict[str, Any] = field(default_factory=dict)
    output: Dict[str, Any] = field(default_factory=dict)


class TemplateValidationError(Exception):
    """Raised when template validation fails."""
    pass


class TemplateParser:
    """Parse YAML/JSON templates into WorkflowTemplate objects."""
    
    SUPPORTED_TYPES = {"string", "int", "float", "bool", "enum", "list", "dict"}
    
    def parse(self, content: str) -> WorkflowTemplate:
        """Parse YAML content into WorkflowTemplate."""
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise TemplateValidationError(f"Invalid YAML: {e}")
        
        if not isinstance(data, dict):
            raise TemplateValidationError("Template must be a YAML mapping")
        
        return self._validate_and_create(data)
    
    def parse_file(self, path: Union[str, Path]) -> WorkflowTemplate:
        """Parse template from file."""
        path = Path(path)
        content = path.read_text(encoding="utf-8")
        return self.parse(content)
    
    def _validate_and_create(self, data: Dict[str, Any]) -> WorkflowTemplate:
        """Validate template structure and create WorkflowTemplate."""
        if "name" not in data:
            raise TemplateValidationError("Template must have \'name\' field")
        if "workflow" not in data:
            raise TemplateValidationError("Template must have \'workflow\' field")
        
        parameters = {}
        if "parameters" in data:
            for name, param_def in data["parameters"].items():
                parameters[name] = self._parse_parameter_schema(name, param_def)
        
        return WorkflowTemplate(
            name=data["name"],
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            author=data.get("author", ""),
            parameters=parameters,
            workflow=data.get("workflow", {}),
            output=data.get("output", {})
        )
    
    def _parse_parameter_schema(self, name: str, 
                                 param_def: Dict[str, Any]) -> ParameterSchema:
        """Parse parameter definition into ParameterSchema."""
        param_type = param_def.get("type", "string")
        if param_type not in self.SUPPORTED_TYPES:
            raise TemplateValidationError(
                f"Parameter \'{name}\' has unsupported type \'{param_type}\'"
            )
        
        return ParameterSchema(
            name=name,
            type=param_type,
            description=param_def.get("description", ""),
            required=param_def.get("required", True),
            default=param_def.get("default"),
            enum_values=param_def.get("values")
        )
'''
    
    write_file(TEMPLATE_DIR / "parser.py", content)
    print()

def create_parameters():
    """Create parameters.py (placeholder)."""
    print("Creating parameters.py...")
    
    content = '''\
"""Parameter resolution for workflow templates."""
from __future__ import annotations

from typing import Any, Dict, Optional

from weebot.templates.parser import ParameterSchema, WorkflowTemplate


class ParameterResolver:
    """Resolve and validate template parameters."""
    
    def resolve(self, template: WorkflowTemplate, 
                provided: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Resolve all parameters for a template.
        
        Args:
            template: The workflow template with parameter schemas
            provided: User-provided parameter values
            
        Returns:
            Dictionary of resolved parameter values
            
        Raises:
            ParameterValidationError: If required parameters are missing
        """
        provided = provided or {}
        resolved = {}
        
        for name, schema in template.parameters.items():
            if name in provided:
                resolved[name] = self._validate_type(name, provided[name], schema)
            elif schema.default is not None:
                resolved[name] = schema.default
            elif schema.required:
                raise ParameterValidationError(
                    f"Required parameter \'{name}\' not provided"
                )
        
        return resolved
    
    def _validate_type(self, name: str, value: Any, 
                       schema: ParameterSchema) -> Any:
        """Validate a value against its schema."""
        # Type validation logic will be implemented in full version
        return value


class ParameterValidationError(Exception):
    """Raised when parameter validation fails."""
    pass
'''
    
    write_file(TEMPLATE_DIR / "parameters.py", content)
    print()

def create_registry():
    """Create registry.py (placeholder)."""
    print("Creating registry.py...")
    
    content = '''\
"""Template registry for loading and managing templates."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from weebot.templates.parser import TemplateParser, WorkflowTemplate


class TemplateRegistry:
    """Registry for workflow templates."""
    
    def __init__(self):
        self._templates: Dict[str, WorkflowTemplate] = {}
        self._parser = TemplateParser()
    
    def register(self, template: WorkflowTemplate) -> None:
        """Register a template in the registry."""
        self._templates[template.name] = template
    
    def get(self, name: str) -> Optional[WorkflowTemplate]:
        """Get a template by name."""
        return self._templates.get(name)
    
    def list_templates(self) -> List[str]:
        """List all registered template names."""
        return list(self._templates.keys())
    
    def load_builtin_templates(self) -> int:
        """Load all built-in templates. Returns count loaded."""
        builtin_dir = Path(__file__).parent / "builtin"
        count = 0
        
        if not builtin_dir.exists():
            return 0
        
        for yaml_file in builtin_dir.glob("*.yaml"):
            try:
                template = self._parser.parse_file(yaml_file)
                self.register(template)
                count += 1
            except Exception:
                # Skip invalid templates
                pass
        
        return count
'''
    
    write_file(TEMPLATE_DIR / "registry.py", content)
    print()

def create_engine():
    """Create engine.py (placeholder)."""
    print("Creating engine.py...")
    
    content = '''\
"""Template execution engine."""
from __future__ import annotations

from typing import Any, Dict, Optional

from weebot.templates.parser import WorkflowTemplate
from weebot.templates.parameters import ParameterResolver
from weebot.templates.registry import TemplateRegistry


class TemplateEngine:
    """Main engine for executing workflow templates."""
    
    def __init__(self):
        self._registry = TemplateRegistry()
        self._resolver = ParameterResolver()
    
    @property
    def registry(self) -> TemplateRegistry:
        """Access the template registry."""
        return self._registry
    
    def execute(self, template_name: str, 
                parameters: Optional[Dict[str, Any]] = None) -> Any:
        """
        Execute a template by name with given parameters.
        
        Args:
            template_name: Name of registered template to execute
            parameters: Parameter values to use
            
        Returns:
            Execution result
        """
        template = self._registry.get(template_name)
        if not template:
            raise TemplateNotFoundError(f"Template \'{template_name}\' not found")
        
        resolved_params = self._resolver.resolve(template, parameters)
        
        # Execution logic will be implemented in full version
        return {
            "template": template_name,
            "parameters": resolved_params,
            "status": "not_implemented"
        }


class TemplateNotFoundError(Exception):
    """Raised when a template is not found."""
    pass
'''
    
    write_file(TEMPLATE_DIR / "engine.py", content)
    print()

def create_test_parser():
    """Create test_parser.py."""
    print("Creating test_parser.py...")
    
    content = '''\
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
'''
    
    write_file(TEST_DIR / "test_parser.py", content)
    print()

def create_example_template():
    """Create an example template."""
    print("Creating example template...")
    
    content = '''\
name: "Research Analysis Workflow"
version: "1.0.0"
description: |
  A workflow that performs comprehensive research on a topic
  and generates a structured analysis report.
author: "Weebot Team"

parameters:
  topic:
    type: string
    description: "The topic to research"
    required: true
  
  depth:
    type: enum
    description: "Research depth level"
    values: ["brief", "comprehensive", "exhaustive"]
    default: "comprehensive"
    required: false
  
  output_format:
    type: enum
    description: "Report output format"
    values: ["markdown", "html", "json"]
    default: "markdown"
    required: false
  
  include_sources:
    type: bool
    description: "Include source citations"
    default: true
    required: false

workflow:
  initial_research:
    agent_role: "researcher"
    task: "Gather initial information on {{ topic }}"
    parameters:
      depth: "{{ depth }}"
    
  deep_analysis:
    agent_role: "analyst"
    task: "Analyze research findings for {{ topic }}"
    depends_on: [initial_research]
    parameters:
      format: "{{ output_format }}"
    
  quality_check:
    agent_role: "reviewer"
    task: "Review analysis quality"
    depends_on: [deep_analysis]
    
  final_report:
    agent_role: "writer"
    task: "Generate final {{ output_format }} report on {{ topic }}"
    depends_on: [quality_check]
    parameters:
      include_citations: "{{ include_sources }}"

output:
  format: "{{ output_format }}"
  sections:
    - "executive_summary"
    - "key_findings"
    - "recommendations"
    - "sources"  # Conditional on include_sources
'''
    
    write_file(BUILTIN_DIR / "research_analysis.yaml", content)
    print()

def create_documentation():
    """Create documentation."""
    print("Creating documentation...")
    
    content = '''\
# Workflow Templates Guide

## Overview

The Template Engine allows non-developers to create workflows using YAML
instead of writing Python code.

## Template Structure

```yaml
name: "Template Name"
version: "1.0.0"
description: "What this template does"
author: "Your Name"

parameters:
  param_name:
    type: string | int | float | bool | enum | list | dict
    description: "What this parameter does"
    required: true | false
    default: value  # Optional
    values: ["option1", "option2"]  # For enum type

workflow:
  task_id:
    agent_role: "role_name"
    task: "Task description"
    depends_on: [other_task_id]
    parameters:
      key: "{{ template_parameter }}"

output:
  format: "markdown"
  sections:
    - "section_name"
```

## Usage Example

```python
from weebot.templates import TemplateEngine

engine = TemplateEngine()
engine.registry.load_builtin_templates()

result = engine.execute(
    "Research Analysis Workflow",
    {
        "topic": "Artificial Intelligence",
        "depth": "comprehensive",
        "output_format": "markdown"
    }
)
```
'''
    
    write_file(BUILTIN_DIR / "README.md", content)
    print()

def main():
    """Main setup function."""
    print("=" * 60)
    print("Phase 3 Template Engine Setup")
    print("=" * 60)
    print()
    
    create_directories()
    create_init_files()
    create_parser()
    create_parameters()
    create_registry()
    create_engine()
    create_test_parser()
    create_example_template()
    create_documentation()
    
    print("=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Run tests: pytest tests/unit/test_templates/test_parser.py -v")
    print("  2. Verify import: python -c \"from weebot.templates import TemplateParser\"")
    print("  3. Start building your templates!")
    print()

if __name__ == "__main__":
    main()
