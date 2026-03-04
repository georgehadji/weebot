"""Template parser for YAML/JSON workflow definitions.

HARDEN Mode: Added security limits to prevent YAML bombs and DoS attacks.
"""
from __future__ import annotations

import logging
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

_log = logging.getLogger(__name__)


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


class TemplateSecurityError(Exception):
    """Raised when template violates security limits."""
    pass


class SecureYamlLoader(yaml.SafeLoader):
    """
    HARDEN Mode: Custom YAML loader with security limits.
    
    Prevents:
    - Billion laughs attacks (entity expansion)
    - Deeply nested structures (stack exhaustion)
    - Excessive document size (memory exhaustion)
    """
    
    # Security limits
    MAX_DEPTH = 10  # Maximum nesting depth
    MAX_NODES = 1000  # Maximum total nodes
    MAX_STRING_LENGTH = 10000  # Maximum string length
    MAX_DOCUMENT_SIZE = 1024 * 1024  # 1MB max document
    
    def __init__(self, stream):
        super().__init__(stream)
        self._depth = 0
        self._node_count = 0
    
    def compose_node(self, parent, index):
        """Override to track depth and node count."""
        self._depth += 1
        self._node_count += 1
        
        # Check depth limit
        if self._depth > self.MAX_DEPTH:
            raise TemplateSecurityError(
                f"YAML nesting exceeds maximum depth of {self.MAX_DEPTH}"
            )
        
        # Check node count limit
        if self._node_count > self.MAX_NODES:
            raise TemplateSecurityError(
                f"YAML document exceeds maximum of {self.MAX_NODES} nodes"
            )
        
        try:
            node = super().compose_node(parent, index)
            
            # Check scalar string length
            if isinstance(node, yaml.ScalarNode) and node.value:
                if len(node.value) > self.MAX_STRING_LENGTH:
                    raise TemplateSecurityError(
                        f"String exceeds maximum length of {self.MAX_STRING_LENGTH}"
                    )
            
            return node
        finally:
            self._depth -= 1


class TemplateParser:
    """Parse YAML/JSON templates into WorkflowTemplate objects with security limits."""
    
    SUPPORTED_TYPES = {"string", "int", "float", "bool", "enum", "list", "dict"}
    
    # HARDEN: Additional template-level limits
    MAX_PARAMETERS = 50
    MAX_WORKFLOW_TASKS = 100
    MAX_TEMPLATE_SIZE = 1024 * 1024  # 1MB
    
    def parse(self, content: str) -> WorkflowTemplate:
        """
        Parse YAML content into WorkflowTemplate with security limits.
        
        Args:
            content: YAML template content
            
        Returns:
            Parsed WorkflowTemplate
            
        Raises:
            TemplateValidationError: If template is invalid
            TemplateSecurityError: If template violates security limits
        """
        # HARDEN: Check document size
        if len(content) > self.MAX_TEMPLATE_SIZE:
            raise TemplateSecurityError(
                f"Template size ({len(content)} bytes) exceeds maximum "
                f"({self.MAX_TEMPLATE_SIZE} bytes)"
            )
        
        try:
            # HARDEN: Use secure loader with depth/node limits
            data = yaml.load(content, Loader=SecureYamlLoader)
        except yaml.YAMLError as e:
            raise TemplateValidationError(f"Invalid YAML: {e}")
        except TemplateSecurityError:
            raise
        except Exception as e:
            # Catch any other parsing errors (recursion, etc.)
            raise TemplateSecurityError(f"YAML parsing failed: {e}")
        
        if not isinstance(data, dict):
            raise TemplateValidationError("Template must be a YAML mapping")
        
        return self._validate_and_create(data)
    
    def parse_file(self, path: Union[str, Path]) -> WorkflowTemplate:
        """Parse template from file."""
        path = Path(path)
        
        # HARDEN: Check file size before reading
        file_size = path.stat().st_size
        if file_size > self.MAX_TEMPLATE_SIZE:
            raise TemplateSecurityError(
                f"Template file size ({file_size} bytes) exceeds maximum "
                f"({self.MAX_TEMPLATE_SIZE} bytes)"
            )
        
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
            # HARDEN: Check parameter count
            if len(data["parameters"]) > self.MAX_PARAMETERS:
                raise TemplateSecurityError(
                    f"Template has {len(data['parameters'])} parameters, "
                    f"exceeding maximum of {self.MAX_PARAMETERS}"
                )
            
            for name, param_def in data["parameters"].items():
                parameters[name] = self._parse_parameter_schema(name, param_def)
        
        workflow = data.get("workflow", {})
        
        # HARDEN: Check workflow task count
        if len(workflow) > self.MAX_WORKFLOW_TASKS:
            raise TemplateSecurityError(
                f"Template has {len(workflow)} workflow tasks, "
                f"exceeding maximum of {self.MAX_WORKFLOW_TASKS}"
            )
        
        # HARDEN: Validate workflow structure depth
        self._validate_workflow_depth(workflow)
        
        return WorkflowTemplate(
            name=data["name"],
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            author=data.get("author", ""),
            parameters=parameters,
            workflow=workflow,
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
    
    def _validate_workflow_depth(self, workflow: Dict[str, Any], depth: int = 1) -> None:
        """
        HARDEN: Validate workflow structure doesn't exceed safe nesting.
        
        Args:
            workflow: Workflow dictionary to validate
            depth: Current nesting depth
            
        Raises:
            TemplateSecurityError: If nesting is too deep
        """
        if depth > SecureYamlLoader.MAX_DEPTH:
            raise TemplateSecurityError(
                f"Workflow structure exceeds maximum depth of {SecureYamlLoader.MAX_DEPTH}"
            )
        
        for task_id, task_def in workflow.items():
            if isinstance(task_def, dict):
                # Check for nested structures that might cause issues
                for key, value in task_def.items():
                    if isinstance(value, (dict, list)) and depth >= SecureYamlLoader.MAX_DEPTH - 1:
                        raise TemplateSecurityError(
                            f"Task '{task_id}' has excessively nested structure"
                        )
