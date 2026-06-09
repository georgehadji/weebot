---
name: api-client-builder
description: "Use when building an API client or SDK from documentation or an OpenAPI spec. Trigger: API client, SDK, OpenAPI, Swagger, generate client, API wrapper."
license: MIT
---
# API Client Builder

## When to use
Generate a typed API client from an OpenAPI/Swagger spec or API documentation.

## Workflow
1. **Parse spec** — read OpenAPI JSON/YAML or scrape API docs page.
2. **Extract** — endpoints, methods, parameters, request/response schemas.
3. **Generate client** — Python/JS/TypeScript class with:
   - Typed methods for each endpoint
   - Request/response models
   - Error handling and retries
   - Authentication support
4. **Add usage examples** — docstring with example per method.
5. **Output** — single file client module.

## Output
A ready-to-use API client module.