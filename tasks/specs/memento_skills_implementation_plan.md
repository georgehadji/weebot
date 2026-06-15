# Memento-Skills → weebot: Deployment-Time Learning Implementation Plan

**Status:** Draft for review
**Author:** audit follow-up (Memento-Skills, arXiv:2603.18743)
**Date:** 2026-06-15
**Related:** `tasks/specs/code_as_harness_implementation_plan.md`, memory `code_as_harness_analysis.md` (top gap: "misalignment journal not fed into Evolution Agent")

---

## 1. Context & thesis

Memento-Skills' single idea worth porting is **deployment-time learning**: keep the LLM frozen and treat every live task as a chance to *write* or *repair* a skill via a continual `Read → Execute → Reflect → Write` loop. weebot already has richer machinery than Memento in most dimensions (versioned `Skill` model, GEPA-style `SkillOptFlow`, transfer scores, slow-update sections). **What it lacks is the closed loop in production.** The recurring weebot pattern — confirmed again here — is *rich signal captured, loop not closed*.

This plan closes five seams (R1–R5 from the audit), reusing existing components wherever possible. **No new agent framework, no skill-library rewrite.** Almost all the work is wiring + replacing stub logic with real LLM logic.

## 2. Verified current-state map (anchors)

| Concern | Location | State |
|---|---|---|
| Live skill injection (R2 anchor) | `weebot/application/agents/executor/_base.py:624-637` — `retrieve(step.description, top_k=2)`, inject if `m.score > 0.15` | **Live & wired.** No "no-match → create" branch. |
| Skill retriever composition (R3 anchor) | `weebot/application/di/_skills.py:15` `_create_skill_retriever` — BM25 → optional Cohere rerank | First stage is **lexical only**. |
| Post-task lifecycle (R1 hook) | `SUMMARIZING → MetaAnalysis → Verifying → Completed` (`states/summarizing.py`, `states/meta_analysis.py:89`) | `MetaAnalysisState` already gathers trajectory data + runs `MetaCritic`, non-blocking. Ideal sibling for distillation. |
| Trajectory→skill creation | `weebot/application/services/autonomous_learning.py` `AutonomousSkillCreator` | **Orphaned** (no caller, not in DI) + stub heuristics; comment: *"In production this would use an LLM."* |
| Offline optimizer | `weebot/application/flows/skill_opt_flow.py` + `ports/optimizer_port.py` | Full GEPA loop, but only via `cli/commands/flow.py` on **curated** train/validation tasks. |
| Skill gap detection | `weebot/application/agents/layer_diagnostics_agent.py` — emits `SKILL: Retrieval missed procedural knowledge` | Diagnoses; does not create. High-confidence R2 signal. |
| Misalignment journal (R5 source) | `ports/misalignment_journal_port.py` + `infrastructure/persistence/sqlite_misalignment_journal.py`; populated from `plan_act_flow.py:436`, `states/executing.py:98`, `states/planning.py:131` | **Live & persisted.** Not routed to the optimizer. |
| Remote skill market (R4) | `ports/skill_index_port.py` (`RemoteSkill`, `fetch_index/search/download` w/ sha256) + `application/skills/clawhub_importer.py` | Port exists; import is stub-generation, no dedup/validation. |
| Two skill stores (**critical seam**) | `SkillRegistry` (files `.weebot/skills/*/SKILL.md`, feeds retriever/curator) vs `SkillStore` (SQLite, feeds `SkillOptFlow`) | **Not synced.** A new skill must reach both. |
| Curation | `services/skill_curator.py` (weekly cron, `_skills.py:54`) | **Append-only** — logs ARCHIVE/PIN/KEEP, never acts. |

## 3. Goals / non-goals

**Goals**
- G1. Every completed task can yield a validated, deduped, *quarantined* new skill (R1).
- G2. A retrieval miss on a recurring sub-task triggers skill creation (R2).
- G3. Retrieval recall survives library growth via a semantic first stage (R3).
- G4. Curation and import *act* (archive / dedup / validate), not just observe (R4).
- G5. Live failures are attributed to a concrete skill and feed the existing optimizer (R5).

**Non-goals**
- Replacing `SkillOptFlow`, the `Skill` model, or the retriever interface.
- LLM fine-tuning (Memento's whole point is *zero retraining*).
- Auto-trusting self-generated skills (see §5 trust model — this is a security boundary).

## 4. Architecture constraints (must hold)

- **Dependency rule:** `Interfaces → Infrastructure → Application → Domain`. New ports → `application/ports/`; new domain models/fields → `domain/models/`; new services → `application/services/`; new adapters → `infrastructure/`. Update the import-linter contracts (repo enforces them — see recent `fix(arch)` commits).
- **Structured output:** every LLM call that produces a skill/edit/attribution returns a Pydantic model (extend `weebot/models/structured_output.py`), never free-form parsing.
- **Model cascade:** distillation/attribution/curation use `ModelCascadeService` FREE→BUDGET→PREMIUM; reserve PREMIUM for the optimizer.
- **Fail-open & non-blocking:** all learning steps mirror `MetaAnalysisState` — wrapped in try/except, never block task completion.
- **Feature-flagged:** every phase ships behind a default-OFF flag in `weebot/config/`.
- **Bash safety unchanged:** skills are prompt artifacts; shell still passes `core/bash_guard.py` at execution time.

## 5. Cross-cutting: self-generated skill **trust model** (security boundary)

Auto-created skills are *agent-authored content* and must not be able to silently steer future runs (directly relevant to the recent OpenClaw self-poisoning hardening). Introduce a trust lifecycle on `SkillMetadata`:

```
trust: "quarantined" | "candidate" | "trusted"   # default "trusted" for human-authored
provenance: {origin: "human"|"distilled"|"imported", session_id, trajectory_ref, created_at}
```

- `_base.py` injection gate becomes: inject only if `m.score > τ_inject` **and** `trust == "trusted"`.
- Promotion: `quarantined → candidate` after passing validation (Phase 1); `candidate → trusted` after **N** independent positive-utility uses (validated via `validation_runner` / SkillOpt acceptance). Demotion on net-negative utility.
- Quarantined/candidate skills are still *retrievable for offline optimization* but never injected live. This makes R1 safe to enable by default.

---

## Phase 0 — Foundations (shared write path, flags, trust)

**Why first:** R1/R4 both need one canonical way to persist a skill to *both* stores + refresh the index; the trust model touches the domain.

- **Domain:** add `trust` + `provenance` to `SkillMetadata` (`domain/models/skill.py`); add `SkillProvenance` model. Default `trust="trusted"` so existing skills are unaffected.
- **New service `SkillPublisher`** (`application/services/skill_publisher.py`): single entrypoint `publish(skill) -> Path`:
  1. write `.weebot/skills/<name>/SKILL.md` via `SkillRegistry` conventions,
  2. upsert into `SkillStore` (SQLite),
  3. call `skill_retriever.refresh()` + (Phase 3) vector index upsert.
  Replaces ad-hoc writes in `AutonomousSkillCreator` and `ClawHubImporter`.
- **Config** (`weebot/config/`): `learning` block — `enable_live_distillation=False`, `enable_skill_gap_trigger=False`, `enable_semantic_retrieval=False`, `enable_curation_actions=False`, `enable_online_skillopt=False`, plus thresholds `tau_inject=0.15`, `tau_create=0.35`, `tau_dedup=0.80`, `candidate_promotion_uses=3`.
- **Events** (`domain/models/event.py`): `SkillDistilled`, `SkillGapDetected`, `SkillRepairEnqueued`, `SkillPromoted` (for Web UI + metrics).
- **DI:** new `LearningMixin` (`application/di/_learning.py`) owning the above; register `skill_publisher`.
- **Tests:** `SkillPublisher` writes to both stores + refreshes; trust defaults preserve current behaviour.

**Acceptance:** publishing a `Skill` makes it retrievable (after refresh) and loadable by `SkillStore`; human skills still inject unchanged.

## Phase 1 — R1: Live experience → skill distillation (headline)

- **Port** `SkillDistillerPort` (`application/ports/skill_distiller_port.py`): `distill(task, trajectory, existing_names) -> Optional[Skill]`.
- **Service** `LLMSkillDistiller` (`application/services/skill_distiller.py`) — **repurpose the orphaned `autonomous_learning.py`**, deleting the stub heuristics:
  - Cheap pre-filter (cascade FREE): "does this trajectory contain a reusable, generalizable procedure?" → bool + confidence.
  - If yes (BUDGET/PREMIUM): emit a structured `DistilledSkill` (name, description, when-to-use, procedure, guardrails) via Pydantic structured output.
  - **Dedup:** `skill_retriever.retrieve(description, top_k=3)`; if top ≥ `tau_dedup`, *do not create* — instead enqueue a reinforcing edit to the existing skill (hand to Phase 5 / SkillOpt). Prevents library bloat (Memento's explicit concern).
  - **Validate:** run `validation_runner` + `skill_trigger_tester` against the originating task; require pass before publish.
  - Publish via `SkillPublisher` with `trust="quarantined"`, `provenance.origin="distilled"`.
- **Integration:** new `PostTaskLearningState` inserted `MetaAnalysis → PostTaskLearning → Verifying`, reusing the trajectory data `MetaAnalysisState` already gathers (`step_results`, `failures`, `tool_count`). Non-blocking, flag-gated.
- **Retire dead code:** remove `AutonomousSkillCreator` stubs (replaced); keep/extend `MemoryNudgeService` if still used.
- **Tests:** distiller returns None on trivial trajectories; produces valid SKILL.md on a multi-step trajectory; dedup path skips near-duplicates; published skill is quarantined (not injected) until promoted; integration test: run task → distill → skill is retrievable next task.

**Acceptance:** with the flag on, a novel multi-step task produces a validated quarantined skill; promotion after `candidate_promotion_uses` makes it inject live.

## Phase 2 — R2: Retrieve-vs-generate trigger (depends on Phase 1)

- **Anchor:** `_base.py:624-637`. Add an `else`/post-loop branch: if no match with `score > tau_create`, record a gap signal (do **not** create inline — never block the live step):
  - Emit `SkillGapDetected` + enqueue an `IdeaContract` with new `IdeaSource.SKILL_GAP` (`domain/models/idea_contract.py`), routed through the existing gate (`idea_gate` → `IntentReviewService` → `MainReviewService`).
- **Second signal:** wire `layer_diagnostics_agent`'s `SKILL` verdict into the same queue (higher confidence — it already knows procedural knowledge was missing).
- **Consumer:** the Phase 5 background consolidation job batches `SKILL_GAP` contracts and invokes `LLMSkillDistiller` against the relevant past trajectories (deferred, off the hot path).
- **Tests:** low-score retrieval emits exactly one gap signal (deduped per task); gap with an existing near-duplicate skill does not re-create; gate rejection drops the contract.

**Acceptance:** a recurring sub-task with no good skill reliably produces a queued, gated skill-creation request.

## Phase 3 — R3: Semantic first-stage retrieval (independent of 1/2)

- **Reuse embeddings:** prefer `weebot/qmd_integration/rag_engine.py` / `RagPort`; fall back to `sqlite-vec`. No new model dependency if RAG embeddings are already configured.
- **Service** `EmbeddingSkillRetriever` (`application/services/embedding_skill_retriever.py`) implementing `SkillRetrieverPort`, backed by a vector index over `name + description + content`.
- **Compose** in `_skills.py:_create_skill_retriever`: `HybridSkillRetriever` unions BM25 ∪ embedding candidates → dedupe → existing `RerankingSkillRetriever` (rerank stage unchanged). This *widens stage-1 recall* so the cross-encoder can rank skills BM25 would never surface (paraphrase / cross-lingual).
- **Index lifecycle:** build on startup; incremental upsert via `SkillPublisher.refresh()` (Phase 0). Degrade to BM25-only if embeddings unavailable (mirrors current optional-rerank pattern).
- **Tests:** paraphrased query that BM25 misses is recalled by the hybrid; rerank order preserved; graceful BM25 fallback when embeddings off.

**Acceptance:** measurable recall@k improvement on a held-out paraphrase set vs BM25-only, with no regression in rerank precision.

## Phase 4 — R4: Curation & import that act (depends on Phase 0)

- **SkillCurator:** add flag-gated `apply_recommendations`: move `archive-candidate` skills to `.weebot/skills/_archived/` (reversible move, **not delete**), respecting `PIN` (already modelled). Default = report-only (current behaviour) until flag on.
- **Import pipeline:** route `ClawHubImporter` (and any `SkillIndexPort`/SkillHub adapter) through `SkillPublisher`: (a) dedup against retriever before install, (b) run `validation_runner` on the fetched full body, (c) publish as `trust="candidate"`, `provenance.origin="imported"`. Honour `RemoteSkill.sha256` verification already specified in the port.
- **Tests:** archive respects PIN + is reversible; duplicate import is skipped; an import failing validation is not published.

**Acceptance:** a stale unpinned skill is archived weekly; imported skills are deduped, validated, and quarantined.

## Phase 5 — R5: Failure attribution + online SkillOpt (depends on 0; reuses SkillOpt)

- **Service** `FailureAttributor` (`application/services/failure_attributor.py`): read `MisalignmentJournalPort` entries + `failure_signature` records for a window; map each failure to the most-likely implicated skill (which `SkillMatch` was injected/active in that trajectory) and aggregate by skill.
- **Online optimization:** for skills exceeding a failure-frequency threshold, build an `OptimizationBatch` from the **live failing trajectories** (not curated tasks) and drive the existing `OptimizerPort` ops (`reflect_on_failures → merge_edits → rank_edits → ApplySkillEditsCommand → validate → accept/reject`). Implement as `OnlineSkillOptFlow` (thin parameterization of `SkillOptFlow` with `train_tasks` = live failing prompts, `epochs=1`).
- **Schedule:** register a weekly `skill-consolidation` job mirroring `register_curator_job` (`_skills.py:54`) — the "dream daemon" analogue that also batches Phase 2 `SKILL_GAP` contracts. **This directly closes the memory-flagged gap** (misalignment journal → optimizer).
- **Tests:** attributor maps a known failing trajectory to the injected skill; online batch produces ≥1 accepted edit on a seeded regression; PIN/quarantine respected.

**Acceptance:** a repeatedly-failing skill is auto-scheduled for repair from live data and improves its validation score.

---

## 6. Sequencing & milestones

```
Phase 0 (foundations)  ──┬─→ Phase 1 (R1 distill) ──→ Phase 2 (R2 trigger)
                         ├─→ Phase 3 (R3 retrieval)   [parallel]
                         ├─→ Phase 4 (R4 curate/import)
                         └─→ Phase 5 (R5 attribution + online SkillOpt) ←─ consumes Phase 2 queue
```

- **M1 (highest value):** Phase 0 + Phase 1 → live distillation behind a flag. This *is* the Memento thesis.
- **M2:** Phase 2 → the live trigger; Phase 3 → recall that scales. (Independent; can interleave.)
- **M3:** Phase 4 + Phase 5 → act on curation + close the failure→repair loop.

## 7. Testing strategy

- TDD per service (`tests/unit/`), ≥80% coverage on new code; AAA structure.
- Integration test for the full loop (`tests/integration/`): task → distill → retrieve → inject after promotion.
- Add seeded regression tasks for Phase 5 to the existing `regression_suite`.
- Keep all learning paths fail-open; add a test asserting a distiller/attributor exception never aborts the flow.
- Update import-linter contracts; run `python -m cli.main doctor` + full `pytest` before each milestone.

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| **Library poisoning** by self-authored skills | Trust model (§5): quarantine → candidate → trusted; never inject below `trusted`. Default-safe. |
| Library bloat / near-duplicates | `tau_dedup` dedup in Phase 1; duplicate imports skipped in Phase 4. |
| Two-store drift (files vs SQLite) | Single `SkillPublisher` write path (Phase 0); no other code writes skills. |
| Latency on the hot path | All learning is post-task (`PostTaskLearningState`) or background (Phase 5 job); R2 only *records* a signal inline. |
| Cost | Cascade FREE pre-filters before any BUDGET/PREMIUM call; PREMIUM only in the optimizer. |
| Architecture violations | Ports/models/services/adapters placed per dependency rule; import-linter updated + run in CI. |

## 9. Open questions

1. Embeddings for R3 — reuse the QMD RAG stack, or add `sqlite-vec` standalone? (Prefer reuse if RAG embeddings are already provisioned.)
2. `candidate_promotion_uses` default (3?) and the utility signal source — `validation_runner` pass count vs SkillOpt acceptance vs live success rate.
3. Should `SKILL_GAP` contracts also be surfaced in the Web UI for human approval before distillation, or fully autonomous under a flag?
4. Is there an existing concrete `SkillIndexPort` adapter (SkillHub) to wire in Phase 4, or is `ClawHubImporter` the only import path today?
