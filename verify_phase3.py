#!/usr/bin/env python3
"""Quick verification script for Phase 3 (Complete)."""
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Test that all imports work."""
    print("Testing imports...")
    try:
        from weebot.templates import (
            TemplateParser,
            WorkflowTemplate,
            TemplateValidationError,
            ParameterResolver,
            ParameterValidationError,
            TemplateRegistry,
            TemplateEngine,
        )
        print("  ✅ All imports successful")
        return True
    except Exception as e:
        print(f"  ❌ Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_parser_basic():
    """Test basic parser functionality."""
    print("\nTesting parser (Day 1)...")
    from weebot.templates import TemplateParser
    
    parser = TemplateParser()
    
    # Test 1: Simple template
    yaml_content = """
name: "Test Workflow"
version: "1.0.0"
description: "A test workflow"
parameters: {}
workflow:
  task1:
    agent_role: "test"
"""
    try:
        template = parser.parse(yaml_content)
        assert template.name == "Test Workflow"
        assert template.version == "1.0.0"
        print("  ✅ Simple template parsing")
    except Exception as e:
        print(f"  ❌ Simple template failed: {e}")
        return False
    
    # Test 2: Template with parameters
    yaml_content2 = """
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
    try:
        template = parser.parse(yaml_content2)
        assert "topic" in template.parameters
        assert template.parameters["topic"].type == "string"
        assert "depth" in template.parameters
        assert template.parameters["depth"].default == "brief"
        print("  ✅ Parameter parsing")
    except Exception as e:
        print(f"  ❌ Parameter parsing failed: {e}")
        return False
    
    # Test 3: Validation error for missing name
    try:
        parser.parse("workflow:\n  task1: {}")
        print("  ❌ Missing name validation failed")
        return False
    except Exception as e:
        if "name" in str(e).lower():
            print("  ✅ Missing name validation")
        else:
            print(f"  ❌ Wrong error: {e}")
            return False
    
    return True

def test_parameter_resolver():
    """Test parameter resolver."""
    print("\nTesting parameter resolver (Day 2)...")
    from weebot.templates import ParameterResolver, ParameterValidationError
    from weebot.templates.parser import WorkflowTemplate, ParameterSchema
    
    resolver = ParameterResolver()
    
    # Create test template
    template = WorkflowTemplate(
        name="Test",
        version="1.0.0",
        parameters={
            "topic": ParameterSchema(name="topic", type="string", required=True),
            "count": ParameterSchema(name="count", type="int", required=False, default=10),
            "level": ParameterSchema(
                name="level", 
                type="enum", 
                required=True,
                enum_values=["low", "high"]
            ),
        },
        workflow={}
    )
    
    # Test 1: Basic resolution
    try:
        result = resolver.resolve(template, {"topic": "AI", "level": "high"})
        assert result["topic"] == "AI"
        assert result["count"] == 10  # Default
        assert result["level"] == "high"
        print("  ✅ Basic parameter resolution")
    except Exception as e:
        print(f"  ❌ Basic resolution failed: {e}")
        return False
    
    # Test 2: Type coercion
    try:
        result = resolver.resolve(template, {"topic": 123, "count": "42", "level": "low"})
        assert result["topic"] == "123"  # Converted to string
        assert result["count"] == 42     # Converted to int
        print("  ✅ Type coercion")
    except Exception as e:
        print(f"  ❌ Type coercion failed: {e}")
        return False
    
    # Test 3: Enum validation
    try:
        resolver.resolve(template, {"topic": "AI", "level": "invalid"})
        print("  ❌ Enum validation failed")
        return False
    except ParameterValidationError:
        print("  ✅ Enum validation")
    except Exception as e:
        print(f"  ❌ Wrong error: {e}")
        return False
    
    # Test 4: Missing required parameter
    try:
        resolver.resolve(template, {})
        print("  ❌ Missing required validation failed")
        return False
    except ParameterValidationError:
        print("  ✅ Missing required validation")
    except Exception as e:
        print(f"  ❌ Wrong error: {e}")
        return False
    
    return True

def test_template_registry():
    """Test template registry."""
    print("\nTesting template registry (Day 3)...")
    from weebot.templates import TemplateRegistry
    from weebot.templates.parser import WorkflowTemplate
    
    registry = TemplateRegistry()
    
    # Test 1: Register and get
    template = WorkflowTemplate(
        name="Test Template",
        version="1.0",
        description="Test",
        author="Tester",
        workflow={}
    )
    
    try:
        registry.register(template)
        retrieved = registry.get("Test Template")
        assert retrieved is not None
        assert retrieved.name == "Test Template"
        print("  ✅ Register and get")
    except Exception as e:
        print(f"  ❌ Register/get failed: {e}")
        return False
    
    # Test 2: List templates
    try:
        names = registry.list_templates()
        assert "Test Template" in names
        print("  ✅ List templates")
    except Exception as e:
        print(f"  ❌ List failed: {e}")
        return False
    
    # Test 3: Search
    try:
        results = registry.search("test")
        assert len(results) == 1
        print("  ✅ Search")
    except Exception as e:
        print(f"  ❌ Search failed: {e}")
        return False
    
    # Test 4: Filter by author
    try:
        results = registry.filter_by_author("Tester")
        assert len(results) == 1
        print("  ✅ Filter by author")
    except Exception as e:
        print(f"  ❌ Filter failed: {e}")
        return False
    
    # Test 5: Metadata
    try:
        metadata = registry.get_metadata("Test Template")
        assert metadata is not None
        assert metadata["name"] == "Test Template"
        assert metadata["author"] == "Tester"
        print("  ✅ Metadata")
    except Exception as e:
        print(f"  ❌ Metadata failed: {e}")
        return False
    
    # Test 6: Statistics
    try:
        stats = registry.get_statistics()
        assert stats["total_templates"] == 1
        assert "Tester" in stats["authors"]
        print("  ✅ Statistics")
    except Exception as e:
        print(f"  ❌ Statistics failed: {e}")
        return False
    
    # Test 7: Load built-in templates
    try:
        count = registry.load_builtin_templates()
        print(f"  ✅ Loaded {count} built-in templates")
    except Exception as e:
        print(f"  ❌ Load built-ins failed: {e}")
        return False
    
    return True

def test_template_engine():
    """Test template execution engine."""
    print("\nTesting template engine (Day 4-5)...")
    from weebot.templates import TemplateEngine, TemplateExecutionResult
    from weebot.templates.parser import WorkflowTemplate, ParameterSchema
    
    engine = TemplateEngine()
    
    # Test 1: Register task handler and execute
    execution_log = []
    
    def mock_handler(task_def, context):
        execution_log.append(task_def.get("task", ""))
        return {"status": "completed"}
    
    try:
        engine.register_task_handler("agent_task", mock_handler)
        assert engine.has_task_handler("agent_task")
        print("  ✅ Register task handler")
    except Exception as e:
        print(f"  ❌ Register handler failed: {e}")
        return False
    
    # Test 2: Execute template
    template = WorkflowTemplate(
        name="Engine Test",
        version="1.0",
        parameters={
            "topic": ParameterSchema(name="topic", type="string", required=True)
        },
        workflow={
            "research": {
                "type": "agent_task",
                "task": "Research {{topic}}"
            }
        },
        output={
            "summary": "Research on {{topic}}"
        }
    )
    
    try:
        engine.registry.register(template)
        result = engine.execute("Engine Test", {"topic": "AI"})
        
        assert isinstance(result, TemplateExecutionResult)
        assert result.success is True
        assert result.parameters["topic"] == "AI"
        assert len(execution_log) == 1
        assert execution_log[0] == "Research AI"  # Template was resolved!
        print("  ✅ Execute template with resolution")
    except Exception as e:
        print(f"  ❌ Execute failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test 3: Dry run
    try:
        result = engine.execute("Engine Test", {"topic": "ML"}, dry_run=True)
        assert result.success is True
        assert result.output["status"] == "validated"
        print("  ✅ Dry run validation")
    except Exception as e:
        print(f"  ❌ Dry run failed: {e}")
        return False
    
    # Test 4: Execute template object directly
    try:
        template2 = WorkflowTemplate(
            name="Direct Test",
            version="1.0",
            parameters={},
            workflow={"task1": {"type": "agent_task"}},
            output={}
        )
        result = engine.execute_template(template2)
        assert result.success is True
        print("  ✅ Execute template object")
    except Exception as e:
        print(f"  ❌ Direct execute failed: {e}")
        return False
    
    # Test 5: Quick execute from YAML
    try:
        yaml_template = """
name: Quick Test
version: "1.0"
parameters:
  name:
    type: string
    required: true
workflow:
  greet:
    type: agent_task
    task: "Hello {{name}}"
output:
  greeting: "Completed for {{name}}"
"""
        result = engine.quick_execute(yaml_template, {"name": "World"})
        assert result.success is True
        print("  ✅ Quick execute from YAML")
    except Exception as e:
        print(f"  ❌ Quick execute failed: {e}")
        return False
    
    # Test 6: Template not found
    try:
        result = engine.execute("NonExistent")
        assert result.success is False
        assert "not found" in result.error.lower()
        print("  ✅ Error handling for missing template")
    except Exception as e:
        print(f"  ❌ Error handling failed: {e}")
        return False
    
    return True

def test_builtin_template():
    """Test loading the built-in template."""
    print("\nTesting built-in template...")
    from weebot.templates import TemplateParser, TemplateEngine
    
    parser = TemplateParser()
    template_path = Path("weebot/templates/builtin/research_analysis.yaml")
    
    if not template_path.exists():
        print(f"  ❌ Template not found: {template_path}")
        return False
    
    try:
        template = parser.parse_file(template_path)
        print(f"  ✅ Loaded: {template.name}")
        print(f"     Version: {template.version}")
        print(f"     Parameters: {list(template.parameters.keys())}")
        
        # Try dry run execution
        engine = TemplateEngine()
        engine.registry.register(template)
        
        result = engine.execute(
            "Research Analysis Workflow",
            {
                "topic": "Artificial Intelligence",
                "depth": "comprehensive",
                "output_format": "markdown",
                "include_sources": True
            },
            dry_run=True
        )
        
        if result.success:
            print(f"  ✅ Dry run validation passed")
        else:
            print(f"  ❌ Dry run failed: {result.error}")
            return False
        
        return True
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("=" * 60)
    print("Phase 3 - Complete Verification")
    print("=" * 60)
    
    results = []
    results.append(("Imports", test_imports()))
    results.append(("Parser (Day 1)", test_parser_basic()))
    results.append(("Parameters (Day 2)", test_parameter_resolver()))
    results.append(("Registry (Day 3)", test_template_registry()))
    results.append(("Engine (Day 4-5)", test_template_engine()))
    results.append(("Built-in Template", test_builtin_template()))
    
    print("\n" + "=" * 60)
    print("Results Summary")
    print("=" * 60)
    
    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)
    
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {name}")
    
    all_passed = all(passed for _, passed in results)
    
    print("\n" + "=" * 60)
    print(f"Score: {passed_count}/{total_count} tests passed")
    print("=" * 60)
    
    if all_passed:
        print("\n🎉🎉🎉 Phase 3 COMPLETE! 🎉🎉🎉")
        print("\nYou now have a full Template Engine with:")
        print("  ✅ YAML template parsing")
        print("  ✅ Parameter validation & coercion")
        print("  ✅ Template registry with search")
        print("  ✅ Execution engine with handlers")
        print("  ✅ Built-in example templates")
        print("\nNext steps:")
        print("  1. Run full test suite: pytest tests/unit/test_templates/ -v")
        print("  2. Add more built-in templates")
        print("  3. Integrate with your agent system!")
    else:
        print("\n⚠️  Some verifications failed. Check output above.")
    print("=" * 60)
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
