#!/usr/bin/env python3
"""
Example: Agent System Integration

Demonstrates how to use the Template Engine with the actual Weebot agent system.
"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def example_basic_agent_execution():
    """Execute template with real agents."""
    print("=" * 60)
    print("Example 1: Basic Agent Execution")
    print("=" * 60)
    
    try:
        from weebot.templates.agent_integration import create_agent_enabled_engine
        
        # Create engine with agent support
        engine, agent_manager = create_agent_enabled_engine(
            load_builtin=True
        )
        
        print(f"Engine created with {len(engine.registry)} templates")
        print(f"Agent manager: {agent_manager}")
        
        if agent_manager:
            info = agent_manager.get_agent_info()
            print(f"Available roles: {', '.join(info['available_roles'][:5])}...")
        
        # Execute a template
        result = engine.execute(
            "Research Analysis Workflow",
            {
                "topic": "Python asyncio best practices",
                "depth": "brief",
                "output_format": "markdown"
            }
        )
        
        print(f"\nSuccess: {result.success}")
        print(f"Execution time: {result.execution_time_ms}ms")
        
        if result.task_results:
            print(f"\nTask results:")
            for task in result.task_results:
                print(f"  - {task['task_id']}: {task.get('success', False)}")
        
    except ImportError as e:
        print(f"Agent system not available: {e}")
        print("Running in simulation mode...")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    
    print()


def example_custom_agent_roles():
    """Use custom agent roles."""
    print("=" * 60)
    print("Example 2: Custom Agent Roles")
    print("=" * 60)
    
    try:
        from weebot.templates.agent_integration import TemplateAgentManager
        
        # Create agent manager
        manager = TemplateAgentManager()
        
        # Show available roles
        info = manager.get_agent_info()
        print("Available agent roles:")
        for role in info['available_roles']:
            print(f"  - {role}")
        
        # Get agent for specific role
        agent = manager.get_or_create_agent(
            role="researcher",
            task_description="Research Python async patterns"
        )
        print(f"\nCreated agent: {agent}")
        
    except ImportError as e:
        print(f"Agent system not available: {e}")
    except Exception as e:
        print(f"Error: {e}")
    
    print()


def example_code_review_with_agents():
    """Execute code review template with agents."""
    print("=" * 60)
    print("Example 3: Code Review with Agents")
    print("=" * 60)
    
    try:
        from weebot.templates import TemplateEngine
        from weebot.templates.agent_integration import register_agent_handlers
        
        # Create engine
        engine = TemplateEngine()
        engine.registry.load_builtin_templates()
        
        # Register agent handlers
        register_agent_handlers(engine)
        print("Agent handlers registered")
        
        # Check if code review template exists
        if engine.registry.has_template("Code Review Workflow"):
            print("\nExecuting Code Review Workflow...")
            
            result = engine.execute(
                "Code Review Workflow",
                {
                    "code_source": "src/auth module",
                    "language": "python",
                    "review_type": "quick",
                    "focus_areas": ["security", "readability"]
                },
                dry_run=True  # Validate only for demo
            )
            
            print(f"Validation: {result.success}")
            if result.output:
                print(f"Tasks: {result.output.get('tasks', [])}")
        else:
            print("Code Review Workflow template not found")
            print("Available templates:", engine.registry.list_templates())
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    
    print()


def example_async_execution():
    """Execute tasks asynchronously."""
    print("=" * 60)
    print("Example 4: Async Execution")
    print("=" * 60)
    
    try:
        from weebot.templates.agent_integration import (
            TemplateAgentManager,
            TemplateAgentTaskHandler,
        )
        from weebot.templates.engine import ExecutionContext
        from weebot.templates.parser import WorkflowTemplate
        
        async def run_async():
            # Create manager
            manager = TemplateAgentManager()
            
            # Create dummy context
            template = WorkflowTemplate(
                name="Test",
                version="1.0",
                workflow={}
            )
            context = ExecutionContext(
                template=template,
                parameters={}
            )
            
            # Execute task
            result = await manager.execute_task(
                role="researcher",
                task="Research async patterns in Python",
                context=context
            )
            
            return result
        
        # Run async
        result = asyncio.run(run_async())
        print(f"Async result: {result}")
        
    except ImportError as e:
        print(f"Agent system not available: {e}")
    except Exception as e:
        print(f"Error: {e}")
    
    print()


def example_agent_info():
    """Display agent system information."""
    print("=" * 60)
    print("Example 5: Agent System Info")
    print("=" * 60)
    
    try:
        from weebot.templates.agent_integration import (
            TemplateAgentManager,
            HAS_AGENT_SYSTEM,
        )
        
        print(f"Agent system available: {HAS_AGENT_SYSTEM}")
        
        if HAS_AGENT_SYSTEM:
            manager = TemplateAgentManager()
            info = manager.get_agent_info()
            
            print(f"\nCached agents: {info['cached_agents'] or 'None'}")
            print(f"\nAvailable roles ({len(info['available_roles'])}):")
            
            for role in info['available_roles']:
                print(f"  - {role}")
        else:
            print("Running in simulation mode")
        
    except Exception as e:
        print(f"Error: {e}")
    
    print()


def main():
    """Run all examples."""
    print("\n" + "=" * 60)
    print("Agent System Integration Examples")
    print("=" * 60 + "\n")
    
    examples = [
        ("Basic Agent Execution", example_basic_agent_execution),
        ("Custom Agent Roles", example_custom_agent_roles),
        ("Code Review with Agents", example_code_review_with_agents),
        ("Async Execution", example_async_execution),
        ("Agent System Info", example_agent_info),
    ]
    
    for name, func in examples:
        try:
            func()
        except Exception as e:
            print(f"Example '{name}' failed: {e}")
            print()
    
    print("=" * 60)
    print("Examples completed!")
    print("=" * 60)
    print("\nNote: If agent system is not available, examples run in simulation mode.")
    print("To use real agents, ensure weebot.agent_core_v2 is properly configured.")
    print()


if __name__ == "__main__":
    main()
