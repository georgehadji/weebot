# ADR-011: Port Hierarchy Consolidation

**Status:** Accepted  
**Date:** 2026-07-07  
**Deciders:** Architecture team  

## Context

Weebot has two parallel port hierarchies:

- `weebot/domain/ports.py` — Protocol-based (`IModelProvider`, `IRepository`).
  From the pre-ADR era. 5 consumers.
- `weebot/application/ports/` — 50+ ABC-based ports. Post-ADR. 50+ consumers.

## Decision

Consolidate into a single hierarchy:

1. `application/ports/` is the canonical location for all ports.
2. `domain/ports.py` is frozen — no new ports added.
3. The 5 existing consumers of `domain/ports.py` migrate to
   `application/ports/` equivalents:
   - `IModelProvider` → `LLMPort`
   - `IRepository` → `StateRepositoryPort`
4. `domain/ports.py` is deleted after migration (target: 2026-09-01).

## Consequences

- Single source of truth for all port interfaces.
- Domain layer becomes truly model-only (no interface definitions).
- Migration may surface impedance mismatches between Protocol duck-typing
  and ABC nominal-typing — fix adapters as needed.
