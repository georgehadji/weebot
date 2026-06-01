# ADR 002: CQRS with Mediator over Service Layer

**Status:** Accepted  
**Date:** 2026-06-01  
**Deciders:** Architecture Team  

## Context

The application layer needs to orchestrate operations like plan creation,
step execution, and session management. Two common patterns exist:
a traditional Service Layer (services call each other directly) or
CQRS + Mediator (commands/queries flow through a central mediator).

## Decision

Use CQRS with a Mediator pattern (`weebot/application/cqrs/`).

## Rationale

- **Pipeline behaviors** — The mediator supports middleware behaviors
  (LoggingBehavior, ValidationGateBehavior) that wrap every command/query
  without modifying handlers.
- **Separation of reads and writes** — Queries (get session, list sessions)
  are defined separately from Commands (create plan, execute step), making
  it clear which operations have side effects.
- **Testability** — Handlers depend only on ports, making them trivially
  unit-testable without HTTP, CLI, or database setup.
- **Single entry point** — All state mutations go through `mediator.send()`,
  making it easy to audit, trace, and monitor.

## Consequences

- More boilerplate than a Service Layer (command classes, handler classes,
  registration code).
- Not all operations fit the pattern perfectly — some flows (SkillOpt)
  use the mediator for commands but bypass it for queries, requiring
  dual code paths.
- The mediator is registered in `di.py` and shared across the process —
  must be thread-safe (currently safe since all operations are async).
