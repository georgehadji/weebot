# 📝 Phase 3: Workflow Templates & Examples

**Status:** 🟡 Planning / Ready to Start  
**Depends on:** Phase 2 Complete ✅  
**Goal:** Reusable workflow patterns for common AI tasks  
**Estimated Effort:** 3-5 days

---

## 🎯 Executive Summary

Phase 3 delivers a **Template Engine** that allows users to define reusable workflows using YAML/JSON. This enables non-developers to create complex multi-agent workflows without writing Python code.

### Key Deliverables

| Component | Description | Priority |
|-----------|-------------|----------|
| **Template Engine** | YAML/JSON parser & validator | P0 |
| **Template Registry** | Built-in + custom templates | P0 |
| **Parameter System** | Variable substitution & validation | P0 |
| **4 Example Templates** | Research, Analysis, Data Processing, Report | P1 |
| **CLI Integration** | `weebot template run <template>` | P1 |
| **Template Editor** | Web UI for template creation (optional) | P2 |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  TEMPLATE SYSTEM                             │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │   Template   │───▶│   Parser &   │───▶│  Workflow    │   │
│  │   YAML/JSON  │    │   Validator  │    │  Orchestrator│   │
│  └──────────────┘    └──────────────┘    └──────────────┘   │
│         │                                              │      │
│         ▼                                              ▼      │
│  ┌──────────────┐                              ┌──────────┐   │
│  │   Parameter  │                              │  Task    │   │
│  │Substitution  │                              │Execution │   │
│  └──────────────┘                              └──────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 📋 Template Specification

### Template Format (YAML)

```yaml
# workflow_template.yaml
name: "Research Analysis Pipeline"
version: "1.0.0"
description: "Automated research and analysis workflow"
author: "Weebot Team"

# Input parameters
parameters:
  topic:
    type: string
    description: "Research topic"
    required: true
    
  depth:
    type: enum
    values: ["brief", "standard", "deep"]
    default: "standard"
    
  output_format:
    type: enum
    values: ["markdown", "json", "pdf"]
    default: "markdown"

# Workflow definition
workflow:
  # Task 1: Research
  research_task:
    agent_role: "researcher"
    description: "Gather information about {{ topic }}"
    tools: ["web_search", "advanced_browser"]
    prompt: |
      Research the topic: "{{ topic }}"
      Depth level: {{ depth }}
      
      Gather comprehensive information from reliable sources.
      Save findings to research_notes.txt
    
  # Task 2: Analysis (depends on research)
  analysis_task:
    agent_role: "analyst"
    description: "Analyze research findings"
    depends_on: ["research_task"]
    tools: ["python_execute", "file_editor"]
    prompt: |
      Analyze the research notes from {{ research_task.output }}
      
      Provide insights and identify key patterns.
      Create analysis report in {{ output_format }} format.
    
  # Task 3: Report (depends on analysis)
  report_task:
    agent_role: "documentation"
    description: "Generate final report"
    depends_on: ["analysis_task"]
    tools: ["file_editor"]
    prompt: |
      Compile final report for {{ topic }}
      
      Include:
      - Executive summary
      - Key findings
      - Recommendations
      
      Save as: report_{{ topic | slugify }}.md

# Output configuration
output:
  main_report:
    source: "report_task.output"
    format: "{{ output_format }}"
```

---

## 📚 Built-in Templates

### Template 1: Research Analysis Pipeline

**Use case:** Deep research on any topic with automated analysis

```yaml
name: "Research Analysis"
triggers: ["research", "analysis", "investigation"]
tasks:
  - research: Web search & data gathering
  - analyze: Pattern identification
  - report: Summary generation
```

### Template 2: Competitive Analysis

**Use case:** Analyze competitors and market position

```yaml
name: "Competitive Analysis"
triggers: ["competitor", "market", "benchmark"]
tasks:
  - gather: Collect competitor data
  - compare: Feature comparison matrix
  - strategize: Recommendations
```

### Template 3: Data Processing Pipeline

**Use case:** Process large datasets in parallel

```yaml
name: "Data Processing"
triggers: ["etl", "process", "transform"]
tasks:
  - extract: Data extraction (parallel)
  - transform: Data cleaning (parallel)
  - load: Save to database
```

### Template 4: Report Generation

**Use case:** Automated report generation with multiple formats

```yaml
name: "Report Generation"
triggers: ["report", "document", "summary"]
tasks:
  - collect: Gather data sources
  - draft: Create draft content
  - review: Quality check
  - finalize: Format and deliver
```

---

## 🛠️ Implementation Plan

### Week 1: Core Engine

#### Day 1-2: Template Parser
```python
# weebot/templates/parser.py
class TemplateParser:
    def parse(self, yaml_content: str) -> WorkflowTemplate:
        """Parse YAML template into structured object."""
        
    def validate(self, template: WorkflowTemplate) -> ValidationResult:
        """Validate template structure and parameters."""
```

**Tasks:**
- [ ] YAML/JSON parser
- [ ] Schema validation
- [ ] Error handling
- [ ] 10+ unit tests

#### Day 3-4: Parameter System
```python
# weebot/templates/parameters.py
class ParameterResolver:
    def resolve(self, template: WorkflowTemplate, 
                inputs: Dict[str, Any]) -> ResolvedTemplate:
        """Substitute parameters with actual values."""
        
    def validate_inputs(self, schema: ParameterSchema,
                       inputs: Dict[str, Any]) -> bool:
        """Validate input parameters against schema."""
```

**Tasks:**
- [ ] Jinja2-style templating
- [ ] Type validation
- [ ] Default values
- [ ] 8+ unit tests

#### Day 5: Template Registry
```python
# weebot/templates/registry.py
class TemplateRegistry:
    def __init__(self, template_dir: str = "templates/"):
        self._templates: Dict[str, WorkflowTemplate] = {}
        
    def load_builtin(self) -> None:
        """Load built-in templates."""
        
    def load_custom(self, path: str) -> None:
        """Load user-defined templates."""
        
    def get(self, name: str) -> WorkflowTemplate:
        """Retrieve template by name."""
```

**Tasks:**
- [ ] Built-in templates
- [ ] Custom template loading
- [ ] Template discovery
- [ ] 5+ unit tests

### Week 2: Integration & Examples

#### Day 1-2: Workflow Integration
```python
# weebot/templates/engine.py
class TemplateEngine:
    def __init__(self, orchestrator: WorkflowOrchestrator):
        self._orchestrator = orchestrator
        self._registry = TemplateRegistry()
        
    async def execute(self, template_name: str,
                     parameters: Dict[str, Any]) -> WorkflowResult:
        """Execute template with given parameters."""
        template = self._registry.get(template_name)
        resolved = self._resolve_parameters(template, parameters)
        workflow = self._convert_to_workflow(resolved)
        return await self._orchestrator.execute(workflow)
```

**Tasks:**
- [ ] Integration with WorkflowOrchestrator
- [ ] Result handling
- [ ] Error propagation
- [ ] 10+ integration tests

#### Day 3-4: Example Templates
- [ ] Research Analysis Pipeline
- [ ] Competitive Analysis
- [ ] Data Processing Pipeline
- [ ] Report Generation

#### Day 5: CLI Integration
```bash
# List available templates
weebot template list

# Run template with parameters
weebot template run research_analysis \
  --param topic="AI Safety" \
  --param depth=deep \
  --param output_format=markdown

# Validate template
weebot template validate my_template.yaml

# Create new template from example
weebot template init --name my_workflow --from research_analysis
```

---

## 📊 Success Criteria

| Criteria | Target | Measurement |
|----------|--------|-------------|
| **Template Parser** | 100% valid YAML parsing | Unit tests |
| **Parameter System** | Zero injection vulnerabilities | Security tests |
| **Built-in Templates** | 4 complete templates | Example runs |
| **Documentation** | Complete API docs | Review |
| **Test Coverage** | 80%+ | Coverage report |

---

## 🚀 Usage Examples

### Example 1: Research Task

```bash
# Run research template
weebot template run research_analysis \
  --param topic="Climate Change Solutions" \
  --param depth=deep

# Output: report_climate_change_solutions.md
```

### Example 2: Custom Template

```yaml
# my_workflow.yaml
name: "Code Review Pipeline"
parameters:
  repo_url:
    type: string
    required: true
  
workflow:
  clone:
    agent_role: "automation"
    command: "git clone {{ repo_url }}"
  
  analyze:
    agent_role: "analyst"
    depends_on: ["clone"]
    prompt: "Review code quality and security"
  
  report:
    agent_role: "documentation"
    depends_on: ["analyze"]
    prompt: "Generate review report"
```

```bash
# Run custom template
weebot template run my_workflow.yaml \
  --param repo_url="https://github.com/user/repo"
```

### Example 3: Python API

```python
from weebot.templates import TemplateEngine

engine = TemplateEngine()

# Run template
result = await engine.execute(
    template_name="research_analysis",
    parameters={
        "topic": "Quantum Computing",
        "depth": "deep",
        "output_format": "markdown"
    }
)

print(f"Report generated: {result.output_files[0]}")
```

---

## 📁 File Structure

```
weebot/
├── templates/
│   ├── __init__.py
│   ├── parser.py           # YAML/JSON parsing
│   ├── validator.py        # Schema validation
│   ├── parameters.py       # Parameter resolution
│   ├── registry.py         # Template registry
│   ├── engine.py           # Main execution engine
│   └── builtin/            # Built-in templates
│       ├── research_analysis.yaml
│       ├── competitive_analysis.yaml
│       ├── data_processing.yaml
│       └── report_generation.yaml
├── cli/
│   └── template_commands.py  # CLI interface
└── tests/
    └── unit/test_templates/
        ├── test_parser.py
        ├── test_validator.py
        ├── test_parameters.py
        └── test_engine.py
```

---

## 🎯 Definition of Done

- [ ] Template parser handles all YAML/JSON edge cases
- [ ] Parameter system prevents injection attacks
- [ ] 4 built-in templates work end-to-end
- [ ] CLI commands implemented and tested
- [ ] 30+ unit tests passing
- [ ] 5+ integration tests passing
- [ ] Documentation complete
- [ ] Example templates documented

---

## 🔗 Dependencies

- ✅ Phase 2 (WorkflowOrchestrator) — COMPLETE
- ✅ YAML parsing (PyYAML) — available
- ✅ Jinja2 templating — available
- ✅ Pydantic validation — available

---

## 📅 Timeline

| Week | Focus | Deliverables |
|------|-------|--------------|
| Week 1 | Core Engine | Parser, Parameters, Registry |
| Week 2 | Integration | Templates, CLI, Examples |

**Estimated:** 10 days  
**Start Date:** [After Phase 2 release]  
**Target Completion:** [TBD]

---

## 🎊 Success Metrics

After Phase 3 completion:
- Users can create workflows without Python
- 4+ reusable templates available
- Template execution time < 2x manual workflow
- Zero security vulnerabilities
- 100% backward compatibility

---

**Ready to start Phase 3?** Let's build the Template Engine! 🚀
