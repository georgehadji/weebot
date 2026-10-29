---
status: superseded
date: 2026-10-27
note: research for decision D4 of the audit fix plan; how to wire the G8 and G9 code instead of deleting it; findings come from two read-only agents and were not independently re-checked
---

# D4 research: wiring the G8 and G9 code

Question from the owner: instead of deleting groups G8 and G9 of `tasks/plans/audit_2026_10_27_fix_plan.md`, how would each piece be wired in? Two read-only agents mapped the code. They could not reproduce the audit's line counts (G8 about 4.8k, not 6.5k; G9 about 4k, not 4.5k), because the audit plan names no file list. Every claim below is theirs, with the file and line they gave. Nothing here was run.

## Summary

Little of this is worth wiring now. Three pieces are worth wiring (a small step evaluator, an evaluation command, and a repaired skill promotion check). Everything else is either a duplicate of live code, waits on a trigger that does not exist yet, or has no consumer at all.

## G8: self-improvement, evaluation and context compression

Not dead, so not part of any deletion: `SkillOptFlow`, `HarnessOptFlow` and `harness_generation_flow` are live (`cli/commands/flow.py:337`, `run.py:259`, `cli/commands/harness.py`).

Worth wiring, in this order:

1. **Step evaluator (small, about a day).** The hook `progress_gate` exists (`_step_outcome.py:204-206`) and so does its config field (`plan_act_flow_config.py:110`), but nothing builds the evaluator. Register `step_evaluator` in the container and pass it where `_agent_tools.py:70` passes its siblings, behind a new flag. It costs one language-model call per step and fails open by design, flagged `evaluator_failed` (`step_evaluator.py:111-127`). Tests exist (`tests/unit/services/test_step_evaluator.py`).
2. **Evaluation command (small to medium).** Add `cli/commands/eval.py` that runs `EvalRunner` with a judge resolved from the container. It writes nothing and costs only what is run. Needs one command smoke test with a fake judge.
3. **Skill promotion check (medium to large, not small).** The disabled job `skill_promotion_check` (`config/jobs.yaml:6-17`) cannot pass today:
   - `skill_promotion_gate.py:69` reads `.score` from the verification result, but `CoVeResult` has no such field (`chain_of_verification.py:144-163`), so the score is always 0.
   - `skill_promotion_gate.py:84-86` awaits `harness.score(session_events=[], task_result=...)`, but the real scorer is a synchronous class method that takes a `Session` (`harness_metric_scorer.py:38-46`). The call raises, is caught, and scores 0.
   - It never marks a skill trusted or saves it.
   - Chain of verification fails open on unparseable output: `chain_of_verification.py:138-141` returns no inconsistencies, and `verify()` then reports verified (`:218`). This must be fixed first.
   - Procedural skills have few factual claims, so question planning often returns nothing and `verified` is false (`:200-205`). The agent expected most skills to be rejected; it did not run this.
   - A live promotion path already exists: a held-out pass records a use and three uses promote (`validation_handler.py:56-110`). So the gate should only ever veto, never promote.
   - Hook if built: register the callable next to `default_jobs.py:316-334`; the job lists skills through `SkillStorePort` (`skill_store_port.py:23-27`), keeps those with trust `candidate`, runs the gate, then marks trusted, saves, and publishes `SkillPromoted` (`meta_analysis.py:204`), within `MAX_SKILL_PROMOTIONS_PER_RUN` (`config/learning.py:30`). Run one release in dry-run before enabling.
   - Risk: it writes trust without a human, and trusted skills are injected into live runs (`skill.py:287`). Cost is up to about 7 model calls per skill. The second agent advises against building it and notes `agentic_memory_fix_plan.md:595` says not to resurrect this job id.

Not worth wiring:

- Context compression (`lossy_context_compressor`, `context_manager` and related): duplicates the live `MemoryCompactor` (`_plan_act_wiring.py:158`, `default_jobs.py:73`); an earlier plan chose deletion on purpose (`agentic_memory_fix_plan.md:28-35`).
- `ChainOfVerificationService` inside the flow: `VerifyingState` already runs verification (`states/verifying.py:45,66`, flag `cove_enabled`).
- `self_improver`: it has no proposer to call it (bilevel plan, line 179).
- `strategy_*`, `parent_selector`, `skill_variant_store`, `code_quality_signal`, `harness_profile_resolver`, the two layer agents, the benchmark runner and posterior store: no consumer and no plan that names a hook point.

## G9: unwired adapters and verifiers

- **Valkey event bus (`redis_event_bus.py`, `broker_adapter.py`, `subscriber.py`, about 285 lines): premature.** A correct bridge needs five things: serialize events, rebuild them from a type registry (the event union is incomplete, which the agent inferred but did not test), deliver locally first and publish with an origin id while dropping own-origin messages, a reader task with reconnect and backoff, and a decision on whether remote events are journaled. Today it raises instead of sending when connected (`redis_event_bus.py:114-128`). No second process needs shared events: `docker-compose.yml:31-47` runs one API replica, and the UI talks plain HTTP. Whether the chat gateways or `run_mcp.py` run as separate processes was not checked. The recorded intent (`icm_fix_plan.md:383,407`) is to build the bridge only when more than one process needs it.
- **Summary repository (`sqlite_summary_repo.py`, 78 lines): keep, reserved.** Register `SummaryRepositoryPort` beside the knowledge graph (`di/_capabilities.py:33-37`) when phase 5 of the memory plan builds a consumer (`agentic_memory_fix_plan.md:622`).
- **PostgreSQL knowledge graph (`postgresql/knowledge_graph.py`, 241 lines): only inside the Postgres phase.** It has no `delete_by_session_id`, which the session-delete cascade needs (`dependencies.py:39`; SQLite has it at `sqlite_knowledge_graph.py:655`), so wiring it would silently break data deletion. Its default connection string carries `weebot:weebot` credentials (`postgresql/connection.py:18`).
- **Duplicates of live code, delete or leave dead:** `state_verifier` (534 lines) and `identity_verifier` (572; its multi-factor step is unimplemented), duplicating `StepEvidenceAuditor`, `gateway_auth` and `trust_boundary`; `CommandValidator`, a second shell gate beside `BashGuard`; the checkpoint store and scheduler, superseded; three scorers kept unwired on purpose (`di/__init__.py:200-213`); two event subscribers that duplicate `notifications/sse_adapter.py` and `windows_toast.py`.
- **Optional alternatives with no requester:** the Modal sandbox backend, the OpenRouter speech adapter, `legacy_project_adapter`, `tools/validation.py`, `tools/secure_output.py`, `_adapter_base`.
- **Stale documentation to fix whatever is decided:** `docs/SECURITY_MODULE.md:168` says `BashTool` uses `state_verifier`; `bash_tool.py` never references it.
- Not verified by the agent: `mcp_tool_bridge.py` (found by duck typing, no constructor seen), and anything under `weebot/tools/`, which a registry loads, so an import scan cannot see it.

## Suggested decision

Keep, annotated as reserved, only the summary repository and the three Valkey files. Wire the step evaluator and the evaluation command. Repair and dry-run the skill promotion check only if a second veto on skills is wanted. Delete the rest of G8 and G9 in the wave 6 slices, after tagging the commit before each deletion so any piece can be restored.
