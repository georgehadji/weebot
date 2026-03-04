# Phase 5: Advanced Template Features

**Status:** ✅ Complete  
**Date:** 2026-03-03  
**Version:** 2.2.0 (preview)

---

## 🎉 What's New

Phase 5 adds advanced features to the Template Engine:

1. **Jinja2 Templating** - Conditionals, loops, filters
2. **Template Versioning** - Semantic versioning, migrations
3. **Template Marketplace** - Share and discover templates
4. **Custom Hooks** - Pre/post execution hooks

---

## ✨ Features

### 1. Jinja2 Templating

Advanced template rendering with Jinja2.

#### Conditionals
```yaml
workflow:
  security_scan:
    agent_role: "security"
    condition: "{% if include_security %}true{% endif %}"
    task: "Security scan"
```

#### Loops
```yaml
workflow:
  "{% for item in items %}process_{{item}}{% endfor %}":
    task: "Process {{item}}"
```

#### Filters
```yaml
parameters:
  name:
    default: "{{user_name | upper}}"
  tags:
    default: "{{tag_list | join(', ')}}"
```

#### Functions
```yaml
task: "Generated at {{now()}} - ID: {{uuid()}}"
```

**Usage:**
```python
from weebot.templates.jinja_renderer import JinjaTemplateRenderer

renderer = JinjaTemplateRenderer()
result = renderer.render("Hello {{name | upper}}!", {"name": "world"})
# → "Hello WORLD!"
```

---

### 2. Template Versioning

Semantic versioning for templates.

```python
from weebot.templates.versioning import TemplateVersionManager

manager = TemplateVersionManager()

# Register version
version = manager.register_version(
    template_name="Research Workflow",
    version="2.0.0",
    author="Weebot Team",
    changelog="Added new analysis tasks",
    template=workflow_template,
)

# Check deprecation
is_dep, message, replacement = manager.check_deprecation(
    "Research Workflow", "1.0.0"
)

# Migrate parameters
new_params = manager.migrate_parameters(
    "Research Workflow",
    from_version="1.0.0",
    to_version="2.0.0",
    parameters={"old_param": "value"},
)
```

---

### 3. Template Marketplace

Share and discover templates.

```python
from weebot.templates.marketplace import TemplateMarketplace

marketplace = TemplateMarketplace()

# Search templates
templates = marketplace.search(
    query="research",
    tags=["analysis"],
    sort_by="downloads",
)

# Download template
path = marketplace.download("research-analysis-v2")

# Publish template
listing = marketplace.publish(
    template_path="my_template.yaml",
    author="Your Name",
    tags=["research", "ai"],
    marketplace_token="your_token",
)

# Local repository (offline)
from weebot.templates.marketplace import LocalTemplateRepository

repo = LocalTemplateRepository()
repo.add_template("my_template.yaml")
```

---

### 4. Custom Hooks

Pre/post execution hooks.

```python
from weebot.templates.hooks import HookedTemplateEngine, hook, BuiltinHooks

# Create hooked engine
engine = HookedTemplateEngine()

# Register built-in hooks
BuiltinHooks.register_all(engine)

# Register custom hook
@hook("post_execute", priority=5)
def notify_completion(template_name, result, **kwargs):
    if result.success:
        print(f"✅ {template_name} completed!")
    return {}

engine.hooks.register(
    stage="post_execute",
    function=notify_completion,
    priority=5,
    name="notify_completion",
)

# Conditional hook
from weebot.templates.hooks import HookConditions

engine.hooks.register(
    stage="post_execute",
    function=lambda **ctx: print("Slow execution!"),
    condition=HookConditions.execution_time_exceeded(1000),
    name="slow_alert",
)
```

---

## 📁 New Files

```
weebot/templates/
├── jinja_renderer.py        # Jinja2 templating
├── versioning.py            # Version management
├── marketplace.py           # Template marketplace
├── hooks.py                 # Custom hooks
└── ...

tests/unit/test_templates/
├── test_jinja_renderer.py   # Jinja2 tests
├── test_versioning.py       # Versioning tests
├── test_marketplace.py      # Marketplace tests
└── test_hooks.py            # Hooks tests
```

---

## 🧪 Testing

```bash
# Test Jinja2 rendering
pytest tests/unit/test_templates/test_jinja_renderer.py -v

# Test versioning
pytest tests/unit/test_templates/test_versioning.py -v

# Test marketplace
pytest tests/unit/test_templates/test_marketplace.py -v

# Test hooks
pytest tests/unit/test_templates/test_hooks.py -v
```

---

## 📊 Feature Comparison

| Feature | v2.1.0 | v2.2.0 (Phase 5) |
|---------|--------|------------------|
| Basic templates | ✅ | ✅ |
| Agent integration | ✅ | ✅ |
| **Jinja2 templating** | ❌ | ✅ |
| **Versioning** | ❌ | ✅ |
| **Marketplace** | ❌ | ✅ |
| **Hooks** | ❌ | ✅ |

---

## 🚀 Next Steps

Phase 6 options:
- **Production Hardening** - Rate limiting, auth, database
- **Web Dashboard** - UI for template management
- **Advanced Marketplace** - Ratings, reviews, bundles

---

## 📝 Changelog

### v2.2.0 (Preview)
- Add Jinja2 template rendering
- Add template versioning system
- Add template marketplace
- Add execution hooks
- Full test coverage

---

**Phase 5 Complete!** 🎉
