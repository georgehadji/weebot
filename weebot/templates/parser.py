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
    
    def __init__(self, message: str, field: str = None):
        super().__init__(message)
        self.field = field


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
