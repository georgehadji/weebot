# 🚀 Phase 3 Implementation Guide

**Status:** Ready to Start  
**Date:** 2026-03-03  

---

## ⚠️ IMPORTANT: Directory Setup Required

Before implementing Phase 3, you need to create the following directory structure:

```bash
# Create directories manually or run:
mkdir -p weebot/templates/builtin
mkdir -p tests/unit/test_templates
```

---

## 📁 File Structure to Create

```
weebot/
├── templates/
│   ├── __init__.py              # Module exports
│   ├── parser.py                # YAML parser (Day 1)
│   ├── parameters.py            # Parameter resolution (Day 2)
│   ├── registry.py              # Template registry (Day 3)
│   ├── engine.py                # Main engine (Day 4-5)
│   └── builtin/                 # Built-in templates
│       ├── __init__.py
│       ├── research_analysis.yaml       # (Day 6)
│       ├── competitive_analysis.yaml    # (Day 7)
│       ├── data_processing.yaml         # (Day 7)
│       └── report_generation.yaml       # (Day 8)

tests/
└── unit/
    └── test_templates/
        ├── __init__.py
        ├── test_parser.py       # Parser tests
        ├── test_parameters.py   # Parameter tests
        ├── test_registry.py     # Registry tests
        └── test_engine.py       # Engine tests
```

---

## 📝 Day 1: Template Parser

### Step 1: Create `weebot/templates/__init__.py`

```python
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
```

### Step 2: Create `weebot/templates/parser.py`

```python
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
            raise TemplateValidationError("Template must have 'name' field")
        if "workflow" not in data:
            raise TemplateValidationError("Template must have 'workflow' field")
        
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
                f"Parameter '{name}' has unsupported type '{param_type}'"
            )
        
        return ParameterSchema(
            name=name,
            type=param_type,
            description=param_def.get("description", ""),
            required=param_def.get("required", True),
            default=param_def.get("default"),
            enum_values=param_def.get("values")
        )
```

### Step 3: Create `tests/unit/test_templates/__init__.py`

```python
"""Tests for template engine."""
```

### Step 4: Create `tests/unit/test_templates/test_parser.py`

```python
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
```

### Step 5: Run Tests

```bash
pytest tests/unit/test_templates/test_parser.py -v
```

**Expected:** All tests pass ✅

---

## 📊 Day 1 Success Criteria

- [ ] `weebot/templates/` directory created
- [ ] `parser.py` implemented
- [ ] `__init__.py` with exports
- [ ] 10+ tests passing
- [ ] Can parse simple YAML template
- [ ] Can parse template with parameters
- [ ] Validation errors work correctly

---

## 🚀 Next Steps

After Day 1 is complete:
1. Commit: `git add weebot/templates/ tests/unit/test_templates/`
2. Commit message: `feat(phase3): Add template parser`
3. Continue to Day 2: Parameter System

---

**Ready to start Day 1?** Create the directories and start coding! 💪
