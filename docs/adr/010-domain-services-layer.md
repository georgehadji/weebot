# ADR-010: Domain Services Layer

**Status:** Accepted  
**Date:** 2026-07-07  
**Deciders:** Architecture team  

## Context

`weebot/domain/services/` contains 11 files (commitment_engine, commitment_extractor,
continuation_detector, filter_key_validator, human_interaction, mcp_tool_index_builder,
plan_novelty, plan_template_cache, session_memory, skill_promotion_gate, working_memory)
with no ADR explaining their role.

## Decision

Domain services are **pure domain logic** that operates on domain models without I/O.
They differ from application services:

- **Domain services** operate on domain entities and value objects only.
- **Application services** orchestrate ports, make I/O calls, and manage transactions.

A domain service:

1. Accepts domain model types as arguments.
2. Returns domain model types (or raises domain exceptions).
3. Has zero imports from `weebot.infrastructure`, `weebot.application`, `weebot.interfaces`,
   or `weebot.core`.
4. May import from `weebot.domain.models`, `weebot.domain.exceptions`, and Python stdlib only.

## Consequences

- Import-linter contract `domain-purity` already enforces rule 3.
- New domain services must pass the "no-I/O" gate in code review.
- Domain services are the ONLY place algorithms that operate on domain models may live
  outside the models themselves.
