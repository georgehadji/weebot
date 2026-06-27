# Dead-Code Audit — `application/services/` — 26 Files with 0 Production Callers

**Scan method:** Full-text search for `weebot.application.services.<module>` across all `weebot/` and `tests/` Python files.
**Total services scanned:** 108
**Dead in production (0 imports from non-test code):** 26

---

## Truly Dead — No Callers Anywhere (including tests)

These 10 files have zero imports across BOTH production and test code.
**Safe to delete** with no side effects.

| # | File | Notes |
|---|------|-------|
| 1 | `action_canonicalizer.py` | No production or test imports found |
| 2 | `complex_task_executor.py` | No production or test imports found |
| 3 | `contract_loader.py` | No production or test imports found |
| 4 | `episodic_memory.py` | No production or test imports found |
| 5 | `information_synthesis.py` | No production or test imports found |
| 6 | `memory_facade.py` | No production or test imports found |
| 7 | `parallel_agent_router.py` | No production or test imports found |
| 8 | `scope_classifier.py` | No production or test imports found |
| 9 | `session_archiver.py` | No production or test imports found |
| 10 | `trajectory_exporter.py` | No production or test imports found |

---

## Has Test Coverage (test files import it) — Verify Before Deletion

These 10 files have no production callers but ARE imported by test files.
Deletion requires also cleaning up the corresponding test file(s).

| # | File | Test File(s) |
|---|------|--------------|
| 11 | `chain_of_verification.py` | `test_hermes_remaining.py` (indirect) |
| 12 | `harness_profile_resolver.py` | `test_harness_phase1_evidence_gate.py` |
| 13 | `mcp_sampling_handler.py` | `test_mcp_sampling.py` |
| 14 | `regression_suite.py` | `test_hermes_remaining.py` |
| 15 | `role_model_selector.py` | `test_role_model_selector.py` |
| 16 | `skill_review_gate.py` | `test_hermes_remaining.py` |
| 17 | `step_evaluator.py` | `test_step_evaluator.py` |
| 18 | `stripe_webhook_handler.py` | `test_stripe_webhook_handler.py` |
| 19 | `suggestion_engine.py` | `test_suggestion_engine.py` |
| 20 | `verbalized_sampler.py` | `test_verbalized_sampler.py` |

---

## Possibly Referenced Dynamically — Verify Before Deletion

These 6 files have no string-based imports but may be loaded via DI container,
dynamic dispatch, or `__init__.py` exports.

| # | File | Risk |
|---|------|------|
| 21 | `fs_permission_checker.py` | Check `container.bind()` calls |
| 22 | `skill_security_scanner.py` | Check skill loader code |
| 23 | `skill_trigger_tester.py` | Check skill dispatch logic |
| 24 | `subagent_telemetry.py` | Check sub-agent construction |
| 25 | `user_modeling.py` | Check profile manager |
| 26 | `chain_of_verification.py` | Check CoVe integration |

---

## Recommended Action

**Phase 1** (immediate): Delete the 10 truly dead files. Estimated: −500 LOC, 0 test changes.
**Phase 2** (verify first): For the 10 with test coverage, check whether tests are meaningful.
  - If test is specific to the service → keep the service (it's test-covered even if unused in production)
  - If test is generic and the service is dead → delete both
**Phase 3** (investigate): For the 6 potentially-dynamic services, check DI wiring before deleting.
