# C4: Domain-Logic Relocation Candidates — 40 Services

**Criteria:** Services in `application/services/` whose only `weebot.*` imports
are from `weebot.domain` (plus stdlib).
**Total candidates:** 40
**Recommended action:** Review each; move if genuinely domain-level logic.

---

## Tier 1: Strong Domain Candidates (8 services — move immediately)

These services contain business logic about domain concepts (commitments,
capabilities, skills, plans) with no application-layer dependencies.

| Service | Rationale |
|---------|-----------|
| `commitment_engine.py` | Manages agent commitments — pure domain concept |
| `commitment_extractor.py` | Extracts commitments from text — domain parsing |
| `continuation_detector.py` | Detects repeated plans — domain state machine logic |
| `plan_novelty.py` | Measures plan uniqueness — domain metric |
| `plan_template_cache.py` | Caches plan templates — domain storage pattern |
| `skill_promotion_gate.py` | Skill lifecycle policy — domain rules |
| `skill_review_gate.py` | Skill review policy — domain rules |
| `skill_trigger_tester.py` | Skill activation rules — domain logic |

---

## Tier 2: Mixed — Could Move but Need Port Abstraction (12 services)

These services reference domain types but also handle cross-cutting concerns
(caching, metrics, filesystem) that may keep them in the application layer.

| Service | Dependency Risk |
|---------|----------------|
| `capability_gate.py` | Domain logic but used by tool_registry — verify callers first |
| `flow_serializer.py` | Domain model serialization — pure logic but called from app layer |
| `harness_metric_scorer.py` | Scorer for harness results — domain if concept lives in domain |
| `harness_prompt_assembler.py` | Assembles prompts from domain instructions — could be domain |
| `harness_safety_gate.py` | Safety rules for harness — domain policy |
| `mcp_sampling_handler.py` | MCP sampling — domain concept |
| `memory_compactor.py` | Memory management rules — domain |
| `plan_history.py` | Plan history tracking — domain |
| `regression_suite.py` | Regression definitions — domain concept |
| `step_result_validator.py` | Step validation rules — domain |
| `suggestion_engine.py` | Suggestion logic — domain |
| `truth_binder.py` | Truth binding — domain concept |

---

## Tier 3: Stdlib-Only (20 services — review individually)

These import nothing from `weebot.*` — they may be pure utility or dead code.

| Service | Best Guess |
|---------|------------|
| `constraint_extractor.py` | Parsing logic — could move to domain/utils/ |
| `language_detector.py` | NLP utility — could be infrastructure |
| `lr_scheduler.py` | Learning rate computation — utility |
| `memory_lifecycle_service.py` | Memory lifecycle — might be dead (0 callers in C1) |
| `nlp_understanding.py` | NLP pipeline — infrastructure |
| `proposal_tracker.py` | Proposal tracking — domain |
| `rule_selector.py` | Rule selection — domain |
| `salience_scorer.py` | Salience scoring — domain |
| `session_search_service.py` | Search — application |
| `staged_evaluator.py` | Evaluation — domain |
| `step_budget.py` | Budget calculation — domain |
| `stripe_webhook_handler.py` | Stripe — infrastructure (third-party integration) |
| `subagent_telemetry.py` | Telemetry — observability |
| `task_model_router.py` | Model routing — application |
| `tool_call_repair.py` | Tool repair — application |
| `user_model_consolidator.py` | User models — domain |
| `user_modeling.py` | User modeling — domain |
| `plan_history.py` | Already listed in Tier 2 |
| `skill_security_scanner.py` | Security scanning — cross-cutting |

---

## Recommended Action

**Immediate move (Tier 1):** 8 services → `domain/services/`. Update all callers.
**Next review (Tier 2):** 12 services — evaluate one by one.
**Deferred (Tier 3):** 20 services — too risky without understanding the actual
business logic. Many are genuinely application-layer despite stdlib-only imports.

**Impact on count:** Moving 8 files from `application/services/` to
`domain/services/` reduces the app-layer count from 98 → 90 while adding
8 files to `domain/services/`. This is a net improvement in architectural
layering even though it doesn't reduce the total file count.
