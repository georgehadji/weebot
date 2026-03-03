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
