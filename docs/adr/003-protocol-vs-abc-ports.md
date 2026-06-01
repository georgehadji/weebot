# ADR 003: Protocol (domain) vs ABC (application) for Ports

**Status:** Accepted  
**Date:** 2026-06-01  
**Deciders:** Architecture Team  

## Context

Clean Architecture ports (interfaces) can be defined as either
`typing.Protocol` (structural typing, "duck typing") or `abc.ABC`
( nominal typing, explicit inheritance). weebot uses both in
different places, creating inconsistency.

## Decision

- **Domain-layer ports** (`weebot/domain/ports.py`) use `typing.Protocol`
  — structural typing, no dependency on `abc`.
- **Application-layer ports** (`weebot/application/ports/`) use `abc.ABC`
  — nominal typing with abstract methods.

## Rationale

### Domain → Protocol

- Domain layer must have zero dependencies — `Protocol` is in stdlib
  (`typing`), while `ABC` is also stdlib but encourages subclassing
  patterns more suited to infrastructure.
- Domain services (e.g., `WorkingMemory`) depend on `EventPublisher` as
  a protocol — any object with the right `publish` method satisfies it,
  enabling easy testing with mocks and stubs.
- `@runtime_checkable` allows `isinstance()` checks for testing.

### Application → ABC

- Application ports (`StateRepositoryPort`, `LLMPort`, `SandboxPort`)
  have complex interfaces (5+ methods) — `ABC` with `@abstractmethod`
  provides compile-time enforcement that all methods are implemented.
- Infrastructure adapters (`SQLiteStateRepository`, `OpenRouterAdapter`)
  explicitly inherit from the port, making the dependency visible and
  traceable.
- IDEs and type checkers provide better support for abstract methods
  than protocols.

## Consequences

- Developers must choose the right pattern based on layer: Protocol in
  domain, ABC in application.
- Some ports (e.g., `EventBusPort`) are ABC but used in domain-adjacent
  code — this is acceptable since they're in `application/ports/`.
- Long-term, if Python adds native interface support (PEP 695-style),
  both approaches could be unified.
