# "Code as Agent Harness" → Value Analysis for weebot

**Paper:** *Code as Agent Harness: Toward Executable, Verifiable, and Stateful Agent Systems* (UIUC / Meta / Stanford, arXiv:2605.18747v1, May 2026).
**Repo of curated works:** https://github.com/YennNing/Awesome-Code-as-Agent-Harness-Papers
**Analyzed:** 2026-06-15 against weebot @ branch `master`.

---

## TL;DR

weebot **is** a code-as-agent-harness system in exactly the sense the paper formalizes. The
paper's central thesis — *code is not the output, it is the executable/inspectable/stateful
medium through which agents reason, act, verify, and coordinate* — is already weebot's
operating model. The paper therefore delivers value in two ways:

1. **Validation + vocabulary** for an architecture that is currently rich but under-named.
   weebot already implements the Plan-Execute-Verify (PEV) loop, deep telemetry, an Evolution
   Agent, governed harness mutation, and a change-contract model. The paper gives these a
   shared conceptual frame and a literature anchor.
2. **A precise gap list** drawn from the paper's *Open Problems* (§5.2). These map onto ~6
   concrete, high-leverage improvements — not greenfield features, but closing loops and
   tightening contracts in subsystems weebot already owns.

The honest headline: weebot is **further along than most systems the survey cites**. The
opportunity is *consolidation and loop-closing*, not reinvention.

---

## Part 1 — The three-layer mapping (paper → weebot)

The paper organizes the field into three layers. weebot has implementations at every layer.

### §2 Harness Interface (code for reasoning / acting / environment)
| Paper concept | weebot implementation |
|---|---|
| Code for reasoning (program-delegated, iterative code-grounded) | `StructuredExecutorAgent`, tool-call loop |
| Code for acting (grounded skill selection, policies) | `ToolCollection`, `bash_tool`, skill stores |
| Code for environment (program state, traces, evaluation envs) | `sqlite_state_repo`, `sqlite_knowledge_graph`, event store |

### §3 Harness Mechanisms (planning / memory / tools / control / optimization)
| Paper mechanism | weebot implementation |
|---|---|
| **Planning** — linear / structure-grounded / search / orchestration | `PlannerAgent`; `dependency_graph.py` + `knowledge_graph`; `plan_history` + undo/redo + `PlanStuckError` diversification; `workflow_orchestrator`, `hyper_agent_flow` |
| **Memory** — working / semantic / experiential / long-term / multi-agent / compaction | `MemoryCompactor`, `ContextSwitcher`; `sqlite_knowledge_graph`, `fts5_search`; `trajectory_repo`, `strategy_store`, `skill_store`, `retention_agent`, `dreamer`; `filesystem_memory`, `sqlite_summary_repo` |
| **Tool use** — function / environment / verification / workflow | `tool_registry`, `bash_tool`, `code_reviewer`, `workflow_orchestrator` |
| **PEV control loop** (§3.4) | `PlanActFlow` state machine: `Planning → Executing → Verifying → Reviewing/Critiquing → Updating → Summarizing → Completed` |
| **Static analysis sensors** | `code_reviewer_service`, `truth_binder` |
| **Sandboxed execution** | `sandbox_backend_adapter`, `infrastructure/sandbox/docker_linux.py` |
| **Permissioned state transition** | `bash_guard` (4-tier risk), `approval_policy`, `capability_gate` |
| **Verification via deterministic sensors** | `VerifyingState` (Chain-of-Verification), `_gate_sweep`, `_gate_artifact_verification` |
| **HITL gates** | `approval.py`, `plan_review` state, `WaitForUserEvent` |
| **Agentic Harness Engineering / Evolution Agent (§3.5)** | `harness_opt_flow`, `harness_generation_flow`, `skill_opt_flow`, `optimizer_agent`, `layer_diagnostics_agent`, `layer_editor_agent` |
| **Deep telemetry as optimization substrate** | `workflow_tracer`, `behavior_tracker`, `structured_logger`, `meta_improvement_log` (append-only, rollback-capable) |
| **Governed harness mutation (change contract)** | `HarnessEdit` (target_surface, targeted_mechanism, expected_effect, regression_risks); `RegressionGate`; `HarnessSafetyGate`; held-in/held-out task splits |

### §4 Scaling the Harness (multi-agent)
| Paper concept | weebot implementation |
|---|---|
| Role specialization, orchestration topologies | `hyper_agent`, `hyper_agent_flow`, `sub_agent_factory`, `workflow_orchestrator` |
| Shared substrate (repository / blackboard) | `sqlite_knowledge_graph`, shared state repo |

**Conclusion of Part 1:** Nearly every box in the paper's taxonomy (Figures 1, 4, 8, 9) is
already occupied in weebot. The most remarkable convergence is §3.5: the paper's *Evolution
Agent* ("observe telemetry → diagnose failure → propose harness revision → evaluate on
held-out → promote only non-regressing changes") is implemented almost verbatim by
`HarnessOptFlow` + `RegressionGate` + `HarnessEdit`.

---

## Part 2 — The genuine gaps (from §5.2 Open Problems)

These are the places where the paper offers value weebot has **not** fully captured. Each is
grounded in a specific code observation.

### Gap 1 — Close the experiential loop: feed the misalignment journal into the Evolution Agent
**Paper:** §3.2.3 (experiential memory: *quality of stored experience matters more than scale*;
MemGovern), §3.5.2 (Evolution Agent consumes telemetry **including human interventions**).
**Observation:** `MisalignmentJournal` records the **highest-quality failure signal available —
direct user corrections** — at `plan_act_flow.py`, `executing.py`, `planning.py`. But
`HarnessOptFlow._mine_failure_patterns()` mines **only** `trajectory_repo` failure clusters.
The journal is written, never read back into optimization (`harness_prompt_assembler.py`
references "misalignment" only in a code comment). Two separate failure stores exist; the
richest one is orphaned.
**Value:** Route `MisalignmentEntry` records into the Evolution Agent's evidence mining.
User corrections are exactly the "curated, quality-controlled experiential memory" the paper
says outperforms raw logs. Highest impact / lowest effort.

### Gap 2 — Evidence bundles with explicit scope + uncertainty on every verified action
**Paper:** §5.2.2 — *"every accepted action should carry an evidence bundle: the checks run,
the assumptions preserved, the untested regions, and the remaining risks… each artifact should
declare what it verifies, what it cannot verify, and what confidence it provides."* This
matters specifically for self-evolving harnesses: *"if the verifier is weak, the agent will
learn to optimize against the wrong signal."*
**Observation:** `VerifyingState` produces strong but **binary** signals — `_gate_sweep`
returns a list of failed gate names; CoVe returns consistent/inconsistent; `EvidenceBundle`
today aggregates *failure clusters*, not *per-action verification provenance*. There is no
scope/confidence/residual-risk metadata attached to a passed action.
**Value:** Extend the verification layer so each accepted step carries an evidence record
(what was checked, what was *not* checked, confidence, residual risk). This both improves
auditability (§5.2.1 replayability) and protects the Evolution Agent's reward signal from
oracle-gaming (§5.2.2).

### Gap 3 — Unify the permission surfaces into one context-sensitive capability model
**Paper:** §3.4.3 + §5.2.5 — permissions should be a **multi-tier capability model**
(read-only → sandbox-edit → full-access) that depends *"not only on tool identity, but also on
arguments, environment state, data sensitivity, and expected side effects."* HITL approvals
should become **durable harness state** that updates escalation policy, not one-off prompts.
**Observation:** weebot has **three overlapping but disconnected** permission mechanisms:
- `BashGuard` — command-pattern risk (SAFE/SUSPICIOUS/DANGEROUS/BLOCKED), destructiveness only.
- `ExecApprovalPolicy` — command-pattern approval (AUTO/ASK/DENY).
- `CapabilityGate` — tier per *skill manifest* (PUBLIC/CONTROLLED/RESTRICTED/PRIVILEGED), keyed
  to *user presence / operator token*, with a manifest-based `simulate()`.

None of them keys on **what the action touches** (read vs write vs network vs credentials vs
deploy) as a function of *arguments + environment + data sensitivity*. `CapabilityGate.simulate()`
is the closest to the paper's "side-effect prediction" but operates on manifests, not live args.
**Value:** Converge these into one capability gate keyed to *action semantics*, and persist
approvals/denials as durable policy state (so an approval teaches future escalation). This is
the paper's "executable accountability" — a safety layer that filters, vetoes, escalates, and
records before actions reach the world.

### Gap 4 — Make the RegressionGate real: harness-level metrics + replay evaluation
**Paper:** §5.2.1 proposes *harness-level metrics* beyond task success — trajectory efficiency,
verification strength, recovery ability, state consistency, safety compliance, replayability —
and §3.5.1 stresses **replay-based** comparison across harness versions.
**Observation:** `RegressionGate` **defaults to an always-accept stub** when no task_runner is
supplied (`harness_opt_flow.py:102`), and held-in evaluation is explicitly marked *"deferred to
Phase 4"* (`harness_opt_flow.py:136`). The machinery exists; the held-in/held-out task suites
and the metric definitions are not yet populated. Without them, governed mutation can promote
on weak evidence — precisely the §5.2.3 regression risk.
**Value:** Define a small held-out regression suite + the six harness-level metrics, and wire
them as the gate's acceptance signal. This converts the Evolution Agent from "structurally
present" to "evidence-gated", satisfying §5.2.3's *evidence-carrying harness evolution*.

### Gap 5 — Transactional shared state for the multi-agent path (HyperAgent)
**Paper:** §5.2.4 — multi-agent coordination needs **transactional shared program state**:
each action declares its *read set, write set, assumptions, version dependencies, verifier
obligations*; conflicts resolved semantically. §4.3 + SyncMind formalize **belief-state
divergence** `|B_k − S_k|` as the root cause of silent multi-agent failure.
**Observation:** weebot's multi-agent flows (`hyper_agent_flow`, `sub_agent_factory`) coordinate
through shared state but there is no explicit read-set/write-set/assumption contract per agent
action, and no belief-divergence detector. This is the paper's "implicit-harness-state
constraint" — fine for simple tasks, brittle under parallel edits.
**Value:** When multi-agent work is exercised in earnest, add a lightweight transaction record
(read/write set + assumptions) and a divergence check before merge. Lower priority unless the
HyperAgent path is heavily used.

### Gap 6 — Unify the static and execution views of the substrate
**Paper:** §4.3.1 — the deepest harness integrates **repository/structure view** (call graphs,
dependencies) *and* **execution/behavior view** (what runs, what passes) into one queryable
substrate; *"none of the surveyed systems fully unifies both."*
**Observation:** weebot has both halves — `sqlite_knowledge_graph` / `dependency_graph`
(structure) and execution traces / event store (behavior) — but they are separate stores.
**Value:** A unified, queryable substrate answers cross-cutting questions ("does this refactor
break a dependent that the tests don't cover?"). This is a research-grade direction; flag as
forward-looking, not near-term.

---

## Part 3 — Prioritized recommendations

| # | Opportunity | Paper § | Effort | Impact | Notes |
|---|---|---|---|---|---|
| 1 | Mine `MisalignmentJournal` into `HarnessOptFlow` evidence | 3.2.3, 3.5.2 | **Low** | **High** | Orphaned high-quality signal; small wiring change |
| 2 | Evidence bundles (scope/confidence/residual-risk) per verified action | 5.2.2 | Med | High | Protects Evolution Agent's reward from oracle-gaming |
| 3 | Unify BashGuard + ExecApprovalPolicy + CapabilityGate → one arg/env-aware capability model; persist approvals as policy state | 3.4.3, 5.2.5 | Med-High | High | Safety + "executable accountability" |
| 4 | Populate held-out suite + 6 harness-level metrics; replace RegressionGate stub | 5.2.1, 5.2.3, 3.5.1 | Med | High | Turns governed mutation evidence-gated |
| 5 | Transactional read/write-set + belief-divergence check for HyperAgent | 5.2.4, 4.3 | High | Med | Only if multi-agent path is heavily used |
| 6 | Unify structure + execution substrate into one queryable store | 4.3.1 | High | Med | Forward-looking / research-grade |
| 7 | Adopt the paper's vocabulary in docs (PEV loop, deep telemetry, Evolution Agent, governed mutation) | 1, 5.2.7 | **Trivial** | Med | Cheapest consolidation win |

**Recommended first move:** Gap 1 (wire the misalignment journal into the Evolution Agent).
It is the highest impact-to-effort ratio, reuses existing machinery
(`HarnessOptFlow._mine_failure_patterns`, `misalignment_journal_port`), and directly
instantiates the paper's most reusable insight: *curated human-correction experience is the
best fuel for harness self-improvement.*

---

## Part 4 — Conceptual takeaways worth internalizing

- **The harness is a learnable surface, not a fixed wrapper** (§5.1.1, "harness as distillation
  surface"). weebot's Self-Harness (`HarnessConfig`, `ModelAwareHarnessResolver`) already treats
  it this way; the paper validates the bet.
- **Verification strength bounds self-improvement.** Any self-evolving harness is only as safe as
  its weakest oracle (§5.2.2). Invest in evidence/scope before scaling autonomy.
- **Governance is harness state, not a prompt.** Approvals, denials, and risk tiers should be
  durable, auditable, falsifiable records (§5.2.5) — weebot's `meta_improvement_log` is the right
  pattern; extend it to permissions.
- **Topology complexity is a *symptom* of missing shared state** (§4.4). If the multi-agent path
  ever needs elaborate orchestration, prefer fixing the shared substrate first.
