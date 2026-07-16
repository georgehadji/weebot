# Implementation Plan — "Code as Agent Harness" Enhancements & Fixes

**Companion to:** `tasks/specs/code_as_agent_harness_analysis.md`
**Paper:** *Code as Agent Harness* (arXiv:2605.18747v1).
**Target:** weebot @ `master`. **Drafted:** 2026-06-15.

> **Architecture contract (non-negotiable).** Every change below respects the dependency
> rule `Interfaces → Infrastructure → Application → Domain`, enforced by `.importlinter` and
> the "Architecture Fitness Tests" CI job. New abstract types live in `domain/models` (pure)
> or `application/ports` (abstract); orchestration in `application/services` &
> `application/flows`; I/O in `infrastructure/`; wiring only in `interfaces/factories.py`.
> TDD throughout: write the failing test first, then the minimal implementation, then refactor.
> Keep functions < 50 lines and modules < 800 lines (split when needed).

---

## 0. Scope & sequencing

Seven workstreams, ordered by dependency and value. Phases 1–2 form one shippable increment
(they are co-dependent: the safety backbone + the highest-value evidence source). Phases 3–4
are independent and high-value. Phases 5–6 are forward-looking and gated on real need.

| Phase | Workstream | Gap | Depends on | Effort | Priority |
|------|-----------|-----|-----------|--------|----------|
| 1 | Evidence-gated harness evolution (real `RegressionGate`) | 4 | — | M | **P0 (safety backbone)** |
| 2 | Close the experiential loop (misalignment → Evolution Agent) | 1 | 1 (for safe promotion) | S | **P0 (top value)** |
| 3 | Scoped verification evidence bundles | 2 | — (feeds 1) | M | P1 |
| 4 | Unified capability governance | 3 | — | M-L | P1 (safety) |
| 5 | Transactional shared state (HyperAgent) | 5 | — | L | P2 (on demand) |
| 6 | Unified structure+execution substrate | 6 | 3 | L | P3 (research) |
| 7 | Vocabulary & docs consolidation | 7 | — | XS | P1 (cheap) |

**Cross-cutting (applies to every phase):**
- Add Prometheus metrics under `weebot/infrastructure/observability/metrics.py` for each new gate/loop.
- Add `.importlinter` allow/forbid rules for each new module before writing it.
- Each new domain model is a frozen/immutable Pydantic model; mutate via `model_copy`.
- Each phase ships its own unit + integration tests at ≥ 80% coverage of new code.

---

## Phase 1 — Evidence-gated harness evolution (Gap 4)

**Why first:** §5.2.3 — *"a harness mutation should be treated like a code change to a
safety-critical runtime."* Today `RegressionGate` **auto-accepts when `task_runner is None`**
(`regression_gate.py:107`) and the wired task_runner's oracle is merely *"`flow.run()` did not
raise"* (`harness_opt_flow.py:257`, `{"passed": True}`). That is the weak-oracle failure mode
the paper warns about: the Evolution Agent can promote on noise. Make promotion evidence-gated
before we feed it richer evidence (Phase 2).

### 1.1 Domain layer — `weebot/domain/models/harness_metrics.py` (new)
The paper's six harness-level metrics (§5.2.1) as an immutable model:
```python
class HarnessMetrics(BaseModel):           # frozen
    trajectory_efficiency: float   # tool calls / tokens / wall-clock per solved task
    verification_strength: float   # gate coverage × oracle diversity (from Phase 3)
    recovery_ability: float        # fraction of failures recovered without human
    state_consistency: float       # checkpoint/replay divergence score
    safety_compliance: float       # fraction of actions within permitted tier (from Phase 4)
    replayability: float           # fraction of trajectory reconstructable from logs
    task_pass_rate: float          # the existing scalar, retained
```
Add a `composite(weights)` helper returning a single comparable scalar for the gate.

### 1.2 Application layer
- **`weebot/application/services/harness_metric_scorer.py` (new).**
  `HarnessMetricScorer.score(session, plan, token_usage) -> HarnessMetrics`. Pure computation
  over a finished `Session` + `Plan`. Reuses `VerifyingState` gate results
  (`context.extra["verification_scores"]`, `["gate_failures"]`) already stored on the session.
- **`weebot/application/services/regression_suite.py` (new).**
  `RegressionSuite.load(held_in_path, held_out_path) -> tuple[list[RegressionTask], ...]`.
  A `RegressionTask` (new domain model) is `{id, prompt, oracle}` where `oracle` is a
  deterministic checker (file exists, test passes, expected substring). Replaces the current
  empty `held_in_tasks=[]` defaults.
- **Modify `regression_gate.py`:**
  - Change the `task_runner` contract result dict from `{"passed": bool}` to
    `{"passed": bool, "metrics": HarnessMetrics}`; aggregate metric deltas, not just pass-rate.
  - Replace the `task_runner is None → auto-accept` branch with `task_runner is None → REJECT`
    (fail-closed). Test mode must inject a stub runner explicitly.
  - Acceptance rule unchanged (Δ_in ≥ 0 ∧ Δ_ho ≥ 0 ∧ max > 0) but computed on the composite
    metric, with a configurable `min_held_out_tasks` floor (reject if the suite is too small
    to be meaningful).
- **Modify `harness_opt_flow.py`:** `_make_task_runner._run` scores each task via
  `HarnessMetricScorer` and the `RegressionTask.oracle` instead of `{"passed": True}`.

### 1.3 Infrastructure layer
- `weebot/infrastructure/fixtures/regression/held_in.jsonl` and `held_out.jsonl` — a small,
  curated, version-controlled task suite (start with 5–8 tasks each, drawn from real solved
  sessions). These are the paper's "held-out regression suite" (§5.2.3).
- Metrics: `harness_promotion_total{decision}`, `harness_metric_delta{metric}` counters.

### 1.4 Tests (write first)
- `test_regression_gate_fails_closed_without_runner` — no runner ⇒ `accepted is False`.
- `test_regression_gate_rejects_held_out_regression` — Δ_ho < 0 ⇒ reject.
- `test_harness_metric_scorer_from_session` — known session ⇒ expected metric vector.
- `test_regression_suite_loads_oracles` — suite file ⇒ runnable oracles.
- Update existing `test_self_harness_phase*` for the new fail-closed default.

### 1.5 Risks / rollback
- **Behavior change:** fail-closed default could stop a currently-passing optimization path.
  Mitigate with an explicit `RegressionGate(auto_accept=True)` opt-in for legacy/test callers,
  defaulting to `False`. Rollback = flip the default back; no schema migration.

### 1.6 Acceptance criteria
A harness edit is promoted **only** when the curated suite shows a non-regressing composite
improvement; promotions/rejections emit metrics and a `meta_improvement_log` record.

---

## Phase 2 — Close the experiential loop (Gap 1)

**Why:** §3.2.3 / §3.5.2 — user corrections are the highest-quality experiential signal, and
they are currently **orphaned**: written via `MisalignmentJournalPort.record()` in
`plan_act_flow.py` / `executing.py` / `planning.py`, but `HarnessOptFlow._mine_failure_patterns()`
mines only `trajectory_repo`. Route the journal into the Evolution Agent's evidence.

### 2.1 Domain layer — `weebot/domain/models/misalignment_signature_mapper.py` (new, pure)
Pure mapping `MisalignmentEntry → FailureSignature` (the φ-triple already in
`failure_signature.py`):
- `terminal_cause` ⇐ `entry.symptom` (`user_correction` | `constraint_violation` | `scope_overreach`)
- `agent_behavior` ⇐ classify from `entry.step_description`
- `mechanism` ⇐ classify from `entry.correction_text` (rule-based first; LLM-assisted later)
- `actionability_score` ⇐ **1.0 boost for `user_correction`** (human-labelled = maximally actionable)
No I/O, no LLM in the domain layer — keep the rule-based classifier deterministic and testable.

### 2.2 Application layer
- **Extend `MisalignmentJournalPort`** with one read method for mining (current `get_recent`
  is project-scoped; mining needs lookback + cross-project):
  ```python
  @abstractmethod
  async def get_since(self, lookback_days: int, limit: int = 200) -> list[MisalignmentEntry]: ...
  ```
- **`weebot/application/services/misalignment_miner.py` (new).**
  `MisalignmentMiner.mine(lookback_days) -> list[FailureCluster]`: read entries → map to
  signatures → `FailureCluster.from_signatures()` (existing) grouped by `cluster_key`.
- **Modify `harness_opt_flow.py`:**
  - Inject `misalignment_journal: Optional[MisalignmentJournalPort]` in `__init__`.
  - In `_mine_failure_patterns()`, merge trajectory clusters with misalignment clusters into
    one `EvidenceBundle` (dedupe by `cluster_key`, sum support, keep max actionability).
  - The proposal prompt (`_HARNESS_PROPOSAL_PROMPT`) already consumes clusters — no prompt change.

### 2.3 Infrastructure layer
- Implement `get_since` in `SQLiteMisalignmentJournal` (new `_SELECT_SINCE` query: `WHERE
  created_at >= ? ORDER BY created_at DESC LIMIT ?`). Add an index on `created_at`.

### 2.4 Interfaces layer
- In `weebot/interfaces/factories.py`, pass the existing `SQLiteMisalignmentJournal` instance
  into `HarnessOptFlow(...)` (it is already constructed for `PlanActFlow`).

### 2.5 Tests (write first)
- `test_misalignment_mapper_user_correction_high_actionability`.
- `test_misalignment_miner_clusters_by_signature`.
- `test_harness_opt_merges_misalignment_and_trajectory_evidence`.
- `test_sqlite_misalignment_get_since`.

### 2.6 Risks / rollback
- Low. Journal read is additive; if `misalignment_journal is None`, mining falls back to
  trajectory-only (current behavior). Rollback = stop injecting the journal.

### 2.7 Acceptance criteria
A recorded `user_correction` appears as a high-actionability `FailureCluster` in the next
`HarnessOptFlow` epoch's `EvidenceBundle`, influencing proposal ranking — and is only promoted
through the Phase-1 evidence-gated `RegressionGate`.

---

## Phase 3 — Scoped verification evidence bundles (Gap 2)

**Why:** §5.2.2 — *"every accepted action should carry an evidence bundle: the checks run, the
assumptions preserved, the untested regions, the remaining risks… each artifact declares what
it verifies, what it cannot verify, what confidence it provides."* Today `VerifyingState`
gates are binary (`_gate_sweep -> list[str]`), so the Evolution Agent's reward (Phase 1's
`verification_strength`) has no provenance to measure.

### 3.1 Domain layer — `weebot/domain/models/action_evidence.py` (new, immutable)
> Note: distinct from the cluster-oriented `failure_signature.EvidenceBundle`. Name it
> `ActionEvidence` to avoid collision.
```python
class VerificationCheck(BaseModel):     # one sensor result
    name: str; passed: bool; scope: str          # what it covers
    confidence: float                              # 0..1
    not_covered: list[str] = []                    # explicit blind spots
class ActionEvidence(BaseModel):        # attached to an accepted step
    step_id: str
    checks: list[VerificationCheck]
    residual_risk: str = ""
    @property
    def aggregate_confidence(self) -> float: ...
    @property
    def verification_strength(self) -> float: ...  # consumed by HarnessMetricScorer
```

### 3.2 Application layer
- **New event** `ActionEvidenceEvent(AgentEvent)` in `weebot/domain/models/event.py` (sibling
  of the existing `VerificationEvent`), carrying an `ActionEvidence`.
- **Modify `verifying.py`:** have `_gate_sweep` / `_gate_artifact_verification` build
  `VerificationCheck` objects (each declares scope + what it does *not* check) instead of bare
  strings; emit one `ActionEvidenceEvent` per verified step; keep the legacy `VerificationEvent`
  for backward compat.
- **`HarnessMetricScorer`** (Phase 1.2) reads `ActionEvidence.verification_strength` for its
  `verification_strength` metric — closing the Phase 1 ↔ Phase 3 loop.

### 3.3 Tests
- `test_action_evidence_aggregate_confidence`.
- `test_verifying_state_emits_scoped_evidence`.
- `test_metric_scorer_uses_verification_strength`.

### 3.4 Risks / rollback
- Additive event type; UI/persistence already tolerate unknown event types (verified in
  `_emit`). Gate behavior unchanged — only enriched. Rollback = stop emitting the new event.

---

## Phase 4 — Unified capability governance (Gap 3)

**Why:** §3.4.3 + §5.2.5 — one **context-sensitive** capability model (read-only →
sandbox-edit → full-access) keyed to *arguments, environment, data sensitivity, side effects*;
approvals become **durable harness state**. Today three disconnected mechanisms exist:
`BashGuard` (command-pattern risk), `ExecApprovalPolicy` (command-pattern approval),
`CapabilityGate` (manifest tier keyed to user presence). None keys on action semantics, and
`CapabilityGatePort` is marked **DEPRECATED — no adapter exists**.

### 4.1 Domain layer — `weebot/domain/models/action_capability.py` (new)
```python
class ActionCapability(str, Enum):     # the paper's three tiers
    READ_ONLY = "read_only"            # browse, inspect, static analysis
    SANDBOX_EDIT = "sandbox_edit"      # local patch, test exec, temp deps
    FULL_ACCESS = "full_access"        # network, credentials, deploy, git history
class ActionDescriptor(BaseModel):     # what governance reasons over
    tool_name: str; args: dict; env: dict
    data_sensitivity: str = "low"      # low|pii|secret
class GovernanceDecision(BaseModel):
    capability: ActionCapability; allowed: bool
    requires_human: bool; reason: str; evidence: dict
```

### 4.2 Application layer
- **`weebot/application/ports/action_governor_port.py` (new)** — replaces the deprecated
  `CapabilityGatePort`. `decide(descriptor) -> GovernanceDecision`.
- **`weebot/application/services/action_governor.py` (new)** — the unifying policy. It does
  **not** delete the three existing gates; it *composes* them:
  1. Classify `ActionDescriptor → ActionCapability` (rules on tool+args+env).
  2. Run `BashGuard` for destructive-pattern risk (bash actions).
  3. Run `ExecApprovalPolicy` for approval mode.
  4. Map `data_sensitivity`/capability → required tier, escalate `requires_human`.
  5. Consult the **durable policy store** (see 4.3) for prior approvals of the same signature.
- **`weebot/application/ports/policy_state_port.py` (new)** — persists approvals/denials as
  durable, auditable state (the paper's "approval becomes harness state").

### 4.3 Infrastructure layer
- **`weebot/infrastructure/persistence/sqlite_policy_state.py` (new)** — append-only, mirrors
  the `meta_improvement_log` pattern (id, action_signature, decision, evidence, approver, ts).
  Reuse `credential_sanitizer` before persisting `args`.

### 4.4 Interfaces / wiring
- `bash_tool.py` (and other side-effecting tools) call `ActionGovernor.decide()` at the single
  choke point in `ExecutingState`, replacing direct `BashGuard`/`ExecApprovalPolicy` calls.
  The three legacy modules remain as the governor's internal sensors (no duplicate logic).

### 4.5 Tests
- `test_action_governor_classifies_read_vs_write_vs_network`.
- `test_governor_escalates_on_secret_data_sensitivity`.
- `test_policy_state_persists_and_recalls_approval`.
- `test_governor_blocks_what_bashguard_blocks` (regression parity with current behavior).

### 4.6 Risks / rollback
- **Highest-risk phase** (touches the execution choke point). Land behind a
  `WEEBOT_UNIFIED_GOVERNANCE` flag; when off, fall back to the current direct gate calls.
  Ship parity tests first so the governor is provably ≥ as strict as today before cutover.

---

## Phase 5 — Transactional shared state for HyperAgent (Gap 5)

**Why:** §5.2.4 + SyncMind — multi-agent edits need read-set/write-set/assumption contracts and
belief-divergence detection. Only pursue when the `hyper_agent_flow` path is exercised in
earnest (currently lower-traffic).

### 5.1 Domain — `weebot/domain/models/action_transaction.py` (new)
`ActionTransaction{ agent_id, read_set, write_set, assumptions, version_deps,
verifier_obligations }` + `BeliefDivergence{ agent_belief, ground_truth, delta }`.

### 5.2 Application
- `weebot/application/services/shared_state_coordinator.py` (new): before an agent's write,
  validate its `read_set` versions against current ground truth; on `delta > threshold`, emit a
  re-sync event instead of merging (the paper's `|B_k − S_k|` guard).
- Integrate into `hyper_agent_flow` merge points.

### 5.3 Tests
- `test_transaction_detects_stale_read_set`.
- `test_belief_divergence_blocks_merge`.

### 5.4 Risk
- Scoped to the multi-agent path; no impact on single-agent `PlanActFlow`. Defer until needed.

---

## Phase 6 — Unified structure + execution substrate (Gap 6)

**Why:** §4.3.1 — unify the **structure view** (`sqlite_knowledge_graph` / `dependency_graph`)
and the **execution view** (event store / trajectory traces) into one queryable substrate so
the harness can answer "does this refactor break a dependent the tests don't cover?"
Research-grade; depends on Phase 3 evidence being available.

### 6.1 Approach (spike, not full build)
- `weebot/application/ports/substrate_query_port.py` (new): a read-only façade with typed
  queries spanning both stores (`callers_of`, `tests_covering`, `execution_outcomes_for`).
- Back it first by a thin adapter joining the existing `sqlite_knowledge_graph` and event store
  — **no new write path**; this is a query unification, not a new source of truth.
- Validate value on one concrete question before investing further.

---

## Phase 7 — Vocabulary & docs consolidation (Gap 7)

**Why:** §1, §5.2.7 — cheapest consolidation win. weebot's capabilities are named ad hoc.
Adopt the paper's vocabulary so the architecture is legible and future contributors map code to
literature.

### 7.1 Changes
- Add a "Harness model" section to `weebot/CLAUDE.md` mapping subsystems to the paper's three
  layers + PEV loop + Evolution Agent (reuse the table in the analysis doc).
- Rename internal references where low-risk: the §3.4 loop is the **PEV (Plan-Execute-Verify)
  loop**; `HarnessOptFlow` is the **Evolution Agent**; `HarnessEdit` is the **change contract**.
  Docstrings + comments only — no API renames (avoid churn / import-linter noise).
- Add `docs/harness/GLOSSARY.md` linking each term to its paper section and weebot file.

---

## Appendix A — File manifest (new vs modified)

**New (domain):** `harness_metrics.py`, `misalignment_signature_mapper.py`,
`action_evidence.py`, `action_capability.py`, `action_transaction.py`.
**New (ports):** `action_governor_port.py`, `policy_state_port.py`, `substrate_query_port.py`;
extend `misalignment_journal_port.py`.
**New (services):** `harness_metric_scorer.py`, `regression_suite.py`, `misalignment_miner.py`,
`action_governor.py`, `shared_state_coordinator.py`.
**New (infra):** `sqlite_policy_state.py`, `fixtures/regression/*.jsonl`; extend
`sqlite_misalignment_journal.py`.
**Modified:** `regression_gate.py`, `harness_opt_flow.py`, `verifying.py`, `event.py`,
`bash_tool.py`, `interfaces/factories.py`, `infrastructure/observability/metrics.py`,
`.importlinter`, `weebot/CLAUDE.md`.

## Appendix B — Definition of done (per phase)
1. Failing tests written first; new code ≥ 80% covered (`pytest --cov=weebot`).
2. `pytest tests/ -v` green; **Architecture Fitness Tests** (import-linter) green.
3. New metrics emit; new audit records written (`meta_improvement_log` / `policy_state`).
4. Feature flag (where noted) defaults to safe/off; rollback documented.
5. Conventional-commit messages (`feat:`, `fix:`, `refactor:`) per the repo workflow.

## Appendix C — Suggested commit slices
- `feat(harness): evidence-gated RegressionGate with harness-level metrics` (Phase 1)
- `feat(harness): mine misalignment journal into Evolution Agent evidence` (Phase 2)
- `feat(verify): scoped action evidence bundles` (Phase 3)
- `feat(safety): unified context-sensitive action governor` (Phase 4, flagged)
- `feat(multiagent): transactional shared-state coordinator` (Phase 5)
- `feat(substrate): unified structure+execution query façade (spike)` (Phase 6)
- `docs(harness): adopt code-as-harness vocabulary + glossary` (Phase 7)
