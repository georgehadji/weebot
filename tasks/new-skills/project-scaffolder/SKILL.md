---
name: project-scaffolder
description: "Use when the user asks to create, scaffold, initialize, or set up a new project. Trigger keywords: scaffold, initialize, create project, setup, boilerplate, starter, template."
license: MIT
---

# Project Scaffolder

## When to use
The user wants to create a new project with proper structure, config files, and best practices from scratch.

## Workflow

1. **Determine project type** — ask or infer from context (Python package, Node.js app, React site, Go module, etc.)
2. **Create directory structure:** src, tests, docs, config files at root.
3. **Generate config files** with sensible defaults for the detected language/framework.
4. **Create entry point** — main file with basic structure and a hello-world test.
5. **Initialize git** — `git init`, create initial commit.
6. **Generate README** — project name, description, setup instructions, usage.

## Tool guidance
- `bash`: Create directories, init git, run package managers.
- `file_editor`: Create all source files, configs, and README.

## Output
A fully initialized project directory ready for development.
