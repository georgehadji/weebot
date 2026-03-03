# Phase 3 - Day 4-5: Template Execution Engine

## Overview

Day 4-5 implements the Template Execution Engine that ties everything together - parsing, parameter resolution, and workflow execution.

---

## 🎯 Goals

1. **Template Execution**: Execute templates with resolved parameters
2. **Task Handlers**: Register handlers for different task types
3. **Template Resolution**: Resolve `{{parameter}}` placeholders
4. **Dry Run**: Validate without executing
5. **Error Handling**: Graceful error handling

---

## 📁 Implementation

### `weebot/templates/engine.py` (Already Created)

Key features:
- `execute()` - Execute by template name
- `execute_template()` - Execute template object directly
- `quick_execute()` - Execute from YAML string
- `validate()` - Validate without executing
- `register_task_handler()` - Register task executors
- `dry_run` mode for validation

---

## 🧪 Tests (Already Created)

### `tests/unit/test_templates/test_engine.py`

Test coverage:
- Basic execution
- Mock task handlers
- Dry run mode
- Template validation
- Execution context
- Integration tests
- Error handling

---

## 🚀 Usage Examples

### Basic Execution

```python
from weebot.templates import TemplateEngine

# Create engine
engine = TemplateEngine()

# Load built-in templates
engine.registry.load_builtin_templates()

# Execute a template
result = engine.execute(
    "Research Analysis Workflow",
    {
        "topic": "Artificial Intelligence",
        "depth": "comprehensive",
        "output_format": "markdown"
    }
)

if result.success:
    print(f"Completed in {result.execution_time_ms}ms")
    print(f"Output: {result.output}")
else:
    print(f"Error: {result.error}")
```

### Registering Task Handlers

```python
# Define a task handler
def research_handler(task_def, context):
    """Handle research tasks."""
    topic = task_def["task"]  # Already resolved: "Research AI"
    
    # Perform research...
    findings = perform_research(topic)
    
    return {"findings": findings}

# Register it
engine.register_task_handler("research_task", research_handler)

# Now templates with type: research_task will use this handler
```

### Dry Run (Validation)

```python
# Validate without executing
errors = engine.validate(
    "Research Analysis Workflow",
    {"topic": "AI"}
)

if errors:
    print("Validation errors:")
    for error in errors:
        print(f"  - {error}")
else:
    print("Template is valid!")

# Or use dry_run parameter
result = engine.execute(
    "Research Analysis Workflow",
    {"topic": "AI"},
    dry_run=True
)
```

### Quick Execute from YAML

```python
yaml_content = """
name: Quick Analysis
parameters:
  query:
    type: string
    required: true
workflow:
  analyze:
    type: agent_task
    task: "Analyze {{query}}"
output:
  result: "Analysis of {{query}}"
"""

result = engine.quick_execute(yaml_content, {"query": "sales data"})
```

### Execution Context

```python
# Access execution context in handlers
def my_handler(task_def, context):
    # Access resolved parameters
    topic = context.parameters["topic"]
    
    # Access resolved task definition
    task = task_def["task"]  # "Research {{topic}}" -> "Research AI"
    
    # Store variables for later tasks
    context.variables["research_result"] = findings
    
    return findings
```

---

## 📊 Template Resolution

The engine resolves `{{parameter}}` syntax:

```yaml
parameters:
  topic:
    type: string
  
workflow:
  research:
    task: "Research {{topic}}"  # Becomes: "Research Artificial Intelligence"
    
output:
  summary: "Summary of {{topic}}"  # Becomes: "Summary of Artificial Intelligence"
```

---

## ✅ Success Criteria

- [ ] Execute templates by name
- [ ] Execute template objects directly
- [ ] Execute from YAML strings
- [ ] Register task handlers
- [ ] Resolve template placeholders
- [ ] Dry run validation
- [ ] Error handling and reporting
- [ ] 15+ tests passing

---

## 🧪 Run Tests

```bash
# Run engine tests only
python run_template_tests.py engine

# Run all template tests
python run_template_tests.py

# Run verification
python verify_phase3.py
```

---

## 🎉 Phase 3 Complete!

You now have a full template engine with:
- ✅ YAML template parsing
- ✅ Parameter validation & coercion
- ✅ Template registry with search
- ✅ Execution engine with handlers
- ✅ Built-in example templates

**Next**: Add more built-in templates or integrate with your agent system!
