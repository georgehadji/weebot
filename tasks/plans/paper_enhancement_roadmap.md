# Weebot Enhancement Roadmap — Based on "Fundamentals of Building Autonomous LLM Agents"

**Paper:** de Lamo Castrillo et al., arXiv:2510.09244v1, Oct 2025
**Framework:** Perception → Reasoning → Memory → Execution architecture with Multi-Agent experts
**Date:** 2025-07-17

---

## Weebot vs. Paper Architecture — Current State

| Paper Component | Weebot Coverage | Assessment |
|-----------------|----------------|------------|
| Perception — Text-based | LLM native text processing | **Complete** |
| Perception — Multimodal | `browser_inspector`, `screen_capture`, `advanced_browser`, `video_ingest` | **Partial** — missing Set-of-Mark visual grounding |
| Perception — Structured Data | `knowledge_tool`, `video_ingest` (accessibility tree / DOM extraction) | **Partial** |
| Perception — Tool-augmented | `web_search`, `vane_search`, `weather_tool`, 40+ tools | **Complete** |
| Reasoning — Task Decomposition | `planner.py` + `PlanActFlow` state machine | **Partial** — sequential only, no DPPM |
| Reasoning — CoT / ToT | `tree_of_thoughts_scorer.py`, `plan_critic.py` | **Complete** |
| Reasoning — Reflection | `premortem_analyzer.py`, `step_evaluator.py`, `updating_state_critic.py` | **Partial** — no 3-tier failure classification |
| Reasoning — Multi-Agent | `swarm.py`, `debate.py`, `mixture_of_agents.py`, `dispatch_agents.py` | **Partial** — role-based, not expert-based |
| Memory — Long-term (RAG) | `fts_search.py`, `knowledge_graph.py`, `numpy_vector_store.py` | **Complete** |
| Memory — Short-term | `context_manager.py`, `context_compressor.py`, `conversation_compressor.py` | **Complete** |
| Memory — Experience Storage | `trajectory_*`, `episodic_memory.py`, `memory_lifecycle_service.py` | **Partial** — no AWM-like workflow induction |
| Memory — Memory Dedup | `memory_dedup.py` | **Partial** — not applied to trajectories |
| Execution — Tool/API | 40+ tools via `BaseTool` + `BackendPort` | **Complete** |
| Execution — Code Gen | `python_tool.py`, `bash_tool.py` | **Complete** |
| Execution — Browser/GUI | `browser_tool.py`, `advanced_browser.py`, `computer_use.py` | **Complete** |

---

## 8 Enhancement Recommendations

### 1. Agent Workflow Memory (AWM) — PRIORITY: HIGH

**Paper concept:** Agents induce reusable task workflows from past experiences.
Successful and failed trajectories are stored as observation-action pairs. When
the agent encounters a similar task, AWM retrieves the closest workflow and
injects it into the planning context.

**What to build:**
- New module: `weebot/application/services/workflow_memory.py` — extracts
  generalized workflows from completed sessions
- Enhancement to `weebot/application/services/memory_lifecycle_service.py` —
  on session completion, call AWM to induce/update workflow templates
- Enhancement to `weebot/application/agents/planner.py` — on plan generation,
  query AWM for similar task workflows and inject as plan hints
- Storage: SQLite table `workflow_templates` with fields: `task_embedding`
  (vector), `generalized_steps` (JSON), `success_rate` (float), `use_count` (int)

**Paper citation:** §5.3 — "Agent Workflow Memory (AWM) is a method that induces
commonly reused routines from training examples" [59]

**Impact:** Reduces planning latency for recurring task types. Creates an
institutional memory that improves with usage. Directly addresses the paper's
limitation: "agents fail at operations due to lack of sufficient experience."

---

### 2. DPPM — Parallel Subtask Planning with Merge — PRIORITY: HIGH

**Paper concept:** Decompose task → Plan subtasks in parallel → Merge into
coherent global plan. Each subtask generates alternatives considering potential
issues (anticipatory reflection). The merge step explores combinations to ensure
logical consistency.

**What to build:**
- New module: `weebot/application/agents/parallel_planner.py` — generates
  multiple plan candidates per subtask concurrently
- New module: `weebot/application/services/plan_merger.py` — evaluates
  combinations of subtask plans for consistency, selects optimal assembly
- Enhancement to `PlanActFlow` planning state: add a `planning_mode` that can
  switch between sequential and DPPM modes based on task complexity
- Metrics: track plan diversity (how many distinct subtask options generated),
  merge success rate

**Paper citation:** §4.4 — "DPPM proposes splitting the main task into subtasks,
generating multiple parallel plans for each, and merging the best" (Fig. 7)

**Impact:** Higher plan quality through exploration. Reduces single-point-of-failure
planning. Directly addresses the paper's observation that tree-search planning
(ToT, MCTS) outperforms single-path generation for complex tasks.

---

### 3. Three-Tier Failure Classification — PRIORITY: MEDIUM

**Paper concept:** After each action, classify the outcome into one of three tiers:
1. **Successful execution** — continue to next step
2. **Minor error** — adjust and correct (e.g., coordinates slightly off)
3. **Execution failure** — determine if subplan needs revision or full replan

**What to build:**
- Enhancement to `weebot/application/services/step_evaluator.py` — add
  `classify_failure()` returning enum `SUCCESS | MINOR_FIX | SUBPLAN_FAIL | FULL_REPLAN`
- Enhancement to `weebot/application/flows/states/reviewing.py` — route
  based on classification: MINOR_FIX → re-attempt step with corrected params;
  SUBPLAN_FAIL → regenerate subplan; FULL_REPLAN → restart planning
- Enhancement to `weebot/domain/models/event.py` — add `StepFailureClassification`
  field to `StepEvent`

**Paper citation:** §4.4 — "Feedback processed by a reflection mechanism determines
the current scenario: Successful execution, Minor error, or Execution failure"
(and Fig. 7 flowchart)

**Impact:** Reduces unnecessary replanning. Minor coordinate adjustments don't
trigger full plan regeneration. More efficient recovery, fewer tokens wasted.

---

### 4. Multi-Expert Architecture — PRIORITY: MEDIUM

**Paper concept:** A single agent decomposes into specialized "experts" —
Planning Expert, Reflection Expert, Error Handling Expert, Memory Management
Expert, Action Expert, Coding Expert, Security Expert, HCI Expert.

**What to build:**
- Enhancement to `weebot/tools/tool_registry.py` — add expert-level role mappings
  beyond current `DEFAULT_ROLE_MAPPINGS`. Each role becomes an "expert profile"
  with specialized system prompts, allowed tools, and reasoning strategies.
- New module: `weebot/domain/models/expert_profile.py` — `ExpertProfile` with
  fields: `specialization`, `input_schema`, `output_schema`, `boundary_rules`
- Enhancement to `weebot/application/agents/executor/` — support expert
  chaining (Planning Expert → Action Expert → Reflection Expert → Error
  Handling Expert)

**Paper citation:** §4.5–4.6 — "A single agent can be made up of different
specialized experts, each focusing on a distinct aspect of interaction or
reasoning" (Table: Planning Expert, Reflection Expert, Error Handling Expert,
Memory Management Expert, Action Expert, Coding Expert, Security Expert)

**Impact:** More robust execution through specialization. Each expert has narrow,
validated capabilities reducing hallucination and tool misuse. Aligns with weebot's
existing role-based registry — evolution rather than revolution.

---

### 5. Set-of-Mark (SoM) Visual Grounding — PRIORITY: MEDIUM

**Paper concept:** Combine screenshots with bounding-box overlays on interactive
elements, paired with accessibility tree data, to create a rich percept of GUI
environments. Overcomes the "GUI grounding" limitation identified in OSWorld.

**What to build:**
- Enhancement to `weebot/tools/advanced_browser.py` — add `mark_interactive_elements()`
  method that overlays numbered boxes on a screenshot using Playwright's
  `page.accessibility.snapshot()` + `element.boundingBox()`
- New module: `weebot/infrastructure/browser/som_renderer.py` — renders
  numbered bounding boxes on screenshots and returns element→coordinate mapping
- Enhancement to `weebot/tools/browser_inspector.py` — expose SoM output
  alongside accessibility tree in tool results

**Paper citation:** §3.5 — "The agent applies a Set-of-Mark operation using a
visual encoder that draws a box on every interactive element... and stores the
coordinates of each box." §3.2 — "Set-of-Mark prompting... improves grounding"

**Impact:** Directly addresses the paper's identified limitation: "Difficulties in
GUI grounding and operational knowledge." Should improve browser task success
rate by 10–20% (based on OSWorld benchmarks cited in paper).

---

### 6. Memory Duplication Consolidation for Trajectories — PRIORITY: LOW

**Paper concept:** When 5 similar action sequences exist for the same sub-goal,
condense them into a unified plan via LLM and replace the originals.

**What to build:**
- Enhancement to `weebot/core/memory_dedup.py` — add `consolidate_trajectories()`
  that groups similar trajectories by task embedding, then calls an LLM to
  produce a generalized "consensus workflow" from the group
- Enhancement to `weebot/application/services/trajectory_exporter.py` — trigger
  consolidation when stored trajectory count for a task type exceeds threshold
- Storage: replace raw trajectories with consolidated ones, keeping a
  `consolidation_count` and `source_trajectory_ids` for audit

**Paper citation:** §5.4 — "Once this list reaches a size of five, all sequences
are condensed into a unified plan solution using LLMs, and the original sequences
are then replaced"

**Impact:** Prevents memory bloat from repetitive tasks. Creates higher-quality
generalized workflows. Complements enhancement #1 (AWM).

---

### 7. One-Shot Task Learning from Demonstration — PRIORITY: LOW

**Paper concept:** "Learn from one shot" — agent observes a single human
demonstration of a task, then performs it autonomously thereafter.

**What to build:**
- New module: `weebot/application/services/demonstration_recorder.py` —
  records user-guided sessions as `Demonstration` objects (sequence of
  observation→action pairs with human annotations)
- New module: `weebot/application/services/demonstration_generalizer.py` —
  extracts a generalized skill template from a single demonstration, inferring
  which parameters are variable vs fixed
- Enhancement to `weebot/skills/` — auto-register generalized demonstrations
  as skill templates

**Paper citation:** §7.3 — "Investigate how agents can learn to accomplish a
task after just a single demonstration with human help, subsequently performing
it autonomously"

**Impact:** Dramatically reduces the cost of teaching agents new domain-specific
tasks. Complements the existing skills infrastructure.

---

### 8. Parallel Tool Execution with Bounded Concurrency — PRIORITY: LOW

**Paper concept:** The execution system should support concurrent action
invocation when subtasks are independent. Currently weebot's `PlanActFlow`
executes steps sequentially.

**What to build:**
- Enhancement to `weebot/application/flows/states/executing.py` — detect
  independent steps in the current plan and execute them concurrently via
  `asyncio.gather` with a configurable semaphore
- New `parallel_execution_semaphore` in `PlanActFlowConfig` (default: 4)
- Enhancement to `weebot/application/services/tool_result_cache.py` — ensure
  cache is safe under concurrent tool execution (already keyed by SHA-256,
  but verify thread safety)

**Paper citation:** §6.1 — "The most fundamental way LLM agents execute actions
is through structured tool calling... Agents are given predefined functions"

**Impact:** Speedup for tasks with independent steps. The paper's DPPM (enhancement
#2) generates parallel subtask plans — this enhancement executes them in parallel.

---

## Priority & Estimated Effort

| # | Enhancement | Priority | Effort | Dependencies |
|---|------------|----------|--------|--------------|
| 1 | Agent Workflow Memory (AWM) | HIGH | 3 days | `memory_lifecycle_service.py`, `planner.py` |
| 2 | DPPM — Parallel Planning | HIGH | 5 days | `PlanActFlow`, planning state |
| 3 | 3-Tier Failure Classification | MEDIUM | 2 days | `step_evaluator.py`, reviewing state |
| 4 | Multi-Expert Architecture | MEDIUM | 4 days | `tool_registry.py`, executor agents |
| 5 | Set-of-Mark Visual Grounding | MEDIUM | 3 days | `advanced_browser.py`, Playwright |
| 6 | Trajectory Consolidation | LOW | 2 days | `memory_dedup.py`, #1 (AWM) |
| 7 | One-Shot Demonstration | LOW | 5 days | `skills/`, session recording |
| 8 | Parallel Tool Execution | LOW | 2 days | `PlanActFlowConfig`, tool_result_cache |

**Recommended sequence:** 1 → 2 → 3 → 5 → 4 → 6 → 8 → 7

Start with AWM and DPPM (#1, #2) — these directly address the paper's core
findings on memory and reasoning. The 3-tier failure classification (#3) is a
quick win that improves recovery efficiency. Visual grounding (#5) and expert
architecture (#4) are the next layer. Consolidation (#6), parallel execution (#8),
and one-shot learning (#7) are lower impact.
