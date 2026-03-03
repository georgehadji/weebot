# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.1.0] - 2026-03-03

### 🎉 Major Release: Template Engine

Phase 3 introduces the **YAML-based Workflow Template Engine** - enabling non-developers to create multi-agent workflows without writing Python code.

### ✨ New Features

#### Template Engine Core
- **YAML Template Parser** - Parse workflow definitions from YAML files
- **Parameter System** - 7 types with validation and coercion (string, int, float, bool, enum, list, dict)
- **Template Registry** - Load, search, and manage templates
- **Execution Engine** - Execute templates with task handlers and parameter resolution
- **Template Resolution** - `{{parameter}}` placeholder substitution
- **Dry Run Mode** - Validate templates without executing

#### Built-in Templates (8 total)
1. **Research Analysis Workflow** - Comprehensive research with analysis
2. **Competitive Analysis Workflow** - SWOT analysis and competitor profiling
3. **Data Processing Workflow** - ETL pipeline with analysis
4. **Code Review Workflow** - Multi-aspect code review (NEW)
5. **Documentation Generation** - Auto-generate docs from code (NEW)
6. **Bug Analysis Workflow** - Systematic bug investigation (NEW)
7. **Meeting Summary Workflow** - Extract insights from meetings (NEW)
8. **Learning Path Creation** - Personalized learning plans (NEW)

#### Agent System Integration
- **TemplateAgentManager** - Manage agent lifecycle and caching
- **Role-based Agents** - Researcher, Analyst, Writer, Developer, Tester, etc.
- **Agent Caching** - Reuse agents by role for efficiency
- **Simulation Mode** - Test without real agents (dev mode)
- **Full Integration** - Works with Weebot Agent System

#### CLI & Integration
- **TemplateCLI** - Command-line interface for template operations
- **WorkflowOrchestrator Integration** - Parallel task execution
- **TemplateOrchestratorIntegration** - Full system integration

### 📊 Statistics
- **6** new Python modules
- **8** built-in templates
- **100+** unit tests (all passing)
- **~4,000** lines of code
- **10** documentation files

### 🔧 API Usage

```python
from weebot.templates import TemplateEngine

# Create engine
engine = TemplateEngine()
engine.registry.load_builtin_templates()

# Execute template
result = engine.execute(
    "Research Analysis Workflow",
    {
        "topic": "Artificial Intelligence",
        "depth": "comprehensive",
        "output_format": "markdown"
    }
)
```

### 📁 New Files
```
weebot/templates/
├── __init__.py
├── parser.py
├── parameters.py
├── registry.py
├── engine.py
├── integration.py
├── agent_integration.py
└── builtin/ (8 templates)

examples/
├── template_integration_example.py
└── agent_integration_example.py
```

### 🧪 Testing
```bash
pytest tests/unit/test_templates/ -v
# 100+ tests passing
```

---

## [2.0.0] - 2026-02-XX

### Phase 2: Multi-Agent Orchestration

- WorkflowOrchestrator for parallel task execution
- CircuitBreaker for fault tolerance
- DependencyGraph for task dependencies
- ToolResult enhancements with metadata
- BashTool security hardening (4-layer defense)

---

## [1.0.0] - 2026-01-XX

### Initial Release

- Core agent framework
- Basic tool system
- Agent context management
- Safety and security features

---

## Version History

| Version | Date | Phase | Highlights |
|---------|------|-------|------------|
| 2.1.0 | 2026-03-03 | Phase 3 | Template Engine, 8 templates, 100+ tests |
| 2.0.0 | 2026-02-XX | Phase 2 | Multi-agent orchestration, circuit breaker |
| 1.0.0 | 2026-01-XX | Phase 1 | Core agent framework |

---

## Future Roadmap

### v2.2.0 (Planned)
- Web dashboard for template management
- Template versioning
- Template marketplace

### v2.3.0 (Planned)
- Advanced conditional logic in templates
- Loop constructs
- Template hooks

---

**Full documentation:** See `PHASE3_FINAL_SUMMARY.md`
