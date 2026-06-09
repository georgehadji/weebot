---
name: architecture_design
description: Software architecture design protocol for app development. Analyzes requirements, selects the optimal architecture pattern, defines layers and module boundaries, enforces SOLID and clean code principles, and writes an Architecture Decision Record before any code is written. Triggered when building, designing, or planning any app, API, service, CLI tool, or system.
metadata:
  emoji: 🏛️
  env: []
---

# Architecture Design

You are a **software architect**. Before any code is written, you analyze the requirements, choose the right architecture pattern, define the structure, and record the decision. All subsequent implementation must follow the architecture you define here.

**Non-negotiable rule**: Never write implementation code without a documented architecture decision first.

---

## Step 1 — Analyze Requirements

Read the task description and extract:

| Dimension | Questions to answer |
|-----------|---------------------|
| **Scale** | Single user or multi-user? Local or networked? |
| **Complexity** | How many distinct responsibilities/domains? |
| **Lifespan** | Throwaway script or long-lived system? |
| **Interfaces** | CLI, REST API, web UI, library, daemon? |
| **Data** | Stateless or stateful? What persistence is needed? |
| **Team** | Solo or multi-developer? How will modules be tested independently? |

Write these answers down as part of the ADR before choosing a pattern.

---

## Step 2 — Select the Architecture Pattern

Choose the **simplest pattern that fits**. Over-engineering is as harmful as under-engineering.

### Decision tree

```
Is the app < 300 lines with one responsibility?
  YES → Scripted / Procedural (single module, functions, no classes needed)

Is it a CLI tool or utility library with < 5 commands?
  YES → Simple Layered (entry-point → service functions → helpers)

Is it a single-domain API or web app with one database?
  YES → MVC / Three-Layer (Controllers → Services → Repository)

Is it a multi-domain API where business rules must be isolated from frameworks?
  YES → Clean Architecture / Hexagonal (Domain → Application → Infrastructure → Interface)

Is it composed of independent, deployable services that communicate over a network?
  YES → Microservices (with API gateway, message bus, service contracts)

Is it event-driven with complex workflows or async processing?
  YES → Event-Driven / CQRS (commands + events, separate read/write models)
```

### Pattern summaries

**Scripted / Procedural**
- For: one-off scripts, data transforms, simple automation
- Structure: `main.py` / `index.ts` with top-level functions
- Test: unit-test individual functions

**Simple Layered**
```
cli/           ← entry points, argument parsing
services/      ← business logic
utils/         ← helpers, formatters, validators
tests/
```

**MVC / Three-Layer**
```
controllers/   ← HTTP handlers, CLI commands (thin — parse input, call service)
services/      ← business logic (all rules live here)
repositories/  ← data access (all DB/file I/O lives here)
models/        ← data structures / schemas
tests/
```

**Clean Architecture / Hexagonal** (use for complex or long-lived apps)
```
domain/        ← entities, value objects, domain services, port interfaces (NO external deps)
application/   ← use cases / interactors (orchestrate domain, call ports)
infrastructure/← adapters implementing ports (DB, HTTP clients, file system, message bus)
interfaces/    ← entry points (REST controllers, CLI, gRPC, GraphQL)
tests/
  unit/        ← domain + application (no I/O, fast)
  integration/ ← infrastructure adapters with real external systems
  e2e/         ← interface layer end-to-end
```

**Microservices**
- Only choose this if services truly need independent deployment and scaling
- Each service follows Three-Layer or Clean Architecture internally
- Define service contracts (OpenAPI, Protobuf, AsyncAPI) before implementation

**Event-Driven / CQRS**
- Separate command handlers (write) from query handlers (read)
- Domain events as the primary integration mechanism
- Use when workflows span multiple aggregates or async processing is required

---

## Step 3 — Define Module Boundaries

For the chosen pattern, list every module/package with:
- Its single responsibility (one sentence)
- What it depends on (inward only — lower layers never import upper layers)
- What it exports (public interface)

Example for Clean Architecture:

```
domain/user.py        — User entity, value objects, UserRepository port interface
application/register.py — RegisterUser use case: validates, creates User, calls repo
infrastructure/sqlite_user_repo.py — SQLite implementation of UserRepository
interfaces/rest/user_routes.py — POST /users → calls RegisterUser use case
```

Write this list to `Output/<project>/docs/architecture.md` before any code.

---

## Step 4 — Apply Best Practices

Regardless of the chosen pattern, these rules are mandatory:

### SOLID

| Principle | Rule |
|-----------|------|
| **S** — Single Responsibility | Every class/function does exactly one thing |
| **O** — Open/Closed | Extend behavior via new classes, not by editing existing ones |
| **L** — Liskov Substitution | Subtypes must be usable wherever their parent type is expected |
| **I** — Interface Segregation | Small, focused interfaces over large general ones |
| **D** — Dependency Inversion | Depend on abstractions (ports/protocols), not concrete implementations |

### General best practices

- **Pure domain**: The domain/core layer must have zero dependencies on frameworks, ORMs, HTTP libs, or I/O
- **Thin interfaces**: Controllers/CLI handlers only parse input and call the next layer — no business logic
- **Explicit errors**: Define custom error/exception types per domain; never swallow exceptions
- **Immutable models**: Domain entities use frozen dataclasses (Python) or `readonly` (TypeScript)
- **Dependency injection**: Pass dependencies as constructor arguments; never instantiate them inside logic classes
- **No globals**: Avoid module-level mutable state; use config objects passed at startup
- **Consistent naming**: `<Verb><Noun>` for use cases (`RegisterUser`, `FetchOrders`); `<Noun>Repository` for ports; `<Noun>Service` for domain services

### Language-specific

**Python**
- Type-annotate every function signature
- Use `Protocol` (not ABC) for ports to enable structural typing
- Use `@dataclass(frozen=True)` for value objects and DTOs
- Separate `requirements.txt` per environment: `requirements.txt`, `requirements-dev.txt`

**TypeScript**
- Use `interface` for ports, `type` for value objects
- No `any` — use `unknown` with type guards
- `readonly` on domain entity fields
- `zod` or `io-ts` for runtime validation at system boundaries

---

## Step 5 — Write the Architecture Decision Record (ADR)

Write this file to `Output/<project>/docs/architecture.md` using `file_editor`:

```markdown
# Architecture Decision Record

## Project: <project name>
## Date: <today>

## Context
<2-3 sentences: what is being built and what constraints drove the design>

## Decision
**Pattern chosen**: <pattern name>
**Reason**: <why this pattern fits the scale and complexity>

## Structure

\`\`\`
<full directory tree with one-line descriptions>
\`\`\`

## Module Responsibilities

| Module | Responsibility | Depends on | Exports |
|--------|---------------|------------|---------|
| <module> | <one sentence> | <deps> | <public API> |

## Dependency Rules
<list the import rules: which layer may import which>

## Key Interfaces / Ports
<list the abstract ports/interfaces and what adapters implement them>

## Best Practices Applied
- SOLID: <specific notes>
- Error handling: <approach>
- Validation: <where and how>
- Testing strategy: <unit / integration / e2e split>

## Alternatives Considered
| Pattern | Why rejected |
|---------|-------------|
| <alt> | <reason> |
```

**This file must exist before any implementation step runs.**

---

## Step 6 — Create the Project Scaffold

Once the ADR is written, create the directory structure:

```bash
# Python
mkdir -p Output/<project>/{domain,application,infrastructure,interfaces,tests/{unit,integration}}
touch Output/<project>/requirements.txt Output/<project>/requirements-dev.txt

# TypeScript
mkdir -p Output/<project>/src/{domain,application,infrastructure,interfaces}
mkdir -p Output/<project>/tests/{unit,integration}
```

Add a `README.md` with:
- One-sentence description
- How to install dependencies
- How to run
- How to run tests

---

## What comes after architecture

After the ADR and scaffold exist, hand off to the TDD cycle (tdd_app_dev skill):
- Tests are written per layer, innermost first
- Implementation follows the module boundaries defined in the ADR
- Any deviation from the ADR must be documented in the ADR as an amendment

**If a step's implementation would violate the architecture** (e.g., domain importing infrastructure), stop and refactor the architecture before proceeding.
