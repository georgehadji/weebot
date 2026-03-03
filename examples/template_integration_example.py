#!/usr/bin/env python3
"""
Example: Template Engine Integration

Shows how to use the Template Engine with Weebot core systems.
"""
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def example_basic_usage():
    """Basic template engine usage."""
    print("=" * 60)
    print("Example 1: Basic Template Engine Usage")
    print("=" * 60)
    
    from weebot.templates import TemplateEngine
    
    # Create engine
    engine = TemplateEngine()
    
    # Load built-in templates
    count = engine.registry.load_builtin_templates()
    print(f"Loaded {count} built-in templates")
    
    # List available templates
    templates = engine.registry.list_templates()
    print(f"\nAvailable templates:")
    for name in templates:
        print(f"  - {name}")
    
    # Show template metadata
    if templates:
        metadata = engine.registry.get_metadata(templates[0])
        print(f"\nTemplate: {metadata['name']}")
        print(f"   Version: {metadata['version']}")
        print(f"   Description: {metadata['description'][:60]}...")
        print(f"   Parameters: {metadata['parameter_count']}")
    
    print()


def example_execute_template():
    """Execute a template with parameters."""
    print("=" * 60)
    print("Example 2: Execute Template")
    print("=" * 60)
    
    from weebot.templates import TemplateEngine
    from weebot.templates.parser import WorkflowTemplate, ParameterSchema
    
    engine = TemplateEngine()
    
    # Create a simple template
    template = WorkflowTemplate(
        name="Greeting Workflow",
        version="1.0.0",
        description="Simple greeting example",
        parameters={
            "name": ParameterSchema(name="name", type="string", required=True),
            "greeting": ParameterSchema(
                name="greeting", 
                type="enum", 
                required=False,
                default="Hello",
                enum_values=["Hello", "Hi", "Hey"]
            ),
        },
        workflow={
            "greet": {
                "type": "agent_task",
                "agent_role": "assistant",
                "task": "Say {{greeting}} to {{name}}",
            }
        },
        output={
            "message": "{{greeting}}, {{name}}!"
        }
    )
    
    # Register and execute
    engine.registry.register(template)
    
    # Dry run first
    print("Dry run validation:")
    result = engine.execute("Greeting Workflow", {"name": "World"}, dry_run=True)
    print(f"   Success: {result.success}")
    print(f"   Status: {result.output.get('status')}")
    
    # Actual execution (simulated)
    print("\nExecuting:")
    result = engine.execute("Greeting Workflow", {"name": "Alice", "greeting": "Hi"})
    print(f"   Success: {result.success}")
    print(f"   Parameters: {result.parameters}")
    print(f"   Output: {result.output}")
    print(f"   Execution time: {result.execution_time_ms}ms")
    
    print()


def example_integration():
    """Use the full integration with orchestrator."""
    print("=" * 60)
    print("Example 3: Full Integration")
    print("=" * 60)
    
    try:
        from weebot.templates.integration import create_integrated_engine
        
        # Create integrated engine
        integration = create_integrated_engine(
            load_builtin=True,
            use_orchestrator=False,  # Disable for example (no dependencies)
        )
        
        print("Integrated engine created")
        print(f"   Loaded templates: {len(integration.engine.registry)}")
        
        # Use CLI interface
        from weebot.templates.integration import TemplateCLI
        cli = TemplateCLI(integration)
        
        # List templates
        templates = cli.list_templates()
        print(f"\nTemplates: {', '.join(templates[:3])}")
        
        # Show details
        if templates:
            metadata = cli.show_template(templates[0])
            print(f"\n{metadata['name']}")
            print(f"   Author: {metadata['author']}")
            print(f"   Parameters ({metadata['parameter_count']}):")
            for param in metadata['parameters']:
                req = "required" if param['required'] else "optional"
                print(f"     - {param['name']} ({param['type']}, {req})")
        
    except ImportError as e:
        print(f"Integration not available: {e}")
    
    print()


def example_yaml_template():
    """Create and execute template from YAML."""
    print("=" * 60)
    print("Example 4: YAML Template")
    print("=" * 60)
    
    from weebot.templates import TemplateEngine
    
    engine = TemplateEngine()
    
    # Define template in YAML
    yaml_template = """
name: "Quick Analysis"
version: "1.0.0"
description: "Quick data analysis workflow"

parameters:
  dataset:
    type: string
    description: "Dataset name"
    required: true
  
  analysis_type:
    type: enum
    values: ["summary", "detailed"]
    default: "summary"
    required: false

workflow:
  load_data:
    type: agent_task
    agent_role: data_engineer
    task: "Load dataset: {{dataset}}"
  
  analyze:
    type: agent_task
    agent_role: data_analyst
    task: "Perform {{analysis_type}} analysis on {{dataset}}"
    depends_on: [load_data]
  
  report:
    type: agent_task
    agent_role: writer
    task: "Generate report for {{dataset}}"
    depends_on: [analyze]

output:
  format: markdown
  summary: "Analysis of {{dataset}} completed"
"""
    
    # Quick execute from YAML
    print("Executing YAML template...")
    result = engine.quick_execute(
        yaml_template,
        {"dataset": "sales_data", "analysis_type": "detailed"}
    )
    
    print(f"Success: {result.success}")
    print(f"Output: {result.output}")
    print(f"Time: {result.execution_time_ms}ms")
    
    print()


def main():
    """Run all examples."""
    print("\n" + "=" * 60)
    print("Template Engine Integration Examples")
    print("=" * 60 + "\n")
    
    example_basic_usage()
    example_execute_template()
    example_integration()
    example_yaml_template()
    
    print("=" * 60)
    print("All examples completed!")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Create your own templates in weebot/templates/builtin/")
    print("  2. Use TemplateCLI for command-line execution")
    print("  3. Integrate with your agent system")
    print()


if __name__ == "__main__":
    main()
