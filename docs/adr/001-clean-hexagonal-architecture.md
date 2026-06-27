# ADR-001: Clean Hexagonal Architecture

**Status:** Accepted
**Date:** 2025-07-17
**Deciders:** Architecture team

## Context

Weebot is an AI agent framework that must integrate with multiple LLM
providers (OpenAI, Anthropic, DeepSeek, OpenRouter, xAI), persistence
backends (SQLite, PostgreSQL planned), execution environments (local
sandbox, Docker), and user interfaces (CLI, web, Windows desktop). Early
prototypes used a monolithic app structure where these concerns were mixed,
making provider swaps and testability difficult.

## Decision

Adopt **Clean Architecture** (hexagonal variant) with:

- **Domain** (`weebot/domain/`) — entities, value objects, ports (interfaces),
  and domain exceptions. Zero framework dependencies.
- **Application** (`weebot/application/`) — use cases, flows, agents, CQRS
  mediator, and the dependency injection container. Depends only on domain.
- **Infrastructure** (`weebot/infrastructure/`) — adapter implementations
  for every port (LLM, persistence, browser, sandbox, etc.). Implements
  ports defined in domain/application.
- **Interfaces** (`weebot/interfaces/`) — entry points (CLI, FastAPI, Windows
  desktop, MCP server). Composition root that wires the DI container.

4 import-linter contracts enforce this at every CI gate:
1. Domain must not import outer layers
2. Tools must not access databases directly
3. Infrastructure must depend on ports, not application services
4. Interfaces must not depend on infrastructure directly

## Consequences

**Positive:**
- LLM provider swaps require only a new adapter under `infrastructure/llm/`;
  no flow or agent code changes.
- Domain logic is testable without infrastructure (no real DB or API calls).
- Tool isolation prevents agent actions from reaching persistence directly.

**Negative:**
- Adding a simple feature often requires touching 3–4 files (port + adapter +
  DI binding + test).
- The composition root becomes a bottleneck — every new dependency needs
  explicit wiring.
- 52 `ignore_imports` exceptions (as of this ADR) show the implementation
  hasn't fully caught up to the ideal boundary separation.

**Compliance:** Import-linter CI gate. New PRs that add `ignore_imports`
entries require explicit architecture-team review.
