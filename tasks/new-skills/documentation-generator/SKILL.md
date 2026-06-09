---
name: documentation-generator
description: "Use when the user asks to generate, write, or create documentation from code. Trigger keywords: document, documentation, docs, README, API docs, generate docs."
license: MIT
---

# Documentation Generator

## When to use
The user wants documentation generated from source code — README, API docs, usage guides, or inline comments.

## Workflow

1. **Inventory the codebase** — list all source files, read key entry points.
2. **Extract structure:** functions/methods with signatures, classes, module exports, config files.
3. **Generate documentation sections:** README, API reference, architecture overview.
4. **Write output** — create markdown files in a `docs/` directory.

## Tool guidance
- `bash`: Use grep to find function definitions, exports, and docstrings.
- `file_editor`: Read source files, write documentation files.
- `python_execute`: Can parse ASTs for structured extraction in Python/JS/TS.

## Output
A `docs/` directory containing README.md, API.md, and optionally ARCHITECTURE.md.
