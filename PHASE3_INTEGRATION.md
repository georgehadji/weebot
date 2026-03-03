# Phase 3 Integration Guide

Integrating the Template Engine with Weebot Core Systems

---

## 🎯 Overview

This guide shows how to integrate the Template Engine with:
- **WorkflowOrchestrator** (Phase 2) - for parallel execution
- **AgentManager** - for agent task execution
- **ToolRegistry** - for tool-based tasks

---

## 📁 Integration Module

**File:** `weebot/templates/integration.py`

### Key Components

1. **TemplateOrchestratorIntegration** - Main integration class
2. **TemplateCLI** - Command-line interface
3. **create_integrated_engine()** - Factory function

---

## 🚀 Quick Start

### Basic Integration

```python
from weebot.templates.integration import create_integrated_engine

# Create fully integrated engine
integration = create_integrated_engine(
    load_builtin=True,      # Load built-in templates
    use_orchestrator=True,  # Use WorkflowOrchestrator
)

# Execute a template
result = integration.execute_workflow_template(
    "Research Analysis Workflow",
    {
        "topic": "Artificial Intelligence",
        "depth": "comprehensive",
    }
)

print(f"Success: {result['success']}")
print(f"Execution time: {result.get('execution_time_ms')}ms")
```

### Manual Integration

```python
from weebot.templates import TemplateEngine
from weebot.templates.integration import TemplateOrchestratorIntegration
from weebot.core.workflow_orchestrator import WorkflowOrchestrator

# Create components
engine = TemplateEngine()
orchestrator = WorkflowOrchestrator()

# Create integration
integration = TemplateOrchestratorIntegration(
    engine=engine,
    orchestrator=orchestrator,
)

# Load templates
engine.registry.load_builtin_templates()

# Execute with orchestrator
result = integration.execute_workflow_template(
    "Research Analysis Workflow",
    parameters={"topic": "AI"},
    use_orchestrator=True,  # Use parallel execution
)
```

---

## 🔧 Task Handlers

The integration registers three default task handlers:

### 1. Agent Task Handler

```yaml
workflow:
  research:
    type: agent_task
    agent_role: researcher
    task: "Research {{topic}}"
```

**Behavior:**
- If AgentManager available: Executes via agent
- Otherwise: Simulates execution

### 2. Tool Task Handler

```yaml
workflow:
  search:
    type: tool_task
    tool: web_search
    parameters:
      query: "{{topic}}"
```

**Behavior:**
- If ToolRegistry available: Executes tool
- Otherwise: Simulates execution

### 3. Parallel Tasks Handler

```yaml
workflow:
  parallel_work:
    type: parallel_tasks
    subtasks:
      - id: task1
        agent_role: researcher
        task: "Research part 1"
      - id: task2
        agent_role: researcher
        task: "Research part 2"
```

**Behavior:**
- If Orchestrator available: Executes in parallel
- Otherwise: Executes sequentially

---

## 🎨 CLI Usage

```python
from weebot.templates.integration import TemplateCLI

# Create CLI
cli = TemplateCLI()

# List templates
templates = cli.list_templates()
print(f"Available: {', '.join(templates)}")

# Show template details
metadata = cli.show_template("Research Analysis Workflow")
print(f"Parameters: {metadata['parameter_count']}")

# Validate
errors = cli.validate("Research Analysis Workflow", {"topic": "AI"})
if errors:
    print("Validation errors:", errors)

# Execute
result = cli.execute(
    "Research Analysis Workflow",
    {"topic": "AI", "depth": "comprehensive"}
)

# Dry run
result = cli.execute(
    "Research Analysis Workflow",
    {"topic": "AI"},
    dry_run=True
)
```

---

## ⚙️ Advanced Configuration

### Custom Task Handler

```python
def custom_handler(task_def, context):
    """Custom task handler."""
    # Access resolved parameters
    params = context.parameters
    
    # Do custom work
    result = do_custom_work(task_def, params)
    
    return {
        "success": True,
        "result": result,
    }

# Register with engine
engine.register_task_handler("custom_task", custom_handler)
```

### With Custom Orchestrator

```python
from weebot.core.workflow_orchestrator import WorkflowOrchestrator
from weebot.core.circuit_breaker import CircuitBreaker

# Create orchestrator with custom config
breaker = CircuitBreaker(
    failure_threshold=5,
    cooldown_seconds=120,
)

orchestrator = WorkflowOrchestrator(
    max_parallel=8,
    circuit_breaker=breaker,
)

integration = TemplateOrchestratorIntegration(
    engine=engine,
    orchestrator=orchestrator,
)
```

---

## 📊 Execution Flow

```
┌─────────────────────────────────────────────────────────────┐
│  User calls execute_workflow_template()                      │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  1. Load template from registry                              │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  2. Resolve parameters with ParameterResolver               │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  3. Build task graph from template workflow                 │
│     - Resolve {{placeholders}} in task definitions          │
│     - Map dependencies                                      │
└──────────────────────┬──────────────────────────────────────┘
                       │
         ┌─────────────┴─────────────┐
         │                           │
         ▼                           ▼
┌─────────────────┐      ┌──────────────────┐
│ use_orchestrator│      │  use_engine      │
│ = True          │      │  = True          │
└────────┬────────┘      └────────┬─────────┘
         │                        │
         ▼                        ▼
┌─────────────────┐      ┌──────────────────┐
│ WorkflowOrchestrator    │ TemplateEngine   │
│ - Parallel execution    │ - Sequential     │
│ - Dependency mgmt       │ - Task handlers  │
└─────────────────┘      └──────────────────┘
```

---

## 🧪 Testing Integration

```bash
# Run integration tests
pytest tests/unit/test_templates/test_integration.py -v

# Run all template tests
pytest tests/unit/test_templates/ -v

# Verify integration
python -c "
from weebot.templates.integration import create_integrated_engine
integration = create_integrated_engine()
print('✅ Integration working!')
print(f'Loaded {len(integration.engine.registry)} templates')
"
```

---

## 🔗 Integration Points

### With Existing Weebot Code

```python
# In your existing workflow
from weebot.templates.integration import create_integrated_engine

class WeebotCore:
    def __init__(self):
        # ... existing init ...
        
        # Add template engine integration
        self.template_integration = create_integrated_engine(
            load_builtin=True,
            use_orchestrator=True,
        )
    
    def run_template(self, template_name: str, parameters: dict):
        """Run a workflow template."""
        return self.template_integration.execute_workflow_template(
            template_name, parameters
        )
```

---

## ✅ Integration Checklist

- [ ] TemplateEngine created and configured
- [ ] WorkflowOrchestrator integrated (optional but recommended)
- [ ] AgentManager connected (optional)
- [ ] ToolRegistry connected (optional)
- [ ] Built-in templates loaded
- [ ] Custom task handlers registered (if needed)
- [ ] Integration tests passing
- [ ] CLI working

---

## 🎉 You Did It!

Phase 3 is now fully integrated with your Weebot system!

**What's Next?**
1. Create custom templates for your use cases
2. Add more task handlers for specific operations
3. Build a web UI for template management
4. Share templates with the team

**Happy templating!** 🚀
