# P2 Audit Report — Commitments / Promise-Honoring System

**Plan:** `weebot_unified_implementation_plan.md` · P2 Grows-with-you (Sprint 4–6) — Item 1  
**Date:** 2026-06-22 (implementation + audit)  
**Auditor:** Reasonix Code (automated review + manual verification)  
**Final Verdict:** 🟢 **APPROVED** — audit fixes applied, extraction + surfacing wired, 87 tests pass

---

## 1. Executive Summary

The commitments system was structurally sound but had **4 blocking gaps** (dead extraction path, dead surfacing path, timezone mismatch, dead code). All were fixed in the audit. The system now:

1. **Extracts commitments** from assistant messages during `save_session` — writes to `commitments` table
2. **Heartbeats** every 30 min via the APScheduler cron — marks overdue commitments
3. **Surfaces** pending commitments into the chat flow — injects summary into the session context
4. Uses timezone-aware datetimes consistently across domain, persistence, and engine

**87 tests pass**, zero regressions across P0 + P1 + P2 test suites.

---

## 2. Plan Compliance Matrix

| Plan Item | Status | Evidence | Notes |
|-----------|--------|----------|-------|
| Extract assistant promises | ✅ Complete | `commitment_extractor.py:106` — regex-based extraction, 4 commitment types | |
| Store commitments | ✅ Complete | `sqlite_state_repo.py:120-135` — `commitments` table + 4 CRUD methods | |
| Heartbeat follow-up | ✅ Complete | `commitment_engine.py:42-75` — scans for overdue, updates status | Every 30 min via APScheduler |
| Reuse pending surfacing pattern | ✅ Complete | `chat_message.py:38-43` — injects summary into session context | Follows `pending_*` pattern |
| Cron job registration | ✅ Complete | `jobs.yaml` + `_capabilities.py` | |

---

## 3. Architecture Compliance

| Check | Status | Evidence |
|-------|--------|----------|
| Domain model in domain layer | ✅ Pass | `commitment.py` in `domain/models/` |
| Services in application layer | ✅ Pass | `commitment_extractor.py` + `commitment_engine.py` in `application/services/` |
| Persistence in infrastructure | ✅ Pass | `commitments` table in `sqlite_state_repo.py` |
| Dependency direction | ✅ Pass | All arrows point inward |
| Cron integration follows existing pattern | ✅ Pass | Matches `opportunity_scan`, `kg_consolidation` registrations |
| Duck-typing dependency | ⚠️ See §4.3 | Engine relies on repo method names, not port interface |

### Layer diagram

```
Chat Flow (interfaces)
  └── chat_message.py — injects pending summary on session start

save_session (infrastructure)
  └── extracts commitments from MessageEvents → saves to `commitments` table

CommitmentEngine (application)
  └── heartbeat() — called by APScheduler every 30 min
  └── get_pending_summary() — called by chat flow
```

---

## 4. Code Quality Findings

### 4.1 Audit fix: Blocking — extraction was a dead code path (RESOLVED)

**Original:** `extract_commitments` had zero production callers. The only callers were in tests.

**Fix:** Added extraction to `SQLiteStateRepository.save_session()` — iterates session events, extracts commitments from assistant `MessageEvent`s, calls `save_commitment()` for each. Wrapped in try/except for non-fatal failure.

### 4.2 Audit fix: Blocking — surfacing was a dead code path (RESOLVED)

**Original:** `get_pending_summary` had zero production callers.

**Fix:** Injected into `ChatMessageState.execute()` — when a `state_repo` is available, calls `get_pending_summary()` and prepends the result to the user prompt.

### 4.3 Audit fix: Blocking — timezone mismatch (RESOLVED)

**Original:** `update_commitment_status` used `datetime.utcnow()` (naive) while domain model used `datetime.now(timezone.utc)` (aware). Comparison would raise `TypeError`.

**Fix:** Changed both `update_commitment_status` calls to use `datetime.now(timezone.utc)`.

### 4.4 Audit fix: Should-fix — dead `_TEMPORAL_PATTERNS` list (RESOLVED)

Removed the unused 14-line `_TEMPORAL_PATTERNS` list that duplicated patterns already inline in `_parse_due_at`.

### 4.5 Observation: Port interface gap

Commitment CRUD methods (`save_commitment`, etc.) are defined on `SQLiteStateRepository` but absent from `StateRepositoryPort`. The `CommitmentEngine` relies on duck-typing. The existing `pending_opportunities` methods have the same pattern — suggesting this is established convention for this codebase, not an oversight.

### 4.6 Observation: `commitment_type` captured but not stored

The extractor captures `commitment_type` ("follow_up", "monitor", "notify", "investigate") from the regex match but only uses it for logging. Adding a field to the `Commitment` model would enable richer surfacing (e.g., "You have 2 overdue follow-ups and 1 monitor"). Deferred to follow-up.

---

## 5. Testing & Coverage

| Suite | Tests | Status |
|-------|-------|--------|
| `test_commitment.py` | 20 | 20 passed |
| `test_error_classifier.py` | 38 | 38 passed |
| `test_error_classifier_status_codes.py` | 12 | 12 passed |
| `test_approval_policy.py` | 17 | 17 passed |

### Coverage

| Concern | Tests |
|---------|-------|
| Extraction — 4 commitment types | 5 (follow-up, monitor, notify, investigate, circle-back) |
| Extraction — temporal parsing | 2 (in X time, tomorrow) |
| Extraction — edge cases | 2 (no commitments, empty text) |
| Extraction — metadata | 3 (context, session_id, status) |
| Heartbeat — overdue detection | 1 |
| Heartbeat — non-overdue no-op | 1 |
| Heartbeat — error handling | 1 |
| Surfacing — overdue summary | 1 |
| Surfacing — pending summary | 1 |
| Surfacing — empty/no-op | 1 |
| Surfacing — error handling | 1 |

---

## 6. Risk & Regression Analysis

| Risk | Status | Mitigation |
|------|--------|------------|
| Extraction called but no DB available (save_session called without connection pool) | ✅ Safe | Wrapped in try/except; logs DEBUG |
| Surfacing fails during chat flow | ✅ Safe | Wrapped in try/except; prompt unchanged |
| Timezone mismatch on comparison | ✅ Resolved | All datetimes now `timezone.utc`-aware |
| `MessageEvent` doesn't have `event_id` attribute | ✅ Safe | `getattr(event, 'event_id', None)` with default |
| `state_repo` might not have commitment methods | ✅ Safe | `get_pending_commitments` gated by `hasattr` check |

---

## 7. Required Corrections

| Severity | File | Issue | Status |
|----------|------|-------|--------|
| 🔴 Blocking | `commitment_extractor.py` | `extract_commitments` never called in production | ✅ Fixed — wired in `save_session` |
| 🔴 Blocking | `commitment_engine.py` | `get_pending_summary` never called | ✅ Fixed — wired in `chat_message.py` |
| 🔴 Blocking | `sqlite_state_repo.py:623,628` | `datetime.utcnow()` vs aware datetimes | ✅ Fixed |
| 🔴 Blocking | `commitment_extractor.py:43-50` | Dead `_TEMPORAL_PATTERNS` list | ✅ Removed |
| 🟡 Should-fix | `state_repo_port.py` | CRUD methods not in port interface | Deferred — matches existing `pending_opportunities` pattern |
| 🟡 Should-fix | `commitment.py` | `commitment_type` not stored on model | Deferred to follow-up |

---

## 8. Final Verdict

### 🟢 APPROVED

All 4 blocking issues resolved during audit. The commitments system is now wired end-to-end: extraction in `save_session`, heartbeat via APScheduler, surfacing via `chat_message.py`. 87 tests pass with zero regressions.
