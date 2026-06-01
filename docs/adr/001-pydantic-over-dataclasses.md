# ADR 001: Pydantic BaseModel over dataclasses

**Status:** Accepted  
**Date:** 2026-06-01  
**Deciders:** Architecture Team  

## Context

Domain models in weebot need to be serializable (JSON for persistence and API),
validated (field constraints), and evolve over time (new fields, deprecations).
Python offers two natural choices: `dataclasses` (stdlib) and Pydantic `BaseModel`.

## Decision

Use Pydantic `BaseModel` (with `frozen=True`) for all domain entity models.

## Rationale

- **Built-in validation** — Pydantic validates field types at construction time,
  catching data integrity issues early.
- **JSON Schema generation** — `model_dump()` and `model_dump_json()` give us
  free serialization for persistence (SQLite) and API responses.
- **`model_copy(update=…)`** — Immutable updates with partial field changes,
  critical for the `Session = session.add_event(event)` pattern used throughout
  flows and handlers.
- **Union deserialization** — `TypeAdapter(AgentEvent).validate_python()` handles
  polymorphic event deserialization (e.g., `FactDiscovered` vs `NotificationEvent`)
  using the discriminated `type` field — dataclasses cannot do this without
  custom code.
- **`frozen=True`** — Prevents accidental mutation, aligning with the Clean
  Architecture principle that domain objects should be changed only through
  well-defined use cases.

## Consequences

- Slightly slower construction vs dataclasses (benchmarked ~2–3×, negligible
  at our scale of hundreds per session).
- Additional dependency (`pydantic>=2.0`) — already required for API schemas,
  so no net dependency increase.
- Migration from `dataclasses` to `BaseModel` for legacy types (`ProjectState`,
  `ContextEvent`) is deferred — see `domain/legacy_models.py`.
