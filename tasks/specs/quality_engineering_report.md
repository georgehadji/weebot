# WeeBot Autonomous Quality-Engineering Report

**Date:** 2026-06-22  
**Auditor:** Principal QA Architect / SDET Lead  
**Scope:** Full repository (`E:\Documents\Vibe-Coding\weebot`)

---

## 1. Architecture Summary

### Layer Stack (Hexagonal / Clean Architecture)
```
INTERFACES  → Web(FastAPI), CLI, Gateways(Telegram,Discord), SSE, WebSockets
APPLICATION → Flows(PlanActFlow,ChatFlow), Agents(Planner,Executor),
              CQRS(Commands,Handlers,Mediator), Services(25+), DI Container
DOMAIN      → Models(Plan,Session,Event,Skill,BehavioralRule,etc.), Enums
INFRASTRUCTURE → Adapters(LLM,KnowledgeGraph,Memory), Persistence(SQLite,FTS5),
                 Cache, Sandbox, MCP, EventStore, Notifications
```

### Critical Business Paths (Risk-Prioritized)

| # | Path | Impact | Failure Mode |
|---|------|--------|-------------|
| 1 | `PlanActFlow.run() → PlanningState → ExecutingState → CompletedState` | Core autonomous execution | Plan never completes, tool calls fail silently |
| 2 | `ChatFlow → ChatMessageState → LLM.chat()` | User-facing conversation | Response hallucination, prompt leak |
| 3 | `CascadeExecutor → parallel model cascade → first-responder wins` | Model failover | All models tripped, AllModelsTrippedError |
| 4 | `BashTool.execute() → bash_guard → sandbox → powershell` | Code execution | Command injection, filesystem damage |
| 5 | `save_session() → FTS5 index + commitment extraction` | Data persistence + memory | Session loss, corruption |
| 6 | `autonomous_learning.py → distil skill → SkillStore.save()` | Skill generation | Bad skills injected into executor |
| 7 | `TruthBinder → URL substitution + action announcer + schedule honesty` | Response integrity | Phantom promises, hallucinated actions |

---

## 2. Test Matrix

### Existing Test Coverage (from CI + local runs)

| Suite | Count | Type | Coverage Area |
|-------|-------|------|--------------|
| `test_approval_policy.py` | 17 | Unit | Command approval/deny rules |
| `test_error_classifier.py` | 38 | Unit | Error taxonomy (11 categories) |
| `test_error_classifier_status_codes.py` | 12 | Unit | HTTP status → category mapping |
| `test_vision_reflection.py` | 26 | Unit | Vision reflection parsing |
| `test_caching_llm_adapter.py` | 30 | Unit | Prompt caching wrapper |
| `test_anthropic_caching_adapter.py` | 22 | Unit | JSON normalizer + cache breakpoints |
| `test_tool_call_repair.py` | 29 | Unit | JSON repair + fuzzy name matching |
| `test_commitment.py` | 20 | Unit | Commitment extraction + lifecycle |
| `test_governed_skill_loop.py` | 14 | Unit | Proposal tracker + review gates |
| `test_salience.py` | 15 | Unit | Memory salience scoring + eviction |
| `test_plan_template_cache.py` | 14 | Unit | Template matching + seeding |
| `test_session_search.py` | 2 | Unit | Search enrichment |
| `test_kg_provenance.py` | 3 | Unit | KG node creation |
| `test_user_model_consolidator.py` | 3 | Unit | User profile distillation |
| `test_fts_search.py` | 4+ | Integration | FTS5 indexing + search |
| `test_cqrs_persistence.py` | 5+ | Integration | CQRS handler lifecycle |
| `test_plan_act_flow.py` | 10+ | Integration | Flow state transitions |
| `test_architecture_fitness.py` | 50+ | Structural | Architecture constraints |

### Coverage Gaps → Additional Tests Needed

| Test Type | Priority | Target | Risk |
|-----------|----------|--------|------|
| **Security** | 🔴 HIGH | `TruthBinder` response integrity | Prompt leak, phantom promises |
| **Security** | 🔴 HIGH | `bash_guard.py` edge cases | Command injection |
| **Integration** | 🔴 HIGH | `PlanActFlow` end-to-end with real steps | Execution silent failure |
| **Integration** | 🟡 MED | `CascadeExecutor` all-models-tripped path | Recovery failure |
| **Integration** | 🟡 MED | `PersistentMemoryTool` read/write roundtrip | Data corruption |
| **Contract** | 🟡 MED | `LLMPort` implementations | Provider API changes |
| **Performance** | 🟢 LOW | `save_session` with large event lists | Session save timeout |
| **Concurrency** | 🟢 LOW | `ToolCollection` per-tool semaphore | Race conditions |

---

## 3. Discovered Defects

### Active Defects (from implementation + audit)

| # | Severity | Component | Issue | Root Cause | Status |
|---|----------|-----------|-------|------------|--------|
| D-001 | 🔴 HIGH | `conversation_compressor` | `model=self._model` → should be `cheap_model` | Refactored constructor, call site not updated | ✅ Fixed P0 |
| D-002 | 🔴 HIGH | `_track_salience` in `persistent_memory.py` | `_salience_repo` never initialized | getattr falls to None, early return | ✅ Fixed P2 |
| D-003 | 🔴 HIGH | `CreatePlanHandler` seeding | meta_notes passed to __init__ not create_plan | Wrong method target, bare except swallowed error | ✅ Fixed P2 |
| D-004 | 🔴 HIGH | `sessions.py` route ordering | `/search` shadowed by `/{session_id}` | Route declaration order | ✅ Fixed P2 |
| D-005 | 🔴 HIGH | `_base.py` user profile injection | `threshold=1.0` vs `salience < ?` (exclusive) | Query semantic mismatch | ✅ Fixed P2 |
| D-006 | 🟡 MED | `conversation_compressor.py` | `temperature=TEMPERATURE_BALANCED` → param doesn't exist | Old constructor signature | ✅ Fixed P0 |
| D-007 | 🟡 MED | `memory_lifecycle_service.py` | `hot_min_access` dead config (rule 2 shadowing) | classify() logic order | ✅ Fixed P2 |
| D-008 | 🟡 MED | `classify()` rule 2 shadows rule 1 | HOT requires access ≥ min_access AND age < ttl | Logic flaw in rules | ✅ Fixed P2 |
| D-009 | 🟢 LOW | `plan_template_cache.py` | Duplicate stopword "need" | Manual editing | ✅ Fixed P2 |
| D-010 | 🟢 LOW | `plan_template_cache.py` | Dead constant `_MAX_TASK_CHARS` | Unused variable | ✅ Fixed P2 |

### Potential Defects (hypothesis flags)

| # | Hypothesis | Evidence | Recommended Action |
|---|-----------|----------|-------------------|
| H-001 | `SkillOptFlow` may promote skills without CoVe verification gate | Review gate and promotion gate are defined but not wired to flows | Wire gates into flow |
| H-002 | `OpportunityEngine.scan()` may return empty on fresh database | KG is never populated — discover_node never called in current code | Verify or seed KG |
| H-003 | `TruthBinder` may miss prompt-leak patterns | Regex-based detection, no semantic analysis | Run fuzz tests with synthetic leaks |
| H-004 | `CascadeExecutor` may retry 500 errors unnecessarily | SERVER_ERROR → RETRY action, but 500s on same model always fail | Add model-specific circuit open for 5xx |
| H-005 | `CommitmentEngine.heartbeat()` may mark same commitment overdue twice | No dedup check on already-OVERDUE entries | Verify heartbeat idempotency |

---

## 4. Root Cause Analysis (Selected High-Severity)

### D-001: ConversationCompressor constructor mismatch

**Symptom:** `TypeError: ConversationCompressor.__init__() got an unexpected keyword argument 'model'` raised on first compression attempt.

**Root Cause:** `ConversationCompressor.__init__()` was refactored to accept `cheap_model` instead of `model`, and `temperature` parameter was removed. The call site in `_context_compressor.py:88-91` was never updated.

**Affected Components:** ContextCompressor, ExecutorAgent (via callback chain)

**Fix:** Changed `model=self._model` → `cheap_model=self._model`, removed `temperature=TEMPERATURE_BALANCED`, cleaned up unused import.

### D-005: User profile never injected into executor prompt

**Symptom:** User profile stored with salience=1.0 (pinned), but `get_low_salience_entries(threshold=1.0)` queries `WHERE salience < 1.0` — exclusive comparison. Profile never matched.

**Root Cause:** The `get_low_salience_entries` method is designed for eviction candidates (entries with low salience). The user profile uses salience=1.0 as a "never evict" signal but this also excludes it from the eviction-oriented query.

**Fix:** Changed threshold to `1.01` (pinned entries now match `1.0 < 1.01`). Also added executor-level caching (`_user_profile_cache`) to avoid query on every step.

---

## 5. Fix Options (For Open Hypotheses)

### H-001: Skill promotion without verification gate

| Option | Approach | Risk | Verdict |
|--------|----------|------|---------|
| A | Wire `SkillPromotionGate` into `SkillOptFlow` after each epoch | High — requires CoVe + harness initialization in flow | Deferred to P2 follow-up |
| B | Add a standalone cron job that runs `PromotionGate.evaluate()` on all candidate skills | Medium — periodic, not blocking | ✅ Recommended |
| C | Leave as-is — manual promotion via CLI | Low — no automation, no progress | ❌ Rejected: defeats automation |

**Selected:** Option B — add a `skill_promotion_check` cron job (daily) that evaluates all candidate skills against CoVe + harness thresholds and promotes/persists those that pass.

### H-004: CascadeExecutor retrying 500 errors on same model

| Option | Approach | Risk | Verdict |
|--------|----------|------|---------|
| A | Add per-model circuit breaker for 5xx SERVER_ERROR | Medium — new breaker tracking per model | ✅ Recommended |
| B | Change SERVER_ERROR → FAIL_FAST | High — may break transient 503 recovery | ❌ Rejected: too aggressive |

**Selected:** Option A — add per-model failure counter in CascadeExecutor for SERVER_ERROR with smaller threshold (3 vs 5 for general failures).

---

## 6. Selected Fixes + Implementation Plan

### Fix 1: Skill promotion cron job (H-001)

**File:** `weebot/config/jobs.yaml`, `weebot/application/di/_capabilities.py`

### Fix 2: Per-model 5xx circuit breaker (H-004)

**File:** `weebot/application/agents/executor/_cascade.py`

Shall I proceed to implement these two fixes?
