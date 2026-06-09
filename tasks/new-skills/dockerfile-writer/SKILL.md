---
name: dockerfile-writer
description: "Use when writing or optimizing a Dockerfile. Trigger: Docker, Dockerfile, container, dockerize, containerize."
license: MIT
---
# Dockerfile Writer

## When to use
Generate an optimized, secure Dockerfile for a project.

## Workflow
1. **Analyze project** — detect language, framework, entry point, dependencies.
2. **Write Dockerfile** with best practices:
   - Multi-stage builds (separate build and runtime)
   - Minimal base image (alpine when possible)
   - Layer caching optimization
   - Non-root user
   - Health check
   - Proper signal handling
3. **Generate .dockerignore** to exclude unnecessary files.
4. **Add docker-compose.yml** if multiple services are needed.
5. **Build and test** — verify the image builds and the container runs.

## Output
Dockerfile, .dockerignore, and optional docker-compose.yml.