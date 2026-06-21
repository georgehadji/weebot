# Weebot — Implementation Plan

**Document Version**: 1.0
**Date**: 2026-06-20
**Author**: Systems Audit — Meta-Orchestration v4.0, Cycle 1 (HARDEN)
**Status**: Draft for Review

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current Architecture Assessment](#2-current-architecture-assessment)
3. [Detailed Implementation Plan](#3-detailed-implementation-plan)
4. [Task Breakdown Structure (WBS)](#4-task-breakdown-structure-wbs)
5. [Risk & Mitigation Matrix](#5-risk--mitigation-matrix)
6. [Testing & Quality Assurance Strategy](#6-testing--quality-assurance-strategy)
7. [Deployment & Rollback Plan](#7-deployment--rollback-plan)
8. [Post-Implementation Validation Checklist](#8-post-implementation-validation-checklist)

---

## 1. Executive Summary

### 1.1 System State at Assessment

Weebot is a Python agent framework built on **Clean Architecture** (Domain → Application → Infrastructure → Interfaces). It orchestrates LLM-powered task execution via a `PlanActFlow` state machine backed by a multi-provider model cascade. The system is under **active single-developer development** with 46 files modified in the assessment window.

**Active State**: **FRAGILE** — dominant. The system depends on 6+ external LLM APIs but has no proactive health monitoring for any of them. A single provider outage (OpenRouter credit exhaustion) caused complete system collapse during the assessment, requiring an emergency engineering workaround to restore function via the native xAI API.

| Composite Metric | Score | Interpretation |
|-----------------|-------|---------------|
| Complexity (C) | 6.0 / 10 | Manageable — clean layers but triple-redundant model config |
| Stability (S) | 5.0 / 10 | Tasks complete but zero test coverage for critical routing |
| Fragility (F) | **7.0** / 10 | 6+ unmonitored external dependencies |
| Growth (G) | 5.0 / 10 | Active feature development |
| Pressure (P) | 3.0 / 10 | Personal/dev tool, operational pressure from API limits |
| Regret Envelope (RE) | 6.5 / 10 | Moderate blast radius |
| Regret Potential (RP) | 3.25 / 10 | Acceptable — fragility offset by low pressure |

### 1.2 Bugs Fixed In-Session (Pre-HARDEN)

Six defects were identified and patched during the assessment window:

| # | Bug | Root Cause | File(s) Fixed |
|---|-----|-----------|---------------|
| BF-1 | xAI native API unreachable — all calls routed through OpenRouter | `create_llm_adapter()` hardcoded `provider="openrouter"`, ignoring the model catalog's `provider` field | `_service.py:58`, `_catalog.py` (4 models) |
| BF-2 | xAI adapter used OpenRouter key against xAI endpoint | `adapter_factory.py` xAI branch assigned `_xai_key = api_key` (the OpenRouter key) before checking `XAI_API_KEY` | `adapter_factory.py:290` |
| BF-3 | Admin/coder role cascades contained zero xAI models — never tried native API | `_ROLE_MODEL_CASCADE` for `"admin"` used `moonshotai/kimi-k2.6` etc., all OpenRouter-routed | `model_refs.py` (3 cascades) |
| BF-4 | Browser tools silently dropped from tool collection | `AgentRunner._ensure_tools()` called `build_tools()` without `llm_port`, causing `BrowserTool` to skip construction | `agent_runner.py:64` |
| BF-5 | Constraint guard paused batch execution with no WAITING status | `ExecutingState` yielded `WaitForUserEvent` without setting `SessionStatus.WAITING`, preventing `resume_session()` | `executing.py:112` |
| BF-6 | Plan review gate blocked batch execution | `PlanReviewState` paused for user approval; no env-var bypass existed | `plan_act_flow.py:818` (added `CONTEXT_AWARE_MODEL_SELECTION` gate) |

### 1.3 Recommended HARDEN Actions

Three mitigations selected via the Meta-Orchestration protocol, within the Complexity Budget ceiling (ΔC ≤ 0.9):

| Priority | Mitigation | C Cost | RP Delta |
|----------|-----------|--------|----------|
| **P0** | Add xAI health monitoring to `LLMHealthMonitor` | +0.2 | −0.5 |
| **P1** | Add OpenRouter credit pre-check to cascade | +0.3 | −1.0 |
| **P2** | Add startup model catalog cross-validation | +0.3 | −0.5 |
| **Deferred** | Browser tool invocation audit | — | — |

**Expected outcome**: Fragility (F) reduced from 7.0 → 4.5, Regret Potential (RP) from 3.25 → 1.8. Convergence verdict: **PARTIAL** — stability improvement to 5.5 is speculative without test coverage.

---

## 2. Current Architecture Assessment

### 2.1 Architecture Overview

```
┌──────────────────────────────────────────────────┐
│                  INTERFACES                       │
│  cli/main.py   web/main.py   run_mcp.py          │
└──────────────────────┬───────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────┐
│                APPLICATION                        │
│  PlanActFlow  ─┬─  PlannerAgent                   │
│   State Machine ─┤  ExecutorAgent                 │
│                 └─  CascadeExecutor               │
│  CQRS Mediator  │  TaskRunner  │  Skills          │
└──────────────────────┬───────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────┐
│              INFRASTRUCTURE                       │
│  LLM Adapters (7 files)  │  SQLite Persistence    │
│  Playwright Browser      │  MCP Toolkit           │
│  Health Monitors         │  Circuit Breakers      │
└──────────────────────┬───────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────┐
│                  DOMAIN                           │
│  Pydantic Models: Plan, Step, Session, Event      │
│  Ports (ABCs): LLMPort, StateRepoPort, etc.       │
└──────────────────────────────────────────────────┘
```

The architecture follows **Dependency Inversion**: all dependencies point inward. Domain has zero imports from outer layers. Interfaces depend on Application, which depends on Infrastructure Ports (ABCs), not concrete implementations.

### 2.2 Dependency Analysis

| Layer | Files | Inbound Dependencies | Circular Dependencies |
|-------|-------|---------------------|----------------------|
| Domain | 15+ | 0 (leaf) | None |
| Application | 30+ | Domain only | None detected |
| Infrastructure | 25+ | Domain ports, Application agents | None |
| Interfaces | 10+ | Application, Infrastructure | None |

Dependency depth is **2-3 layers maximum** — interface → service/agent → port. No circular imports detected in the files surveyed.

### 2.3 External Integration Points

| Service | Endpoint | Auth | Health Monitoring | Circuit Breaker |
|---------|----------|------|-------------------|-----------------|
| OpenRouter | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` | Partial (import check only) | Per-session (resets each run) |
| xAI (Grok) | `https://api.x.ai/v1` | `XAI_API_KEY` | **None** | Via `DirectOrFallbackAdapter` |
| DeepSeek | Direct API | `DEEPSEEK_API_KEY` | None | None (routing broken per BF-1) |
| Kimi/Moonshot | Direct API | `KIMI_API_KEY` | None | None |
| Playwright | Local process | N/A | None | None |
| browser-use | Python lib | `BROWSER_USE_API_KEY` | None | None |

**Critical finding**: Only OpenRouter has any health monitoring, and even that is a lightweight import verification — not an actual API ping. The `LLMHealthMonitor` explicitly states: *"No API quota is consumed — HealthCheckService does lightweight connectivity checks (import verification), not generation calls"* (`weebot/infrastructure/monitors/llm_health_monitor.py:41`).

### 2.4 Model Cascade Architecture — Duplication Identified

Four independent cascade systems exist with **no cross-references**:

| Cascade | Location | Lines | Purpose |
|---------|----------|-------|---------|
| Role-based | `config/model_refs.py` | 470 | Maps 10 agent roles → [primary, fallback1, fallback2] |
| Task-based | `core/model_cascade_config.py` | 597 | Maps 7 task types → ModelConfig lists |
| Enhanced OpenRouter | `core/openrouter_enhanced_cascade.py` | 592 | Vendor-provider sorting, variant handling |
| Provider-level | `infrastructure/adapters/llm/direct_or_fallback_adapter.py` | 185 | Direct API → OpenRouter fallback per call |

Additionally, `_catalog.py` (3,100 lines, 343 models) is a third independent model listing used only by `ModelSelectionService` — it has no consumers in the cascade execution path.

### 2.5 Technical Debt Items

| Item | Severity | Location |
|------|----------|----------|
| Triple-redundant model configuration | Medium | `model_refs.py`, `model_cascade_config.py`, `_catalog.py` |
| 3,100-line model catalog (copy-paste boilerplate) | Medium | `_catalog.py` |
| Zero test coverage for critical routing files | **High** | `adapter_factory.py`, `_cascade.py`, `_service.py` |
| No active API health monitoring for 5 of 6 providers | **High** | `llm_health_monitor.py` |
| One TODO (MiniMax adapter) | Low | `adapter_factory.py:281` |
| Catalog duplicate keys (free variant overwritten by paid) | Low | `_catalog.py` docstring |

### 2.6 Security Posture

- **API keys**: Stored in `.env`, loaded via `python-dotenv` with `override=True`. Not committed to VCS (`.env` in `.gitignore` [VF]).
- **Credential sanitizer**: `weebot/core/credential_sanitizer.py` redacts credentials from user input before persistence.
- **Bash guard**: `weebot/core/bash_guard.py` enforces 4-tier risk levels (SAFE, SUSPICIOUS, DANGEROUS, BLOCKED) on all shell commands.
- **No SSRF protection**: Browser tools (`browser_navigator`, `advanced_browser`) can navigate to arbitrary URLs — no allowlist/denylist for target domains.
- **No rate limiting**: The cascade can fire multiple parallel LLM requests (Phase 1 probes) with no global rate limiter.

---

## 3. Detailed Implementation Plan

### 3.1 Phase Structure

```
Phase 1 (HARDEN — Current Cycle)
  ├── P0: xAI Health Monitoring       [0.5 day]
  ├── P1: OpenRouter Credit Check     [0.5 day]
  └── P2: Catalog Cross-Validation    [1.0 day]
                                  Total: ~2 days

Phase 2 (HARDEN — Next Cycle, after P0-P2 verified)
  ├── P3: DeepSeek native routing fix
  ├── P4: Kimi/Moonshot native routing fix
  └── P5: Global rate limiter for cascade probes
                                  Total: ~3 days

Phase 3 (SIMPLIFY — After F < 4 achieved)
  ├── P6: Merge role-based + task-based cascades
  └── P7: Auto-generate catalog from OpenRouter/models API
                                  Total: ~4 days

Phase 4 (EXPAND — After S > 7 AND RP < 3 achieved)
  └── P8: Model-aware tool selection (browser tools for capable models)
                                  Total: ~2 days
```

### 3.2 Phase 1 — HARDEN (Current Cycle)

#### P0: xAI Health Monitoring

**Objective**: Detect xAI API degradation before it causes cascade failure. Currently, xAI failures are silent — the `DirectOrFallbackAdapter` falls through to OpenRouter, which masks the root cause.

**Affected Components**:
- `weebot/infrastructure/monitors/llm_health_monitor.py` — extend existing monitor
- `weebot/infrastructure/adapters/llm/direct_or_fallback_adapter.py` — consume health status

**Design Changes**:
1. Add `XAIHealthCheck` class to `LLMHealthMonitor`:
   - Pings `https://api.x.ai/v1/models` with `XAI_API_KEY`
   - Validates HTTP 200 + non-empty model list
   - Reports: `HEALTHY`, `DEGRADED` (latency > 5s), `DOWN` (non-200 or timeout)
2. Add `_xai_health` property to `DirectOrFallbackAdapter`:
   - If xAI is `DOWN` for 3+ consecutive checks, skip primary and route directly to fallback
   - Log at WARNING level: "xAI health check failed N times — routing all traffic to OpenRouter"
3. Register xAI health check in the existing `HealthCheckService` loop (every 60s)

**Implementation Tasks**:
- [ ] T1.1: Add `XAIHealthCheck` dataclass to `llm_health_monitor.py`
- [ ] T1.2: Implement `_ping_xai()` async method with 10s timeout
- [ ] T1.3: Wire into `HealthCheckService` periodic loop
- [ ] T1.4: Add `_xai_failure_count` and circuit-break logic to `DirectOrFallbackAdapter`
- [ ] T1.5: Add CLI command: `python -m cli.main health --xai`

**Testing Strategy**:
- Unit: Mock `httpx.get` to return 200, 401, 500, timeout — verify correct status enum
- Unit: Verify `DirectOrFallbackAdapter` skips primary after 3 consecutive DOWN states
- Integration: Run health check against live xAI API, confirm HEALTHY response

**Acceptance Criteria**:
- `python -m cli.main health` shows xAI status alongside existing provider statuses
- When xAI is healthy, `DirectOrFallbackAdapter` routes `x-ai/*` models through primary
- When xAI is DOWN (3+ failures), adapter logs WARNING and routes directly to OpenRouter
- Health check never blocks the hot call path (fail-open: if health check itself fails, assume HEALTHY)

**Rollback**: Remove `XAIHealthCheck` registration from `HealthCheckService`. The `DirectOrFallbackAdapter` change is purely additive — remove the health-gate block.

---

#### P1: OpenRouter Credit Pre-Check

**Objective**: Prevent the cascade from attempting OpenRouter models when credits are below a safe threshold. The 402 "insufficient credits" error was encountered 100+ times during the assessment session — each one wasted a cascade timeout (15-90s).

**Affected Components**:
- `weebot/infrastructure/monitors/llm_health_monitor.py` — credit check
- `weebot/application/agents/executor/_cascade.py` — consume credit status

**Design Changes**:
1. Add credit threshold constant: `OPENROUTER_MIN_CREDITS = 10000` (tokens)
2. Implement `_check_openrouter_credits()` — queries OpenRouter's credit/generation endpoint if available, or uses a heuristic (last successful call's token count vs. remaining credits from 402 error metadata)
3. In `_cascade.py`'s model list builder, filter out OpenRouter models when credits < threshold
4. Log at INFO: "Skipping N OpenRouter models — credits below threshold (X available, Y needed)"

**Implementation Tasks**:
- [ ] T2.1: Research OpenRouter credit API — identify endpoint or parse 402 error metadata
- [ ] T2.2: Implement `OpenRouterCreditCheck` in `llm_health_monitor.py`
- [ ] T2.3: Add `openrouter_credits_ok` flag to cascade model list builder
- [ ] T2.4: Add CLI command: `python -m cli.main health --credits`

**Testing Strategy**:
- Unit: Mock credit API response — verify models are filtered when below threshold and included when above
- Unit: Verify cascade still works (with remaining providers) when OpenRouter models are removed
- Integration: Test with actual OpenRouter account at varying credit levels

**Acceptance Criteria**:
- Cascade skips OpenRouter models when credits < 10k tokens (configurable)
- Warning log emitted when models are skipped
- No 402 errors reach the executor — credit exhaustion is caught at cascade construction time
- Other providers (xAI, DeepSeek direct) continue to work unaffected

**Rollback**: Remove the credit-check filter from the cascade model list builder. Health check addition is additive and harmless to remove.

---

#### P2: Startup Model Catalog Cross-Validation

**Objective**: Detect model catalog / cascade divergence at startup rather than at runtime. Bug BF-1 (xAI models with `provider="openrouter"`) existed silently in the codebase — there was no mechanism to validate that cascade model lists reference valid, correctly-provider-tagged catalog entries.

**Affected Components**:
- New file: `weebot/config/_catalog_validator.py`
- `weebot/config/model_refs.py` — add validate hook
- `weebot/application/services/model_registry/_catalog.py` — reference for validation

**Design Changes**:
1. Create `CatalogValidator` with a single public method: `validate(role_cascades, catalog) -> List[ValidationWarning]`
2. For each model in `_ROLE_MODEL_CASCADE` (all roles, all tiers):
   - Verify it exists in `_catalog.py`
   - Verify its `provider` field matches the expected adapter (e.g., `x-ai/grok-build-0.1` → `provider="xai"`)
   - Verify the model name is in the correct format for its provider
3. Run validation at DI container initialization (`Container.configure_defaults()`)
4. **Fail open**: validation warnings are logged at WARNING level but never block startup
5. Add `python -m cli.main doctor --validate-catalog` for manual checks

**Implementation Tasks**:
- [ ] T3.1: Create `weebot/config/_catalog_validator.py` with `CatalogValidator` class
- [ ] T3.2: Implement `validate()` method with the three checks above
- [ ] T3.3: Wire into `Container.configure_defaults()` — call after catalog is loaded
- [ ] T3.4: Add `--validate-catalog` flag to `cli/main.py doctor` command
- [ ] T3.5: Add a lightweight "ping one model per provider" test that runs on first flow execution

**Testing Strategy**:
- Unit: Feed validator known-good and known-bad catalogs — verify correct warnings
- Unit: Test edge cases: missing model, wrong provider, empty cascade, duplicate entries
- Integration: Run against current catalog — should produce zero warnings after BF-1 fixes

**Acceptance Criteria**:
- `python -m cli.main doctor --validate-catalog` lists all models that fail validation
- Startup log shows "[CatalogValidator] N models validated, M warnings" (M=0 for clean catalog)
- A model with `provider="openrouter"` in an xAI cascade slot triggers a WARNING
- Validation never blocks startup (fail-open)

**Rollback**: Remove the `CatalogValidator` call from `Container.configure_defaults()`. The validator module is standalone — no other code depends on it.

---

### 3.3 Deferred Items (Future Cycles)

| Item | Reason for Deferral | Planned Cycle |
|------|-------------------|---------------|
| Browser tool invocation audit | Complexity budget exceeded (C cost 0.2, budget ceiling reached). Low impact — best addressed by model selection. | Phase 4 (EXPAND) |
| DeepSeek native routing | DeepSeek models still have `provider="openrouter"` in catalog (same BF-1 pattern as xAI was). Lower priority because DeepSeek is not in primary cascade slots. | Phase 2 (HARDEN) |
| Merge role-based + task-based cascades | C reduction (SIMPLIFY) — requires careful migration to avoid breaking existing flows. Best done after HARDEN stabilizes the system. | Phase 3 (SIMPLIFY) |
| Auto-generate catalog from API | The 3,100-line `_catalog.py` is manually maintained. OpenRouter and xAI both have `/v1/models` endpoints that could auto-populate it. | Phase 3 (SIMPLIFY) |

---

## 4. Task Breakdown Structure (WBS)

```
1. Weebot HARDEN Cycle 1
   1.1 P0: xAI Health Monitoring
       1.1.1 Implement XAIHealthCheck dataclass
       1.1.2 Implement _ping_xai() async method
       1.1.3 Wire into HealthCheckService loop
       1.1.4 Add circuit-break logic to DirectOrFallbackAdapter
       1.1.5 Add CLI health --xai command
       1.1.6 Write unit tests (mock API responses)
       1.1.7 Code review
   1.2 P1: OpenRouter Credit Pre-Check
       1.2.1 Research OpenRouter credit API endpoint
       1.2.2 Implement OpenRouterCreditCheck
       1.2.3 Add credit filter to cascade model list builder
       1.2.4 Add CLI health --credits command
       1.2.5 Write unit tests (mock credit levels)
       1.2.6 Integration test with live OpenRouter account
       1.2.7 Code review
   1.3 P2: Startup Catalog Cross-Validation
       1.3.1 Create _catalog_validator.py module
       1.3.2 Implement validate() method
       1.3.3 Wire into Container.configure_defaults()
       1.3.4 Add doctor --validate-catalog CLI flag
       1.3.5 Add first-flow model ping test
       1.3.6 Write unit tests (good/bad catalogs)
       1.3.7 Code review
   1.4 Integration & Verification
       1.4.1 Run full test suite (pytest tests/ -v)
       1.4.2 Run health check CLI (all providers)
       1.4.3 Run catalog validation
       1.4.4 Execute one browser task as smoke test
       1.4.5 Execute one email task as smoke test
       1.4.6 Verify no regression in PlanActFlow execution
```

---

## 5. Risk & Mitigation Matrix

| ID | Risk | Probability | Impact | Detection | Mitigation | Residual Risk |
|----|------|------------|--------|-----------|------------|---------------|
| R1 | Health ping consumes API quota | Low | Low | Quota dashboard | Use `/v1/models` (free on both OpenRouter and xAI). Set ping interval to 60s minimum. | Minimal — 1 free request/minute |
| R2 | xAI health check blocks startup | Low | Medium | Integration test | Fail-open: if health check itself times out, assume HEALTHY. Log warning. | Startup proceeds; operator sees warning |
| R3 | Catalog validator false-positives on legitimate model names | Medium | Low | Manual review | Warnings are non-blocking. New models can be added to a skip-list. | Operator investigates warnings at leisure |
| R4 | OpenRouter credit API changes or is unavailable | Medium | Medium | 4xx error in logs | Graceful degradation: if credit API fails, assume credits OK and proceed. | Cascade may attempt OpenRouter models with insufficient credits (status quo) |
| R5 | Increased startup time from catalog validation | Low | Low | Timing log | Validation runs once at startup, O(n) where n = number of cascade models (~30). Should take <100ms. | Negligible |
| R6 | Single developer bus factor | High | High | N/A | Document all changes in this plan. Ensure rollback is trivial (remove registration calls). | Inherent — not addressable in code |

---

## 6. Testing & Quality Assurance Strategy

### 6.1 Current State

**Zero test coverage** exists for the critical routing files modified in this cycle: `adapter_factory.py`, `_cascade.py`, `_service.py`, `executing.py`, `agent_runner.py`, and `direct_or_fallback_adapter.py`. The only cascade-related test is `tests/unit/test_executor_agent.py` which tests the `ExecutorAgent` class but not the cascade routing logic.

### 6.2 Test Pyramid for New Code

```
     ┌──────┐
     │ E2E  │  1 test: smoke-test a full PlanActFlow with
     │      │  xAI primary + health monitoring enabled
     ├──────┤
     │ INT  │  3 tests: health check CLI, catalog validator,
     │      │  DirectOrFallbackAdapter with mock health states
     ├──────┤
     │ UNIT │  12+ tests: one per new function/method
     │      │  (see WBS tasks 1.1.6, 1.2.5, 1.3.6)
     └──────┘
```

### 6.3 Unit Test Specifications

**`test_xai_health_monitor.py`**:
- `test_ping_xai_healthy` — mock 200 + model list → HEALTHY
- `test_ping_xai_degraded` — mock 200 with 6s latency → DEGRADED
- `test_ping_xai_down_401` — mock 401 → DOWN
- `test_ping_xai_down_timeout` — mock timeout → DOWN
- `test_circuit_breaker_opens_after_3_failures` — verify adapter skips primary
- `test_circuit_breaker_resets_on_success` — verify adapter re-enables primary

**`test_openrouter_credit_check.py`**:
- `test_credits_above_threshold` — models included
- `test_credits_below_threshold` — models filtered out
- `test_credit_api_unavailable` — graceful degradation (assume OK)
- `test_cascade_still_works_without_openrouter` — other providers unaffected

**`test_catalog_validator.py`**:
- `test_all_models_valid` — clean catalog → zero warnings
- `test_missing_model` — model in cascade but not in catalog → WARNING
- `test_wrong_provider` — model has `provider="openrouter"` but expected `"xai"` → WARNING
- `test_empty_cascade` — empty cascade list → handled gracefully
- `test_duplicate_entries` — same model in two cascade tiers → INFO

### 6.4 Regression Test

Before merging any HARDEN change, run:
```bash
pytest tests/ -v --cov=weebot --cov-report=term-missing
python -m cli.main health
python -m cli.main doctor
python scripts/run_browser_tasks.py --task 1 --dry-run  # verify no import errors
```

---

## 7. Deployment & Rollback Plan

### 7.1 Deployment Strategy

All three mitigations are **additive** — they extend existing modules without modifying hot call paths:

| Mitigation | Deployment Risk | Strategy |
|-----------|----------------|----------|
| P0 (xAI health) | Low — adds health check, doesn't change routing unless circuit opens | Deploy independently, verify health CLI works |
| P1 (OpenRouter credit) | Low — filters model list at cascade construction, doesn't change API calls | Deploy after P0 verified |
| P2 (Catalog validator) | Very Low — warnings only, never blocks startup | Deploy anytime, independently |

**Recommended order**: P2 → P0 → P1 (safest first).

### 7.2 Rollback Protocol

Each mitigation is independently revertible:

1. **Pre-deployment snapshot**:
   ```bash
   git tag pre-harden-cycle1
   git push origin pre-harden-cycle1
   ```

2. **Per-mitigation rollback**:
   - **P2**: Remove `CatalogValidator` call from `Container.configure_defaults()`. Delete `_catalog_validator.py`.
   - **P1**: Remove credit-check filter from `_cascade.py` model list builder. Remove `OpenRouterCreditCheck` from health monitor.
   - **P0**: Remove `XAIHealthCheck` from `HealthCheckService` registration. Remove health-gate from `DirectOrFallbackAdapter`.

3. **Full rollback**: `git revert` the three mitigation commits in reverse order.

### 7.3 Rollback Trigger Conditions

- Any mitigation causes a **5xx error** in the hot call path
- **Startup time increases by >2 seconds** (catalog validation or health check blocking)
- **False-positive circuit breaks**: xAI marked DOWN while actually healthy
- **Regression in PlanActFlow**: any existing task fails that previously passed

---

## 8. Post-Implementation Validation Checklist

### 8.1 Health Monitoring Validation

- [ ] `python -m cli.main health` shows all provider statuses
- [ ] xAI status is HEALTHY when API is reachable
- [ ] xAI status transitions to DOWN when API key is intentionally invalidated (test only)
- [ ] OpenRouter credit status is reported (if API available) or gracefully absent
- [ ] Health check failures never block the hot call path (test by temporarily blocking xAI endpoint)

### 8.2 Cascade Validation

- [ ] `python -m cli.main doctor --validate-catalog` produces zero warnings
- [ ] Intentionally break one model entry — verify WARNING appears, startup proceeds
- [ ] Cascade still routes `x-ai/grok-build-0.1` through native xAI API (not OpenRouter)
- [ ] OpenRouter models are skipped when credits below threshold

### 8.3 Functional Smoke Tests

- [ ] **Browser Task**: `python scripts/run_browser_tasks.py --task 1` completes successfully
- [ ] **Email Task**: `python scripts/run_email_tasks.py --task 1` completes successfully
- [ ] **LinkedIn Task**: `python scripts/run_linkedin_tasks.py --task 1` runs without API errors
- [ ] **Health Check**: `python -m cli.main health` returns 0 exit code
- [ ] **Doctor**: `python -m cli.main doctor` returns 0 exit code

### 8.4 Metrics Collection

After 1 week of operation post-deployment:

- [ ] Count of xAI circuit-break events (should be 0 in normal operation)
- [ ] Count of OpenRouter credit-skip events
- [ ] Catalog validation warnings at startup (should be 0)
- [ ] Any regression in task completion rate vs. pre-deployment baseline

### 8.5 Documentation

- [ ] Update `CLAUDE.md` with new CLI commands (`health --xai`, `health --credits`, `doctor --validate-catalog`)
- [ ] Document `CONTEXT_AWARE_MODEL_SELECTION`, `CONSTRAINT_CHECK_ENABLED`, `PLAN_REVIEW_ENABLED`, `COVE_ENABLED` env vars in README or developer docs
- [ ] Add inline docstrings to new classes: `XAIHealthCheck`, `OpenRouterCreditCheck`, `CatalogValidator`

---

## Appendix A: Engineering Practices Applied

| Principle | Application in This Plan |
|-----------|------------------------|
| **SOLID — Single Responsibility** | Each mitigation addresses one concern: health monitoring, credit checking, catalog validation |
| **SOLID — Open/Closed** | Health checks extend the monitor (open for extension) without modifying its core loop (closed for modification) |
| **SOLID — Dependency Inversion** | New health checks depend on `HealthCheckPort` (ABC), not concrete implementations |
| **Clean Architecture** | All changes in Infrastructure layer; Application layer consumes via ports; Domain untouched |
| **Separation of Concerns** | `CatalogValidator` is a standalone module with one job; `DirectOrFallbackAdapter` health-gate is a separate concern from routing |
| **DRY** | `XAIHealthCheck` reuses the existing `HealthCheckService` loop pattern; credit check reuses the same monitor infrastructure |
| **KISS** | Health checks are simple HTTP pings with timeout — no complex state machines or distributed consensus |
| **YAGNI** | Deferred: browser tool audit, DeepSeek native routing, cascade merge — not needed for current HARDEN cycle |
| **Secure-by-Design** | Health check API keys are read from existing `.env` (never hardcoded); validation warnings never expose key material |
| **Defensive Programming** | All health checks fail-open (assume HEALTHY on check failure); catalog validator warns but never blocks |
| **Observability** | Structured logging at INFO/WARNING for all health state transitions; circuit-break events logged prominently |
| **Fail-Fast** | Catalog validation runs at startup — catches misconfiguration before any task executes |

---

## Appendix B: Glossary

| Term | Definition |
|------|-----------|
| **Cascade** | The ordered list of LLM models tried per execution step: primary → fallback1 → fallback2. If primary fails, the next is tried. |
| **Circuit Breaker** | A pattern that stops calling a failing dependency after N consecutive failures, preventing cascading latency. |
| **DirectOrFallbackAdapter** | An adapter that tries a provider's native API first (e.g., xAI direct), then falls back to OpenRouter if the native call fails. |
| **HealthCheckService** | A periodic background task that pings external dependencies and reports their status. Currently import-only, not active probing. |
| **PlanActFlow** | The core state machine: PlanningState → ExecutingState → VerifyingState → CompletedState. Handles replanning on failure. |
| **Regret Envelope (RE)** | Composite metric: `(Complexity + Fragility) / 2`. Measures blast radius — how bad could a failure be? |
| **Regret Potential (RP)** | Composite metric: `RE × (10 − Stability) / 10`. Combines blast radius with probability of latent defects. Primary input to mode selection. |
| **Growth Tension (GT)** | Composite metric: `Growth × (1 + Pressure/10)`. Measures competitive urgency. |

---

*End of document. Next re-assessment triggered after 2-day mitigation window OR if OpenRouter/xAI experiences another outage.*
