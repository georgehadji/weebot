# Phase 3 - Day 3: Template Registry

## Overview

Day 3 implements the template registry for loading, managing, and searching workflow templates.

---

## 🎯 Goals

1. **Registration**: Register templates programmatically
2. **File Loading**: Load templates from files and directories
3. **Built-ins**: Load built-in templates automatically
4. **Search**: Search and filter templates
5. **Metadata**: Access template metadata

---

## 📁 Implementation

### `weebot/templates/registry.py` (Already Created)

Key features:
- `register()` / `unregister()` / `clear()`
- `get()` / `get_required()` / `has_template()`
- `load_from_file()` / `load_from_directory()`
- `load_builtin_templates()`
- `search()` / `filter_by_author()` / `filter_by_parameter()`
- `get_metadata()` / `get_statistics()`

---

## 🧪 Tests (Already Created)

### `tests/unit/test_templates/test_registry.py`

Test coverage:
- Basic CRUD operations
- Duplicate detection
- File loading
- Directory loading
- Search functionality
- Metadata access
- Statistics

---

## 🚀 Usage Examples

### Basic Usage

```python
from weebot.templates import TemplateRegistry

# Create registry
registry = TemplateRegistry()

# Load built-in templates
registry.load_builtin_templates()

# List all templates
print(registry.list_templates())
# ['Research Analysis Workflow']

# Get a template
template = registry.get("Research Analysis Workflow")
print(template.description)

# Check if template exists
if "Research Analysis Workflow" in registry:
    print("Template found!")
```

### Loading from Files

```python
# Load single file
template = registry.load_from_file("path/to/template.yaml")

# Load entire directory
count = registry.load_from_directory("path/to/templates/")
print(f"Loaded {count} templates")

# Check for errors
errors = registry.get_load_errors()
for error in errors:
    print(f"Error: {error}")
```

### Searching

```python
# Search by name/description/author
results = registry.search("research")
for template in results:
    print(f"Found: {template.name}")

# Filter by author
alice_templates = registry.filter_by_author("Alice")

# Filter by parameter
templates_with_topic = registry.filter_by_parameter("topic")
```

### Metadata & Statistics

```python
# Get template metadata
metadata = registry.get_metadata("Research Analysis Workflow")
print(f"Parameters: {metadata['parameter_count']}")
for param in metadata['parameters']:
    print(f"  - {param['name']} ({param['type']})")

# Get registry statistics
stats = registry.get_statistics()
print(f"Total templates: {stats['total_templates']}")
print(f"Total parameters: {stats['total_parameters']}")
print(f"Authors: {', '.join(stats['authors'])}")
```

---

## ✅ Success Criteria

- [ ] Register/unregister templates
- [ ] Load from files and directories
- [ ] Load built-in templates
- [ ] Search and filter functionality
- [ ] Metadata access
- [ ] Error handling for invalid templates
- [ ] 20+ tests passing

---

## 🧪 Run Tests

```bash
# Run registry tests only
python run_template_tests.py registry

# Run all template tests
python run_template_tests.py
```

---

## 🚀 Next Steps

After Day 3:
1. Verify all tests pass
2. Continue to Day 4-5: Template Engine (execution)
