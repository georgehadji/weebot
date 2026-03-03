# 🚀 Phase 3 Quick Start Guide

**Status:** Ready to Start  
**Goal:** Template Engine for reusable workflows  
**Estimated Time:** 10 days  

---

## 🎯 What We're Building

A **Template Engine** that lets users define multi-agent workflows using YAML instead of Python.

### Before (Python Code)
```python
orchestrator = WorkflowOrchestrator()
result = await orchestrator.execute({
    "research": {"deps": [], "agent_role": "researcher"},
    "analyze": {"deps": ["research"], "agent_role": "analyst"},
})
```

### After (YAML Template)
```yaml
# research_workflow.yaml
name: "Research Task"
workflow:
  research:
    agent_role: "researcher"
  analyze:
    agent_role: "analyst"
    depends_on: ["research"]
```

```bash
weebot template run research_workflow --param topic="AI Safety"
```

---

## 📋 Week 1: Core Engine (Days 1-5)

### Day 1: Template Parser

**File:** `weebot/templates/parser.py`

```python
"""Template parser for YAML/JSON workflow definitions."""
from __future__ import annotations

import yaml
from pathlib import Path
from typing import Any, Dict, List
from dataclasses import dataclass


@dataclass
class WorkflowTemplate:
    """Parsed workflow template."""
    name: str
    version: str
    description: str
    parameters: Dict[str, Any]
    workflow: Dict[str, Any]
    output: Dict[str, Any]


class TemplateParser:
    """Parse YAML/JSON templates into WorkflowTemplate objects."""
    
    def parse(self, content: str) -> WorkflowTemplate:
        """Parse YAML content into template."""
        data = yaml.safe_load(content)
        return self._validate_and_create(data)
    
    def parse_file(self, path: Path) -> WorkflowTemplate:
        """Parse template from file."""
        content = path.read_text()
        return self.parse(content)
    
    def _validate_and_create(self, data: Dict) -> WorkflowTemplate:
        """Validate structure and create template."""
        # TODO: Implement validation
        pass
```

**Test:** `tests/unit/test_templates/test_parser.py`

```python
import pytest
from weebot.templates.parser import TemplateParser


def test_parse_simple_template():
    parser = TemplateParser()
    yaml_content = """
name: "Test Workflow"
version: "1.0.0"
description: "A test workflow"
parameters: {}
workflow:
  task1:
    agent_role: "test"
output: {}
"""
    template = parser.parse(yaml_content)
    assert template.name == "Test Workflow"
    assert template.version == "1.0.0"
```

---

### Day 2: Parameter System

**File:** `weebot/templates/parameters.py`

```python
"""Parameter resolution and validation."""
from __future__ import annotations

from typing import Any, Dict
from jinja2 import Template as JinjaTemplate


class ParameterResolver:
    """Resolve template parameters with actual values."""
    
    def resolve(self, content: str, parameters: Dict[str, Any]) -> str:
        """Substitute parameters in content."""
        template = JinjaTemplate(content)
        return template.render(**parameters)
    
    def validate(self, schema: Dict[str, Any], 
                 inputs: Dict[str, Any]) -> bool:
        """Validate inputs against parameter schema."""
        # TODO: Implement validation
        pass
```

---

### Day 3: Template Registry

**File:** `weebot/templates/registry.py`

```python
"""Template registry for built-in and custom templates."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from weebot.templates.parser import TemplateParser, WorkflowTemplate


class TemplateRegistry:
    """Registry of available templates."""
    
    def __init__(self, template_dir: str = "templates/"):
        self._parser = TemplateParser()
        self._templates: Dict[str, WorkflowTemplate] = {}
        self._template_dir = Path(template_dir)
    
    def load_builtin(self) -> None:
        """Load built-in templates."""
        builtin_dir = Path(__file__).parent / "builtin"
        for template_file in builtin_dir.glob("*.yaml"):
            template = self._parser.parse_file(template_file)
            self._templates[template.name] = template
    
    def get(self, name: str) -> Optional[WorkflowTemplate]:
        """Get template by name."""
        return self._templates.get(name)
    
    def list_all(self) -> List[str]:
        """List all available template names."""
        return list(self._templates.keys())
```

---

### Day 4-5: Template Engine

**File:** `weebot/templates/engine.py`

```python
"""Main template execution engine."""
from __future__ import annotations

from typing import Any, Dict

from weebot.core.workflow_orchestrator import WorkflowOrchestrator, WorkflowResult
from weebot.templates.parser import WorkflowTemplate
from weebot.templates.parameters import ParameterResolver
from weebot.templates.registry import TemplateRegistry


class TemplateEngine:
    """Execute templates using the workflow orchestrator."""
    
    def __init__(self, orchestrator: WorkflowOrchestrator):
        self._orchestrator = orchestrator
        self._registry = TemplateRegistry()
        self._resolver = ParameterResolver()
        
        # Load built-in templates
        self._registry.load_builtin()
    
    async def execute(self, template_name: str,
                     parameters: Dict[str, Any]) -> WorkflowResult:
        """Execute a template with given parameters."""
        # 1. Get template
        template = self._registry.get(template_name)
        if not template:
            raise ValueError(f"Template not found: {template_name}")
        
        # 2. Validate parameters
        # TODO: Validate against schema
        
        # 3. Convert to workflow
        workflow = self._convert_to_workflow(template, parameters)
        
        # 4. Execute
        return await self._orchestrator.execute(workflow)
    
    def _convert_to_workflow(self, template: WorkflowTemplate,
                            parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Convert template to workflow orchestrator format."""
        # TODO: Implement conversion
        pass
```

---

## 📋 Week 2: Templates & CLI (Days 6-10)

### Day 6: Built-in Template #1 — Research Analysis

**File:** `weebot/templates/builtin/research_analysis.yaml`

```yaml
name: "Research Analysis Pipeline"
version: "1.0.0"
description: "Deep research and analysis on any topic"

parameters:
  topic:
    type: string
    description: "Research topic"
    required: true
  
  depth:
    type: enum
    values: ["brief", "standard", "deep"]
    default: "standard"

workflow:
  research:
    agent_role: "researcher"
    description: "Gather information about {{ topic }}"
    tools: ["web_search", "advanced_browser"]
    prompt: |
      Research the topic: "{{ topic }}"
      Depth level: {{ depth }}
      Gather comprehensive information.
  
  analysis:
    agent_role: "analyst"
    description: "Analyze findings"
    depends_on: ["research"]
    tools: ["python_execute"]
    prompt: "Analyze research findings and identify patterns"
  
  report:
    agent_role: "documentation"
    description: "Generate report"
    depends_on: ["analysis"]
    tools: ["file_editor"]
    prompt: "Create comprehensive report on {{ topic }}"

output:
  main_report:
    source: "report.output"
```

---

### Day 7: Built-in Templates #2 & #3

**Templates:**
- `competitive_analysis.yaml`
- `data_processing.yaml`

---

### Day 8: Built-in Template #4 & CLI

**Template:**
- `report_generation.yaml`

**CLI:** `cli/template_commands.py`

```python
import click
from weebot.templates.engine import TemplateEngine

@click.group()
def template():
    """Template management commands."""
    pass

@template.command()
def list():
    """List available templates."""
    engine = TemplateEngine()
    # TODO: List templates

@template.command()
@click.argument('template_name')
@click.option('--param', multiple=True)
def run(template_name: str, param: list):
    """Run a template with parameters."""
    # TODO: Execute template
```

---

### Day 9: Testing & Integration

**Tests to write:**
- [ ] Parser tests (10+ tests)
- [ ] Parameter tests (8+ tests)
- [ ] Registry tests (5+ tests)
- [ ] Engine integration tests (5+ tests)
- [ ] End-to-end template tests (4 tests)

---

### Day 10: Documentation & Polish

**Tasks:**
- [ ] API documentation
- [ ] Template authoring guide
- [ ] Example templates
- [ ] README update
- [ ] Final testing

---

## 🚀 Daily Workflow

### Morning (2-3 hours)
1. Review yesterday's code
2. Write new feature
3. Write tests

### Afternoon (2-3 hours)
4. Debug and fix issues
5. Run test suite
6. Commit with message:
```bash
git add .
git commit -m "feat(phase3): [feature description]

- [specific change]
- [specific change]

Tests: [X] passing"
```

---

## ✅ Daily Checklist

- [ ] Code written
- [ ] Tests passing
- [ ] Documentation updated
- [ ] Committed to git
- [ ] No regressions

---

## 🎯 Success Criteria

By end of Week 2:
- [ ] 4 built-in templates work
- [ ] CLI commands functional
- [ ] 30+ tests passing
- [ ] Documentation complete
- [ ] No security issues

---

## 📚 Resources

- **Phase 3 Plan:** `docs/PHASE3_WORKFLOW_TEMPLATES.md`
- **Template Spec:** See "Template Format (YAML)" section above
- **Examples:** `weebot/templates/builtin/`

---

**Ready to start Day 1?** Let's build the Template Engine! 🚀

**First task:** Create `weebot/templates/parser.py` with basic YAML parsing.
