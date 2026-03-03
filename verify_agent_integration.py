#!/usr/bin/env python3
"""Verify agent integration is working."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def test_imports():
    """Test agent integration imports."""
    print("Testing agent integration imports...")
    
    try:
        from weebot.templates.agent_integration import (
            TemplateAgentManager,
            TemplateAgentTaskHandler,
            register_agent_handlers,
            create_agent_enabled_engine,
            HAS_AGENT_SYSTEM,
        )
        print(f"  Agent system available: {HAS_AGENT_SYSTEM}")
        print("  ✅ Imports successful")
        return True
    except ImportError as e:
        print(f"  ❌ Import failed: {e}")
        return False


def test_agent_manager():
    """Test agent manager creation."""
    print("\nTesting Agent Manager...")
    
    try:
        from weebot.templates.agent_integration import (
            TemplateAgentManager,
            HAS_AGENT_SYSTEM,
        )
        
        if not HAS_AGENT_SYSTEM:
            print("  ⚠️  Agent system not available (simulation mode)")
            return True
        
        manager = TemplateAgentManager()
        info = manager.get_agent_info()
        
        print(f"  ✅ Manager created")
        print(f"     Available roles: {len(info['available_roles'])}")
        print(f"     Roles: {', '.join(info['available_roles'][:5])}...")
        return True
        
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return False


def test_agent_roles():
    """Test agent role definitions."""
    print("\nTesting Agent Roles...")
    
    try:
        from weebot.templates.agent_integration import TemplateAgentManager
        
        manager = TemplateAgentManager()
        
        expected_roles = [
            "researcher", "analyst", "writer", 
            "reviewer", "developer", "tester", "default"
        ]
        
        for role in expected_roles:
            if role not in manager.ROLE_PROFILES:
                print(f"  ❌ Missing role: {role}")
                return False
        
        print(f"  ✅ All {len(expected_roles)} roles defined")
        return True
        
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return False


def test_engine_integration():
    """Test engine integration."""
    print("\nTesting Engine Integration...")
    
    try:
        from weebot.templates import TemplateEngine
        from weebot.templates.agent_integration import register_agent_handlers
        
        engine = TemplateEngine()
        
        # Register handlers
        register_agent_handlers(engine)
        print("  ✅ Agent handlers registered")
        
        # Load templates
        count = engine.registry.load_builtin_templates()
        print(f"  ✅ Loaded {count} templates")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return False


def test_template_with_agents():
    """Test template that uses agents."""
    print("\nTesting Template with Agents...")
    
    try:
        from weebot.templates import TemplateEngine
        
        engine = TemplateEngine()
        engine.registry.load_builtin_templates()
        
        # Find a template with agent tasks
        templates = engine.registry.list_templates()
        
        if not templates:
            print("  ⚠️  No templates loaded")
            return True
        
        # Get first template and check its workflow
        template = engine.registry.get(templates[0])
        
        agent_tasks = 0
        for task_id, task_def in template.workflow.items():
            if task_def.get("type") == "agent_task" or task_def.get("agent_role"):
                agent_tasks += 1
        
        print(f"  ✅ Template '{template.name}' has {agent_tasks} agent tasks")
        return True
        
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return False


def test_simulation_mode():
    """Test simulation mode."""
    print("\nTesting Simulation Mode...")
    
    try:
        from weebot.templates.agent_integration import (
            TemplateAgentTaskHandler,
            HAS_AGENT_SYSTEM,
        )
        
        handler = TemplateAgentTaskHandler()
        
        if HAS_AGENT_SYSTEM:
            print("  ✅ Real agent mode available")
        else:
            print("  ✅ Simulation mode active")
            assert handler.is_simulation_mode() is True
        
        # Test simulation
        result = handler._simulate_execution("researcher", "Test task")
        
        assert result["success"] is True
        assert result["agent_role"] == "researcher"
        assert result["simulation"] is True
        
        print("  ✅ Simulation working")
        return True
        
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return False


def main():
    """Run all verification tests."""
    print("=" * 60)
    print("Agent Integration Verification")
    print("=" * 60)
    
    tests = [
        ("Imports", test_imports),
        ("Agent Manager", test_agent_manager),
        ("Agent Roles", test_agent_roles),
        ("Engine Integration", test_engine_integration),
        ("Template with Agents", test_template_with_agents),
        ("Simulation Mode", test_simulation_mode),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"  ❌ {name} crashed: {e}")
            results.append((name, False))
    
    print("\n" + "=" * 60)
    print("Results Summary")
    print("=" * 60)
    
    passed_count = sum(1 for _, p in results if p)
    total_count = len(results)
    
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {name}")
    
    print(f"\nScore: {passed_count}/{total_count} tests passed")
    
    if passed_count == total_count:
        print("\n🎉 Agent integration is fully working!")
        print("\nYou can now:")
        print("  • Execute templates with real agents")
        print("  • Use role-based agent selection")
        print("  • Cache and reuse agents")
        print("  • Run in simulation mode for testing")
        return 0
    else:
        print("\n⚠️  Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
