# Agentic Design Patterns (Gulli) → weebot Value Analysis

**Source:** `Papers/Agentic-Design-Patterns.pdf` / `Agentic-Design-Patterns-main/Agentic_Design_Patterns_Complete.pdf`
Antonio Gulli, 458pp, 21 chapters + 7 appendices. Full text extracted and read (chapter overviews, use-cases, "At a Glance", "Key Takeaways", conclusions). Framework code examples (LangChain/LangGraph/ADK) skipped — not portable to weebot's Clean Architecture.

**Date:** 2026-07-29
**Method:** book digest → per-chapter pattern extraction → weebot capability verification by **reading source files** (not grep/docstrings), per `audit_method_lesson`.

---

## 1. Verdict

The book is a **catalog, not a frontier paper**. weebot already implements 17 of its 21 patterns at equal or greater depth. Its value to weebot is therefore *not* "here are new capabilities" — it is:

1. **A completeness checklist** that exposes 4 concrete gaps.
2. **Two genuinely additive ideas** weebot does not have in any form: *ground-truth trajectory evaluation* (Ch19) and the *contractor model* (Ch19).
3. **One dead feature it forces you to confront**: weebot's A2A implementation is a stub that reports success without doing anything.

Net: ~4 actionable items, one of which (`delegate_task`) is a live correctness bug.

---

## 2. Coverage matrix

| Ch | Pattern | weebot | Evidence (verified by reading) |
|----|---------|--------|--------------------------------|
| 1 | Prompt Chaining | ✅ exceeds | `application/flows/plan_act_flow.py` (45KB state machine), `step_pipeline_orchestrator.py` |
| 2 | Routing | ✅ exceeds | `flow_router.py`, `semantic_task_router.py`, `keyword_task_router.py`, `task_model_router.py`, `services/routing/` — LLM, embedding **and** rule-based, all three variants the book names |
| 3 | Parallelization | ✅ exceeds | `parallel_planner.py`, `core/adaptive_concurrency.py`, `domain/models/swarm.py`, `dispatch_parallel_tasks` |
| 4 | Reflection | ✅ exceeds | Dedicated flow states `critiquing.py`, `reviewing.py`, `verifying.py` (29KB), `meta_critic.py`, `plan_critic.py`, `code_reviewer_service.py`, `chain_of_verification.py`. Book's Producer–Critic split is realised as separate states, not just prompts |
| 5 | Tool Use | ✅ exceeds | 50 tool modules, `tool_call_repair.py`, `composite_tool_builder.py`, `native_tool_retrieval_service.py` |
| 6 | Planning | ✅ exceeds | `agents/planner.py`, `flows/workflow_planner.py`, `plan_merger.py`, `plan_history.py`, `domain/services/plan_novelty.py`, `plan_template_cache.py` |
| 7 | Multi-Agent | ✅ | `hyper_agent.py`, `synthesizer_agent.py`, `tools/debate.py` (3 perspectives + reconciler), swarm dispatch |
| 8 | Memory | ✅ exceeds | `working_memory.py`, `session_memory.py`, `memory_lifecycle_service.py`, `memory_compactor.py`, `memory_archivist.py`, `selective_erasure.py`, `memory_dedup.py`, `knowledge_graph.py` (22KB), `vector_store_port.py` |
| 9 | Learning & Adaptation | ✅ exceeds | `self_improver.py`, `meta_self_improver.py`, `autonomous_learning.py`, `behavioral_learner.py`, `strategy_adaptation.py`, `evolution_tracker.py`, `thompson_sampler.py`, `parent_selector.py`. **Book's SICA case study (archive → pick best past version → self-modify) is already surpassed** by `ParentSelector`'s novelty-biased DGM-H formula `score × 1/(1+children)` |
| 10 | MCP | ✅ exceeds | Both directions: `weebot/mcp/` (server), `infrastructure/mcp/` (client), `mcp_tool_registry_bridge.py` (15KB), `mcp_sampling_handler.py`, `mcp_scope.py` |
| 11 | Goal Setting & **Monitoring** | ⚠️ **partial** | `agents/goal_agent.py` decomposes into `SubGoal`s — but emits no measurable success criteria. `step_evaluator.py` scores steps against `plan.title`; there is no goal-level completion monitor |
| 12 | Exception Handling & Recovery | ✅ exceeds | `circuit_breaker.py` (20KB), `error_classifier.py`, `error_system_*.py` (3 modules), `model_health.py`, `flows/states/updating.py` (replan-on-failure) |
| 13 | Human-in-the-Loop | ✅ exceeds | `core/approval.py` (14KB), `approval_policy.py` (13KB), `flows/states/plan_review.py`, `intent_review_service.py`, `domain/services/human_interaction.py` |
| 14 | Knowledge Retrieval (RAG) | ✅ exceeds | `multi_source_research.py` (23KB), `source_credibility_assessment.py` (26KB), `knowledge_graph.py` (= book's GraphRAG), `semantic_skill_retriever.py`, `reranking_skill_retriever.py`, `bm25_skill_retriever.py`. Book's "Agentic RAG" = weebot's `truth_binder.py` + credibility scoring |
| 15 | Inter-Agent Comms (A2A) | ❌ **stub / broken** | See §3.1 |
| 16 | Resource-Aware Optimization | ✅ exceeds | `core/model_cascade_config.py` (22KB), `model_cascade_tracker.py`, `task_model_router.py`, `role_model_selector.py`, `token_budget_monitor.py`, `step_budget.py`, `tool_result_cache.py`, `adaptive_concurrency.py` |
| 17 | Reasoning Techniques | ✅ mostly | `tree_of_thoughts_scorer.py`, `core/search_tree.py`, `chain_of_verification.py`, `verbalized_sampler.py`, `premortem_analyzer.py`, `tools/debate.py`. Missing: MASS topology optimization, Graph-of-Debates (§4.6/4.7) |
| 18 | Guardrails / Safety | ✅ **far exceeds** | `bash_guard.py` (23KB, 4-tier), `egress_guard.py`, `trust_boundary.py` (non-spoofable untrusted-content fencing incl. `mcp__*` passthrough), `secret_redaction.py`, `credential_sanitizer.py`, `capability_gate.py`, `harness_safety_gate.py`, `skill_security_scanner.py`. weebot's injection defence is materially ahead of the book |
| 19 | Evaluation & Monitoring | ⚠️ **weakest area** | See §3.2 and §3.3 |
| 20 | Prioritization | ⚠️ **partial** | See §3.4 |
| 21 | Exploration & Discovery | ✅ | `agents/dreamer.py`, `opportunity_engine.py`, `idea_gate.py`, `domain/models/idea_contract.py`, intent/main review gates |
| ApA | Advanced prompting | ✅ | `prompt_registry.py`, `harness_prompt_assembler.py`, `templates/` (19 modules) |
| ApB | GUI / real-world interaction | ✅ | `infrastructure/browser/`, `osworld/`, `tools/desktop_a11y.py`, `interfaces/windows/` |
| ApE/ApG | CLI agents / coding-agent teams | ✅ | `cli/commands/agents.py` — personas + divisions + `sync-claude` |

---

## 3. The four real gaps

### 3.1 A2A is a stub that lies about success — **fix or delete**

`weebot/core/agent_registry.py` defines `AgentCard` + `AgentRegistry` exactly matching the book's Ch15 shape (name, capabilities, version, description, endpoint). It is consumed by exactly one caller.

`weebot/tools/delegate_task.py:21`:
```python
_registry: AgentRegistry = AgentRegistry()   # "populated at startup by DI container"
```

Verified across the whole repo: **nothing ever calls `register()` on this registry.** No DI wiring, no factory, no startup hook. Consequences:

- `delegate_task` always takes the `if not agents:` branch → returns `"No registered agent provides capability 'X'"` for every capability it advertises in its own tool description.
- Even on the success path (`delegate_task.py:78-86`) it **never invokes the delegated agent**. It returns `f"Delegated '{task}' to {agent.name}"` with no execution. If the registry were populated, the tool would report success while doing nothing — a silent-failure class defect the model would take at face value.

The registry is also unrelated to `weebot/agents/registry.py` (the real persona registry used by `cli/commands/agents.py`), which already holds the persona/division data an Agent Card should describe. Two registries, one real, one decorative.

**Recommendation:** wire `AgentCard`s from the persona registry at DI time and make `execute()` actually dispatch through the sub-agent factory (`sub_agent_factory_port.py` already exists) — or delete `delegate_task` + `core/agent_registry.py`. Do not leave it advertising a capability it does not have.

### 3.2 EvalRunner exists and is wired to nothing

`weebot/application/eval/` contains a complete, well-formed evaluation framework: `EvalRunner` (task bank → target → judge → aggregated `EvalReport` with per-criterion breakdown), `ModelJudge` (LLM-as-judge, 0–10 per criterion, JSON), `ScoreJudge` (exact/substring/regex).

Repo-wide search for `EvalRunner`: **tests only** (`tests/unit/tools/test_eval_runner.py`) plus two architecture-fitness assertions. There is no `cli/commands/eval.py`, no flow, no scheduled job. The optimizer path uses a different, harness-specific stack (`application/harness/scorer.py`, `regression_gate.py`, `regression_suite.py`, `staged_evaluator.py`, `evaluator_selector.py`) that is not reusable for "how good is weebot at task X".

This is the same failure mode recorded in `hermes_v019_study_2026-07`: weebot's constraint is unwired code, not missing capability. Ch19 is the chapter that names the cost.

### 3.3 No trajectory evaluation against a ground-truth path — **the single most additive idea in the book**

Ch19, verbatim on the mechanism:

> "The agent's actual actions are compared to this expected, or ground truth, trajectory to identify errors and inefficiencies. Comparison methods include exact match (requiring a perfect match to the ideal sequence), in-order match (correct actions in order, allowing extra steps), any-order match (correct actions in any order, allowing extra steps), precision (measuring the relevance of predicted actions), recall…"

weebot has every input this needs and none of the comparison:

- `trajectory_builder.py`, `trajectory_exporter.py` (session events → JSONL), `domain/models/trajectory.py`, `trajectory_repository_port.py` — capture is solved.
- `trajectory_monitor.py` — verified by reading: it is a **runtime degeneracy detector** (repetition, semantic loop, stagnation, budget hotspot, terminal, cross-step failure accumulation). Excellent at what it does. It has no notion of an *expected* trajectory and does no offline scoring.
- `ground_truth` appears in exactly two places (`evaluator_selector.py:108`, `skill_opt_flow.py:381`) and both are **evaluator-calibration scores**, not reference trajectories.

So weebot can tell you *the agent is looping*. It cannot tell you *the agent solved it, but took 11 steps where 4 were correct, chose `advanced_browser` where `web_search` was right, and never called `verify`*. That is precisely the signal `self_improver`, `strategy_adaptation` and `harness_opt_flow` are starved of — they currently optimize against artifact scores, not path quality.

The book also supplies the **evalset** file format worth copying: multiple sessions, each with turns containing user query, *expected tool use*, intermediate responses, and a reference final response.

### 3.4 Prioritization is a bare integer

Ch20's model: criteria definition (**urgency, importance, dependencies, resource availability, cost/benefit, user preference**) → task evaluation against criteria → selection logic → **dynamic re-prioritization** as circumstances change.

weebot has:
- `TaskQueuePort.enqueue(..., priority: int = 5)` — caller-supplied constant, sorted by `QueuedSession(order=True)`. `task_runner.py:143` passes it straight through. No scoring, no re-ranking, no dependency awareness.
- `SubGoal.priority: 0|1|2` — assigned by the LLM in `goal_agent.py`'s prompt, then **never read** for ordering (`SwarmSpec` execution is concurrency-bounded, not priority-ordered).
- `IdeaContract.heat_score` (`urgency × novelty × confidence`) — the *only* real multi-criteria priority score in the codebase, and it is scoped to the Dreamer idea pipeline.

Notably `core/dependency_graph.py` (15KB) already exists, so dependency-aware ordering is nearly free.

---

## 4. Recommendations, ranked by value/effort

### R1 — Trajectory evaluation harness (highest value)
Add `application/eval/trajectory_scorer.py` implementing the five Ch19 comparison methods (exact / in-order / any-order match, precision, recall) over the existing `Trajectory` model. Add an evalset loader (`tests/fixtures/evalsets/*.json`) using the book's schema: session → turns → `{query, expected_tools, reference_response}`.
**Then feed the trajectory score into `harness_metric_scorer.py`** so the self-improvement loop optimizes path quality, not just artifact quality. This closes the loop `code_as_harness_analysis` already flagged as open.

### R2 — Wire EvalRunner: `python -m cli.main eval run <evalset>`
Small: `cli/commands/eval.py` + factory wiring. Composes `EvalRunner` + `ModelJudge` + R1's trajectory scorer. Gives weebot the A/B-testing and drift-detection use cases from Ch19 that it currently cannot perform. Register as a scheduled job in `scheduling/default_jobs.py` for drift detection.

### R3 — Fix or remove `delegate_task` (correctness, not enhancement)
As §3.1. Silent-failure defect; the tool currently advertises delegation it never performs.

### R4 — Contractor model for high-stakes tasks (Ch19, four pillars)
The book's strongest architectural idea, and weebot is unusually well-positioned for it because the enforcement states already exist:

| Pillar | Implementation in weebot |
|--------|--------------------------|
| Formalized Contract — deliverables, specs, acceptable sources, scope, expected cost/time, objectively verifiable | New `domain/models/task_contract.py`. Feed from `constraint_extractor.py` (already extracts safety/negative/positive constraints) + `PlannerAgent` |
| Negotiation & feedback lifecycle | `flows/states/plan_review.py` already does human review — extend to let the agent counter-propose terms |
| Self-validation against contract before delivery | `flows/states/verifying.py` (29KB) + `product_gate.py` — check deliverables against the contract rather than a free-text goal |
| Hierarchical subcontracts | `plan_merger.py` + `SwarmSpec` — each sub-goal gets its own contract |

This also fixes gap §3.4's root cause and gap 11: a contract with measurable acceptance criteria *is* a SMART goal, and `verifying` becomes the monitor.

### R5 — Prioritization service (Ch20)
`application/services/task_prioritizer.py`: score = f(urgency, importance, dependency-depth from `dependency_graph.py`, resource availability, cost/benefit). Replace the caller-supplied int in `TaskQueuePort.enqueue`, and honour `SubGoal.priority` in swarm dispatch. Add a re-prioritization hook on new-event arrival.

### R6 — Graph of Debates (Ch17)
`tools/debate.py` is a fixed 3-perspective fan-out + single reconciler. GoD models arguments as nodes with `supports`/`refutes` edges, concluding by finding the best-supported cluster. weebot already has `knowledge_graph.py` — this is a graph-backed upgrade to an existing tool, not new infrastructure.

### R7 — MASS topology optimization (Ch17, advanced)
`harness_opt_flow.py` / `skill_opt_flow.py` optimize **prompts**. MASS adds block-level prompt optimization → topology optimization (who talks to whom) → workflow-level joint optimization. The topology axis is genuinely absent from weebot. Highest effort, most speculative — treat as research, not roadmap.

---

## 5. What to ignore

- **Ch1–8, 10, 12–14, 16, 18** — weebot meets or exceeds all of these. No action.
- **All framework code examples** — LangChain/LangGraph/ADK/CrewAI. weebot's ports-and-adapters layout is a better fit than any of them; porting would be a regression.
- **Appendix C/D** (framework survey, AgentSpace) — vendor material, no transferable content.
- **Appendix F** (LLMs describing their own reasoning) — anecdotal.
- **Ch9's SICA** — already surpassed by `parent_selector.py`.

---

## 6. One-line summary

weebot doesn't need this book's patterns; it needs this book's **Chapter 19** — trajectory-level evaluation and the contractor model — plus the honesty check that `delegate_task` is a stub.
