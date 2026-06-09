---
name: readme-generator
description: "Use when the user asks to generate or write a README file for a project. Trigger keywords: README, readme generator, project readme, write readme."
license: MIT
---

# README Generator

## When to use
The user wants a comprehensive README.md generated from their project's source code.

## Workflow
1. **Scan the project** — list all source files, read package.json/pyproject.toml/go.mod, find entry points.
2. **Extract metadata:** project name, description, language, dependencies, license.
3. **Generate sections:**
   - Title and badges
   - Description
   - Installation
   - Quick start / usage
   - Configuration
   - API overview (if applicable)
   - Contributing guidelines
   - License
4. **Write README.md** at project root.

## Output
A complete README.md ready for GitHub.