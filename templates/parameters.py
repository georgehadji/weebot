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