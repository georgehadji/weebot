# ADR-002: CQRS with Event Sourcing

**Status:** Accepted
**Date:** 2025-07-17
**Deciders:** Architecture team

## Context

The agent loop produces many time-ordered events: plan created, step
executing, tool result returned, review verdict, step completed, session
summary. Consumers include the state machine (which decisions depends on
event history), the audit trail (for debugging), the trajectory optimizer
(for skill improvement), and the operator dashboard (for observability).

Early versions used direct method calls between agents and a mutable
`Session` object, making it impossible to replay a session, audit failures,
or decouple write-side from read-side consumers.

## Decision

Adopt **CQRS (Command-Query Responsibility Segregation)** with a typed
event stream:

- **Commands** (`application/cqrs/commands/`) — mutation intent sent to
  the mediator (e.g., `CreatePlanCommand`, `ExecuteStepCommand`).
- **Queries** (`application/cqrs/queries.py`) — read requests (e.g.,
  `GetSessionQuery`).
- **Mediator** (`application/cqrs/mediator.py`) — dispatches commands to
  handlers with middleware behaviors (logging, telemetry, save-policy).
- **Event Bus** (`EventBusPort` in `application/ports/`) — pub/sub for
  typed `AgentEvent` subtypes (19 event types in `domain/models/event.py`).
- **CQRS handlers** in `application/cqrs/handlers/` — process commands
  and queries; emit events via the event bus.
- **State repository** (`StateRepositoryPort`) — persists session state
  so it can be resumed. The single source of truth for current session
  snapshot; events are the source of truth for history.

## Consequences

**Positive:**
- Every agent action is traceable through the event stream.
- Session replay for debugging: replay the event stream to reconstruct
  state at any point.
- Decoupled consumers: the dashboard, optimizer, and audit log subscribe
  to events without modifying the agent loop.
- CQRS behaviors (logging, telemetry, save-policy) compose cleanly.

**Negative:**
- Higher initial complexity — adding a new event type requires a command,
  a handler, an event class, and a subscriber.
- Read-model consistency requires eventual consistency; the current
  SQLite single-store means command and query share the same DB (a known
  shortcut).

**Compliance:** Every `Command` subclass must have a registered handler in
`handlers/`. Every new `AgentEvent` subtype must be listed in
`docs/EVENT_CATALOG.md`. Enforced by fitness tests.
