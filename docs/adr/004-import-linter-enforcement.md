# ADR-004: Mechanical Architecture Enforcement via Import-Linter

**Status:** Accepted
**Date:** 2025-07-17
**Deciders:** Architecture team

## Context

As weebot grew from a single-developer prototype to a multi-contributor
production framework (770+ Python files, 4,500+ dependency edges), the
Clean Architecture boundaries that existed in documentation were eroding
in implementation. Code review alone couldn't catch every import that
crossed a forbidden boundary — reviewers miss things, and pressure to
ship leads to shortcuts.

Traditional linters (Ruff, pylint) can't reason about architectural layer
dependencies. Static analysis tools that can (pylint with custom plugins)
require per-file configuration that's brittle.

## Decision

Adopt **import-linter** as the mechanical architecture enforcement tool,
with contracts for each layer boundary:

- **Domain purity** — domain may not import any outer layer (infrastructure,
  application, interfaces, tools, core).
- **Tools-no-DB** — tools may not import `sqlite3`, `aiosqlite`, or
  `sqlalchemy` directly (they must use ports).
- **Infra-no-app** — infrastructure adapters must depend on ports, not on
  application services/flows/agents.
- **Interfaces-no-infra** — interface entry points must not import
  infrastructure adapters directly (they go through DI).
- **Core-no-app** — cross-cutting core module must not import from
  application or interfaces.

Contracts use the `forbidden` type with transitive dependency checking.
Known deliberate boundary crossings are documented as `ignore_imports`
entries in `.importlinter`, each with a comment explaining why.

### Fitness Test Integration

44 architecture fitness tests in `test_architecture_fitness.py` implement
additional checks beyond import-linter: no module-level singletons outside
DI, no blocking `time.sleep()` in async code, services/flows cycle-free,
ports have adapters, God modules under 800 lines, and more.

## Consequences

**Positive:**
- Architecture drift is caught at CI time, not at production incident time.
- New contributors can see the intended boundaries in `.importlinter`.
- 5 contracts KEPT, 0 BROKEN — every PR runs through this gate.
- The `ignore_imports` list provides a prioritized migration backlog.

**Negative:**
- 52 `ignore_imports` entries (as of this ADR) show the implementation
  hasn't fully caught up to the ideal architecture.
- Transitive dependency checking is strict — core→tools→application paths
  are flagged even when architecturally acceptable. Requires `ignore_imports`
  entries for the tool-intermediary edges.
- Running import-linter on 770 files adds ~30 seconds to CI.

**Compliance:** CI job `make lint-imports` gates every PR. Adding a new
`ignore_imports` entry requires an inline comment explaining the
architectural reason and tracking issue number.
