"""Tests for template registry."""
from __future__ import annotations

import pytest
from pathlib import Path

from weebot.templates.registry import TemplateRegistry
from weebot.templates.parser import WorkflowTemplate, ParameterSchema, TemplateValidationError


class TestTemplateRegistryBasic:
    """Test basic registry operations."""
    
    @pytest.fixture
    def registry(self):
        return TemplateRegistry()
    
    @pytest.fixture
    def sample_template(self):
        return WorkflowTemplate(
            name="Test Template",
            version="1.0.0",
            description="A test template",
            author="Test Author",
            parameters={},
            workflow={"task1": {}}
        )
    
    def test_register_and_get(self, registry, sample_template):
        """Register and retrieve a template."""
        registry.register(sample_template)
        
        retrieved = registry.get("Test Template")
        assert retrieved is not None
        assert retrieved.name == "Test Template"
        assert retrieved.version == "1.0.0"
    
    def test_register_duplicate_raises_error(self, registry, sample_template):
        """Registering duplicate template raises ValueError."""
        registry.register(sample_template)
        
        with pytest.raises(ValueError, match="already registered"):
            registry.register(sample_template)
    
    def test_get_nonexistent_returns_none(self, registry):
        """Getting non-existent template returns None."""
        assert registry.get("NonExistent") is None
    
    def test_get_required_raises_keyerror(self, registry):
        """get_required raises KeyError for missing template."""
        with pytest.raises(KeyError, match="not found"):
            registry.get_required("NonExistent")
    
    def test_unregister(self, registry, sample_template):
        """Unregister removes template."""
        registry.register(sample_template)
        assert registry.has_template("Test Template")
        
        result = registry.unregister("Test Template")
        assert result is True
        assert not registry.has_template("Test Template")
    
    def test_unregister_nonexistent_returns_false(self, registry):
        """Unregistering non-existent template returns False."""
        result = registry.unregister("NonExistent")
        assert result is False
    
    def test_clear(self, registry, sample_template):
        """Clear removes all templates."""
        registry.register(sample_template)
        assert len(registry) == 1
        
        registry.clear()
        assert len(registry) == 0
        assert registry.list_templates() == []
    
    def test_list_templates_sorted(self, registry):
        """list_templates returns sorted names."""
        template_a = WorkflowTemplate(name="Z Template", version="1.0", workflow={})
        template_b = WorkflowTemplate(name="A Template", version="1.0", workflow={})
        template_c = WorkflowTemplate(name="M Template", version="1.0", workflow={})
        
        registry.register(template_a)
        registry.register(template_b)
        registry.register(template_c)
        
        names = registry.list_templates()
        assert names == ["A Template", "M Template", "Z Template"]
    
    def test_contains_operator(self, registry, sample_template):
        """Test 'in' operator."""
        registry.register(sample_template)
        
        assert "Test Template" in registry
        assert "NonExistent" not in registry
    
    def test_len(self, registry, sample_template):
        """Test len() operator."""
        assert len(registry) == 0
        
        registry.register(sample_template)
        assert len(registry) == 1


class TestTemplateRegistrySearch:
    """Test search functionality."""
    
    @pytest.fixture
    def populated_registry(self):
        registry = TemplateRegistry()
        
        templates = [
            WorkflowTemplate(
                name="Research Analysis",
                version="1.0",
                description="Performs research analysis",
                author="Alice",
                workflow={}
            ),
            WorkflowTemplate(
                name="Data Processing",
                version="1.0",
                description="Processes data files",
                author="Bob",
                workflow={}
            ),
            WorkflowTemplate(
                name="Report Generation",
                version="1.0",
                description="Generates reports from research",
                author="Alice",
                workflow={}
            ),
        ]
        
        for t in templates:
            registry.register(t)
        
        return registry
    
    def test_search_by_name(self, populated_registry):
        """Search by template name."""
        results = populated_registry.search("research")
        assert len(results) == 2  # Research Analysis, Report Generation
        names = [r.name for r in results]
        assert "Research Analysis" in names
        assert "Report Generation" in names
    
    def test_search_by_description(self, populated_registry):
        """Search by description."""
        results = populated_registry.search("processes data")
        assert len(results) == 1
        assert results[0].name == "Data Processing"
    
    def test_search_by_author(self, populated_registry):
        """Search by author."""
        results = populated_registry.search("Alice")
        assert len(results) == 2
    
    def test_search_case_insensitive(self, populated_registry):
        """Search is case-insensitive."""
        results_lower = populated_registry.search("research")
        results_upper = populated_registry.search("RESEARCH")
        assert len(results_lower) == len(results_upper)
    
    def test_filter_by_author(self, populated_registry):
        """Filter by exact author match."""
        results = populated_registry.filter_by_author("Alice")
        assert len(results) == 2
        
        results = populated_registry.filter_by_author("Bob")
        assert len(results) == 1
        assert results[0].name == "Data Processing"
    
    def test_filter_by_parameter(self, populated_registry):
        """Filter by parameter presence."""
        # Add template with specific parameter
        template_with_param = WorkflowTemplate(
            name="Template With Param",
            version="1.0",
            parameters={
                "special_param": ParameterSchema(
                    name="special_param",
                    type="string",
                    required=True
                )
            },
            workflow={}
        )
        populated_registry.register(template_with_param)
        
        results = populated_registry.filter_by_parameter("special_param")
        assert len(results) == 1
        assert results[0].name == "Template With Param"


class TestTemplateRegistryFileLoading:
    """Test loading templates from files."""
    
    @pytest.fixture
    def registry(self):
        return TemplateRegistry()
    
    @pytest.fixture
    def temp_template_file(self, tmp_path):
        """Create a temporary template file."""
        template_content = """
name: "Test From File"
version: "2.0.0"
description: "Loaded from file"
author: "Test"
parameters:
  input:
    type: string
    required: true
workflow:
  task1:
    agent_role: "test"
"""
        file_path = tmp_path / "test_template.yaml"
        file_path.write_text(template_content)
        return file_path
    
    def test_load_from_file(self, registry, temp_template_file):
        """Load template from file."""
        template = registry.load_from_file(temp_template_file)
        
        assert template.name == "Test From File"
        assert template.version == "2.0.0"
        assert registry.has_template("Test From File")
    
    def test_load_from_file_not_found(self, registry):
        """Loading non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            registry.load_from_file("/nonexistent/path/template.yaml")
    
    def test_load_from_directory(self, registry, tmp_path):
        """Load all templates from directory."""
        # Create multiple template files
        for i in range(3):
            content = f"""
name: "Template {i}"
version: "1.0"
workflow:
  task: {{}}
"""
            (tmp_path / f"template_{i}.yaml").write_text(content)
        
        # Create a non-template file
        (tmp_path / "not_a_template.txt").write_text("not a template")
        
        count = registry.load_from_directory(tmp_path)
        
        assert count == 3
        assert len(registry) == 3
        assert registry.has_template("Template 0")
        assert registry.has_template("Template 1")
        assert registry.has_template("Template 2")
    
    def test_load_from_directory_not_found(self, registry, tmp_path):
        """Loading from non-existent directory returns 0."""
        count = registry.load_from_directory(tmp_path / "nonexistent")
        assert count == 0
    
    def test_load_errors_collected(self, registry, tmp_path):
        """Load errors are collected and accessible."""
        # Create a valid template
        valid = tmp_path / "valid.yaml"
        valid.write_text("name: Valid\nworkflow: {}\n")
        
        # Create an invalid template
        invalid = tmp_path / "invalid.yaml"
        invalid.write_text("invalid: yaml: content: [")
        
        # Create a template that will fail validation
        bad_template = tmp_path / "bad.yaml"
        bad_template.write_text("name: Bad\nworkflow: {}\n")
        
        # Register "Bad" first to cause duplicate error
        registry.register(WorkflowTemplate(name="Bad", version="1.0", workflow={}))
        
        count = registry.load_from_directory(tmp_path)
        
        # Should load 1 (valid)
        assert count == 1
        
        # Should have 2 errors
        errors = registry.get_load_errors()
        assert len(errors) == 2


class TestTemplateRegistryMetadata:
    """Test metadata functionality."""
    
    @pytest.fixture
    def registry_with_templates(self):
        registry = TemplateRegistry()
        
        template = WorkflowTemplate(
            name="Complex Template",
            version="3.0.0",
            description="A complex template",
            author="Developer",
            parameters={
                "param1": ParameterSchema(
                    name="param1",
                    type="string",
                    required=True
                ),
                "param2": ParameterSchema(
                    name="param2",
                    type="int",
                    required=False,
                    default=42
                )
            },
            workflow={}
        )
        
        registry.register(template)
        return registry
    
    def test_get_metadata(self, registry_with_templates):
        """Get template metadata."""
        metadata = registry_with_templates.get_metadata("Complex Template")
        
        assert metadata is not None
        assert metadata["name"] == "Complex Template"
        assert metadata["version"] == "3.0.0"
        assert metadata["description"] == "A complex template"
        assert metadata["author"] == "Developer"
        assert metadata["parameter_count"] == 2
        assert len(metadata["parameters"]) == 2
    
    def test_get_metadata_nonexistent(self, registry_with_templates):
        """Metadata for non-existent template returns None."""
        assert registry_with_templates.get_metadata("NonExistent") is None
    
    def test_list_metadata(self, registry_with_templates):
        """List metadata for all templates."""
        metadata_list = registry_with_templates.list_metadata()
        
        assert len(metadata_list) == 1
        assert metadata_list[0]["name"] == "Complex Template"
    
    def test_get_statistics(self, registry_with_templates):
        """Get registry statistics."""
        stats = registry_with_templates.get_statistics()
        
        assert stats["total_templates"] == 1
        assert stats["total_parameters"] == 2
        assert stats["authors"] == ["Developer"]
        assert stats["avg_parameters_per_template"] == 2.0
    
    def test_get_statistics_empty(self):
        """Statistics for empty registry."""
        registry = TemplateRegistry()
        stats = registry.get_statistics()
        
        assert stats["total_templates"] == 0
        assert stats["total_parameters"] == 0
        assert stats["authors"] == []
        assert stats["avg_parameters_per_template"] == 0
