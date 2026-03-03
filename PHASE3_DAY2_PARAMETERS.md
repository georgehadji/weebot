# Phase 3 - Day 2: Parameter Resolution System

## Overview

Day 2 implements the parameter resolution system that validates and resolves template parameters with type checking and default value handling.

---

## 🎯 Goals

1. **Type Validation**: Validate parameter values against their schemas
2. **Default Values**: Handle optional parameters with defaults
3. **Coercion**: Convert string inputs to proper types
4. **Error Messages**: Clear validation error messages

---

## 📁 File to Update

### `weebot/templates/parameters.py`

Replace the placeholder with the full implementation:

```python
"""Parameter resolution for workflow templates."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from weebot.templates.parser import ParameterSchema, WorkflowTemplate


class ParameterValidationError(Exception):
    """Raised when parameter validation fails."""
    
    def __init__(self, message: str, parameter: str = None, 
                 expected_type: str = None, actual_value: Any = None):
        super().__init__(message)
        self.parameter = parameter
        self.expected_type = expected_type
        self.actual_value = actual_value


class ParameterResolver:
    """
    Resolve and validate template parameters.
    
    Features:
    - Type validation and coercion
    - Required parameter checking
    - Default value handling
    - Enum value validation
    """
    
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
                                    or type validation fails
        """
        provided = provided or {}
        resolved = {}
        
        for name, schema in template.parameters.items():
            if name in provided:
                value = provided[name]
                resolved[name] = self._validate_and_convert(name, value, schema)
            elif schema.default is not None:
                resolved[name] = schema.default
            elif schema.required:
                raise ParameterValidationError(
                    f"Required parameter '{name}' not provided",
                    parameter=name
                )
        
        return resolved
    
    def _validate_and_convert(self, name: str, value: Any, 
                               schema: ParameterSchema) -> Any:
        """
        Validate and convert a value to match its schema.
        
        Args:
            name: Parameter name (for error messages)
            value: Value to validate
            schema: Parameter schema
            
        Returns:
            Converted value
            
        Raises:
            ParameterValidationError: If validation fails
        """
        param_type = schema.type
        
        # Handle enum type specially
        if param_type == "enum":
            if schema.enum_values and value not in schema.enum_values:
                raise ParameterValidationError(
                    f"Parameter '{name}' must be one of {schema.enum_values}, "
                    f"got '{value}'",
                    parameter=name,
                    expected_type=f"enum({schema.enum_values})",
                    actual_value=value
                )
            return value
        
        # Type coercion and validation
        try:
            if param_type == "string":
                return str(value)
            
            elif param_type == "int":
                if isinstance(value, bool):
                    raise ValueError("Boolean not allowed for int type")
                return int(value)
            
            elif param_type == "float":
                if isinstance(value, bool):
                    raise ValueError("Boolean not allowed for float type")
                return float(value)
            
            elif param_type == "bool":
                if isinstance(value, str):
                    lower = value.lower()
                    if lower in ('true', '1', 'yes', 'on'):
                        return True
                    elif lower in ('false', '0', 'no', 'off'):
                        return False
                    else:
                        raise ValueError(f"Cannot convert '{value}' to bool")
                return bool(value)
            
            elif param_type == "list":
                if isinstance(value, str):
                    # Try to parse as JSON or comma-separated
                    import json
                    try:
                        parsed = json.loads(value)
                        if isinstance(parsed, list):
                            return parsed
                    except json.JSONDecodeError:
                        pass
                    # Fallback to comma-separated
                    return [item.strip() for item in value.split(',')]
                elif isinstance(value, list):
                    return value
                else:
                    raise ValueError(f"Cannot convert {type(value).__name__} to list")
            
            elif param_type == "dict":
                if isinstance(value, str):
                    import json
                    return json.loads(value)
                elif isinstance(value, dict):
                    return value
                else:
                    raise ValueError(f"Cannot convert {type(value).__name__} to dict")
            
            else:
                raise ParameterValidationError(
                    f"Unknown type '{param_type}' for parameter '{name}'",
                    parameter=name,
                    expected_type=param_type,
                    actual_value=value
                )
                
        except (ValueError, TypeError) as e:
            raise ParameterValidationError(
                f"Parameter '{name}' type error: {e}",
                parameter=name,
                expected_type=param_type,
                actual_value=value
            )
    
    def validate_only(self, template: WorkflowTemplate,
                     provided: Optional[Dict[str, Any]] = None) -> List[str]:
        """
        Validate parameters without resolving defaults.
        
        Returns list of validation error messages.
        Empty list means all parameters are valid.
        """
        provided = provided or {}
        errors = []
        
        for name, schema in template.parameters.items():
            if name in provided:
                try:
                    self._validate_and_convert(name, provided[name], schema)
                except ParameterValidationError as e:
                    errors.append(str(e))
            elif schema.required and schema.default is None:
                errors.append(f"Required parameter '{name}' not provided")
        
        return errors
```

---

## 🧪 Tests to Create

### `tests/unit/test_templates/test_parameters.py`

```python
"""Tests for parameter resolver."""
from __future__ import annotations

import pytest
from weebot.templates.parameters import ParameterResolver, ParameterValidationError
from weebot.templates.parser import WorkflowTemplate, ParameterSchema


class TestParameterResolver:
    """Test parameter resolution functionality."""
    
    @pytest.fixture
    def resolver(self):
        return ParameterResolver()
    
    @pytest.fixture
    def simple_template(self):
        return WorkflowTemplate(
            name="Test",
            version="1.0.0",
            parameters={
                "topic": ParameterSchema(
                    name="topic",
                    type="string",
                    required=True
                ),
                "count": ParameterSchema(
                    name="count",
                    type="int",
                    required=False,
                    default=10
                )
            },
            workflow={}
        )
    
    def test_resolve_required_parameter(self, resolver, simple_template):
        """Resolve required parameter successfully."""
        result = resolver.resolve(simple_template, {"topic": "AI"})
        
        assert result["topic"] == "AI"
        assert result["count"] == 10  # Default
    
    def test_missing_required_parameter(self, resolver, simple_template):
        """Missing required parameter raises error."""
        with pytest.raises(ParameterValidationError, match="topic"):
            resolver.resolve(simple_template, {})
    
    def test_string_type_coercion(self, resolver):
        """Convert values to strings."""
        template = WorkflowTemplate(
            name="Test",
            version="1.0.0",
            parameters={
                "value": ParameterSchema(name="value", type="string", required=True)
            },
            workflow={}
        )
        
        result = resolver.resolve(template, {"value": 123})
        assert result["value"] == "123"
        assert isinstance(result["value"], str)
    
    def test_int_type_validation(self, resolver):
        """Validate integer type."""
        template = WorkflowTemplate(
            name="Test",
            version="1.0.0",
            parameters={
                "count": ParameterSchema(name="count", type="int", required=True)
            },
            workflow={}
        )
        
        # Valid conversions
        assert resolver.resolve(template, {"count": "42"})["count"] == 42
        assert resolver.resolve(template, {"count": 3.14})["count"] == 3
        
        # Boolean not allowed
        with pytest.raises(ParameterValidationError):
            resolver.resolve(template, {"count": True})
    
    def test_bool_type_coercion(self, resolver):
        """Convert various values to booleans."""
        template = WorkflowTemplate(
            name="Test",
            version="1.0.0",
            parameters={
                "flag": ParameterSchema(name="flag", type="bool", required=True)
            },
            workflow={}
        )
        
        # String conversions
        assert resolver.resolve(template, {"flag": "true"})["flag"] is True
        assert resolver.resolve(template, {"flag": "false"})["flag"] is False
        assert resolver.resolve(template, {"flag": "yes"})["flag"] is True
        assert resolver.resolve(template, {"flag": "no"})["flag"] is False
        assert resolver.resolve(template, {"flag": "1"})["flag"] is True
        assert resolver.resolve(template, {"flag": "0"})["flag"] is False
    
    def test_enum_validation(self, resolver):
        """Validate enum values."""
        template = WorkflowTemplate(
            name="Test",
            version="1.0.0",
            parameters={
                "level": ParameterSchema(
                    name="level",
                    type="enum",
                    required=True,
                    enum_values=["low", "medium", "high"]
                )
            },
            workflow={}
        )
        
        # Valid value
        assert resolver.resolve(template, {"level": "medium"})["level"] == "medium"
        
        # Invalid value
        with pytest.raises(ParameterValidationError, match="low.*medium.*high"):
            resolver.resolve(template, {"level": "invalid"})
    
    def test_list_type_parsing(self, resolver):
        """Parse list from string or list."""
        template = WorkflowTemplate(
            name="Test",
            version="1.0.0",
            parameters={
                "items": ParameterSchema(name="items", type="list", required=True)
            },
            workflow={}
        )
        
        # JSON array
        assert resolver.resolve(template, {"items": '["a", "b", "c"]'})["items"] == ["a", "b", "c"]
        
        # Comma-separated string
        assert resolver.resolve(template, {"items": "a, b, c"})["items"] == ["a", "b", "c"]
        
        # List input
        assert resolver.resolve(template, {"items": ["x", "y"]})["items"] == ["x", "y"]
    
    def test_dict_type_parsing(self, resolver):
        """Parse dict from JSON string or dict."""
        template = WorkflowTemplate(
            name="Test",
            version="1.0.0",
            parameters={
                "config": ParameterSchema(name="config", type="dict", required=True)
            },
            workflow={}
        )
        
        # JSON object
        result = resolver.resolve(template, {"config": '{"key": "value"}'})
        assert result["config"] == {"key": "value"}
        
        # Dict input
        result = resolver.resolve(template, {"config": {"a": 1}})
        assert result["config"] == {"a": 1}


class TestParameterValidationOnly:
    """Test validate_only method."""
    
    def test_no_errors_for_valid_params(self):
        """Empty list returned for valid params."""
        resolver = ParameterResolver()
        template = WorkflowTemplate(
            name="Test",
            version="1.0.0",
            parameters={
                "name": ParameterSchema(name="name", type="string", required=True)
            },
            workflow={}
        )
        
        errors = resolver.validate_only(template, {"name": "test"})
        assert errors == []
    
    def test_errors_for_invalid_params(self):
        """List of errors returned for invalid params."""
        resolver = ParameterResolver()
        template = WorkflowTemplate(
            name="Test",
            version="1.0.0",
            parameters={
                "count": ParameterSchema(name="count", type="int", required=True)
            },
            workflow={}
        )
        
        errors = resolver.validate_only(template, {"count": "not_a_number"})
        assert len(errors) == 1
        assert "type error" in errors[0].lower()
```

---

## ✅ Success Criteria

- [ ] All parameter types validated correctly
- [ ] Type coercion works (string→int, string→bool, etc.)
- [ ] Enum validation works
- [ ] Required parameter checking works
- [ ] Default values applied correctly
- [ ] Clear error messages for validation failures
- [ ] 15+ tests passing

---

## 🚀 Next Steps

After Day 2:
1. Run tests: `pytest tests/unit/test_templates/test_parameters.py -v`
2. Continue to Day 3: Template Registry
