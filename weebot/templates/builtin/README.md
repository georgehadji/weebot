# Workflow Templates Guide

## Overview

The Template Engine allows non-developers to create workflows using YAML
instead of writing Python code.

## Template Structure

```yaml
name: "Template Name"
version: "1.0.0"
description: "What this template does"
author: "Your Name"

parameters:
  param_name:
    type: string | int | float | bool | enum | list | dict
    description: "What this parameter does"
    required: true | false
    default: value  # Optional
    values: ["option1", "option2"]  # For enum type

workflow:
  task_id:
    agent_role: "role_name"
    task: "Task description"
    depends_on: [other_task_id]
    parameters:
      key: "{{ template_parameter }}"

output:
  format: "markdown"
  sections:
    - "section_name"
```

## Usage Example

```python
from weebot.templates import TemplateEngine

engine = TemplateEngine()
engine.registry.load_builtin_templates()

result = engine.execute(
    "Research Analysis Workflow",
    {
        "topic": "Artificial Intelligence",
        "depth": "comprehensive",
        "output_format": "markdown"
    }
)
```
