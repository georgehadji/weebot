# Agent-Native Memory — Implementation Plan

**Source paper:** *Are We Ready For An Agent-Native Memory System?* (Zhou et al., SJTU/MemTensor, arXiv:2606.24775v1)
**Date:** 2026-06-30
**Status:** Draft — grounded against actual weebot source (file:line verified)

---

## 0. Correction of the first-pass analysis

The initial gap table was written from assumptions and was wrong on three counts.
Verified against source:

| First-pass claim | Reality (verified) |
|---|---|
| "KG has no BM25 layer" | **FALSE.** `sqlite_knowledge_graph.py:111` creates `kg_nodes_fts` (FTS5). The real bug: it is an *external-content* table (`content='kg_nodes'`) with **no triggers and no manual sync**, so it is never populated → `search()` (`:326`) always falls through to `LIKE` (`:340`). |
| "lossy_context_compressor likely too aggressive" — vague | **Confirmed but specific:** `lossy_context_compressor.py:111` hard-cuts content at `[:150]`, whole summary at `[:2000]` (`:118`). Brute truncation, mid-token, drops exact dates/numbers. |
| "no dense embeddings; add a vector layer" | **FALSE.** Dense infra already exists: `qmd_integration/embeddings.py` (`LocalEmbeddings`), `sqlite_summary_repo.py:75` (`_cosine_similarity`), `semantic_skill_retriever.py`, `semantic_task_router.py`. It is simply **not wired into the KG**. Hybrid retrieval is a *wiring* job, not a new dependency. |

Also confirmed **already correct** and needing no change:
- `KnowledgeGraphService` dedups by deterministic `(label, name)` id (`knowledge_graph.py:201`) — facts bind to a stable entity, satisfying paper F3's "bind to same entity, don't append as new text".
- `upsert_node` overwrites in place + snapshots history (`sqlite_knowledge_graph.py:158-170`) — not append-only text. Good.
- `MemoryCompactor` is conservative (truncates only screenshot/shell tails, dedupes, preserves constraints) — already aligned with F7/F9. No aggressive summarization.

---

## 1. Paper findings → weebot mapping (verified)

The paper's value is 9 empirical findings (F1–F9). Mapped to real, confirmed gaps:

| Finding | Principle | Weebot gap (verified) | Priority |
|---|---|---|---|
| F2/F8 | Evidence retrieval needs sparse index; hybrid (BM25+dense) beats either alone | FTS index dead (`:111`); no fusion; dense not wired to KG | **P0 / P1** |
| F3 | Bind updates to entity; prefer correct temporal state; stale facts = "hallucination of the past" | Merge is confidence-only (`:145`); no recency tiebreak; no `valid_from/valid_to` | **P1** |
| F7 | Coverage-preserving write-time extraction; filter late | `extract_from_step_result` (`:140`) captures only `key: value` lines, drops all other context | **P2** |
| F6 | Light compression > summary for exact recall; never hard-truncate facts | `lossy_context_compressor.py:111` mid-token hard cut | **P2** |
| F9 | Conservative consolidation; avoid delayed flush / over-summary | Already conservative — verify no delayed-flush path | **P3 (verify)** |
| F1 | Match memory structure to workload bottleneck | `context_manager` single-strategy (lossy only) | **P3 (optional)** |

Explicitly **out of scope** (paper findings not worth weebot's cost):
- Parametric/RLGF fine-tuning of memory (too heavy).
- Neo4j-style topological DB (SQLite KG + FTS + dense is sufficient).
- LLM-as-router autonomous retrieval (F8 shows added reflection ≈ no gain, more cost).

---

## 2. Architecture constraints

All changes respect the dependency rule (`Interfaces → Infrastructure → Application → Domain`):

- **Domain** (`domain/models/knowledge_graph.py`): add validity fields to `KnowledgeNode`/edge models. Pure, no deps.
- **Application** (`application/services/knowledge_graph.py`, ports): merge policy, hybrid-retrieve orchestration, extraction logic. Depends only on ports + domain.
- **Infrastructure** (`infrastructure/persistence/sqlite_knowledge_graph.py`, `postgresql/knowledge_graph.py`): FTS triggers, dense column, SQL. Implements `KnowledgeGraphPort`.
- New retrieval reuses existing `qmd_integration` embeddings via a port — no new pip dependency.
- TDD per repo rules: failing test first, 80%+ coverage on new code.

---

## 3. Phased work

### Phase 0 — Fix the dead FTS index  *(P0, bug, ~half day)*

**Problem:** `kg_nodes_fts` external-content table is never synced; full-text search is silently broken everywhere it's used.

**Changes — `infrastructure/persistence/sqlite_knowledge_graph.py`:**
1. In `_init_tables()` after creating the FTS table, add the three standard external-content sync triggers:
   ```sql
   CREATE TRIGGER IF NOT EXISTS kg_nodes_ai AFTER INSERT ON kg_nodes BEGIN
     INSERT INTO kg_nodes_fts(rowid, name, properties) VALUES (new.rowid, new.name, new.properties);
   END;
   CREATE TRIGGER IF NOT EXISTS kg_nodes_ad AFTER DELETE ON kg_nodes BEGIN
     INSERT INTO kg_nodes_fts(kg_nodes_fts, rowid, name, properties) VALUES('delete', old.rowid, old.name, old.properties);
   END;
   CREATE TRIGGER IF NOT EXISTS kg_nodes_au AFTER UPDATE ON kg_nodes BEGIN
     INSERT INTO kg_nodes_fts(kg_nodes_fts, rowid, name, properties) VALUES('delete', old.rowid, old.name, old.properties);
     INSERT INTO kg_nodes_fts(rowid, name, properties) VALUES (new.rowid, new.name, new.properties);
   END;
   ```
2. One-time backfill for existing rows: `INSERT INTO kg_nodes_fts(kg_nodes_fts) VALUES('rebuild');` guarded so it runs only when the FTS row count is 0 but `kg_nodes` is non-empty (migration-safe, idempotent).
3. Wrap all FTS5 DDL in the existing `try/except OperationalError` (FTS5 may be absent in some SQLite builds) — keep the LIKE fallback path intact.

**Tests (`tests/unit/test_sqlite_knowledge_graph.py`):**
- `test_fts_index_populated_on_upsert` — upsert node, assert MATCH returns it (not via LIKE).
- `test_fts_reflects_update` — change name, assert old term no longer matches, new term does.
- `test_fts_reflects_delete` (via prune) — pruned node not in FTS.
- `test_search_falls_back_when_fts_unavailable` — keep existing behavior.

---

### Phase 1 — Recency-aware merge + temporal validity  *(P1, F3, ~1–2 days)*

**Problem:** `_upsert_node_sync` keeps the old value whenever `old._confidence ≥ new._confidence` (`:150-154`). A stale-but-confident fact never gets corrected → paper's "hallucination of the past".

**Domain — `domain/models/knowledge_graph.py`:**
- Add optional `valid_from: datetime | None` and `valid_to: datetime | None` to the property/snapshot model (or as reserved property keys `_valid_from` / `_valid_to` to avoid a schema migration on `kg_nodes`). Prefer reserved keys for v1 to stay migration-light; document as canonical.

**Application — `application/services/knowledge_graph.py`:**
- Introduce an explicit merge policy (small pure function, testable):
  - If new confidence **clearly** exceeds old (delta ≥ configurable margin, default 0.1) → overwrite.
  - Else if values **conflict** and new observation is more recent → overwrite, stamp `_valid_from=now`, move prior value into snapshot with `_valid_to=now` (already snapshotted; add the `valid_to` stamp).
  - Else (agreement / negligible delta) → keep, bump corroboration count.
- This makes recency a first-class tiebreak instead of pure confidence — directly implements F3.

**Infra — `sqlite_knowledge_graph.py`:**
- Move merge decision out of the adapter into the service policy (adapter should persist, not decide). Adapter exposes `get_node(id)`; service computes merged props; adapter writes. Keeps clean-architecture layering (business rule in application, not infra). The current in-adapter merge (`:141-154`) is a layering smell — relocating it also satisfies the repo's dependency rule.

**Tests:**
- `test_recent_conflicting_fact_overwrites_stale` (the core F3 case).
- `test_higher_confidence_overwrites`.
- `test_agreement_bumps_corroboration_not_version_churn`.
- `test_valid_to_stamped_on_supersede`.

---

### Phase 2 — Hybrid retrieval (BM25 + dense + structured), RRF fusion  *(P1, F8, ~2 days)*

**Problem:** retrieval is single-mode (FTS *or* LIKE). Paper F8: moderate hybrid fusion is the consistent winner.

**Port — `application/ports/knowledge_graph_port.py`:**
- Add `async def hybrid_search(query, *, label=None, filters=None, limit=10) -> list[ScoredNode]`.

**Application — orchestration in `KnowledgeGraphService`:**
- Fan out three candidate sets:
  1. **Sparse:** FTS5 BM25 (`rank`) — now working after Phase 0.
  2. **Dense:** cosine over node embeddings using existing `qmd_integration` `LocalEmbeddings` (mirror the pattern already in `sqlite_summary_repo.py:75`). Embed node `name + key properties` at upsert; store vector as a reserved property/blob.
  3. **Structured:** existing `query()` label/filter path.
- Fuse with **Reciprocal Rank Fusion** (k=60 default) — moderate fusion, not sparse-leaning (F8 explicitly warns sparse-leaning underperforms). RRF is a ~15-line pure function → unit-testable in isolation.
- No LLM router / no reflection stage (F8: adds cost, no gain).

**Infra:**
- Add nullable `embedding` storage (reserved property JSON array, or a sidecar `kg_node_vectors(node_id, dim, vec)` table to keep `kg_nodes` lean). Sidecar preferred for query performance and to avoid bloating FTS content.
- Backfill embeddings lazily (on read miss) or via a one-shot maintenance call — gate behind the existing embeddings availability check so environments without the model degrade to sparse+structured only.

**Tests:**
- `test_rrf_fusion_orders_by_combined_rank` (pure).
- `test_hybrid_beats_sparse_only_on_paraphrase` (dense recovers lexical miss).
- `test_hybrid_degrades_gracefully_without_embeddings`.

---

### Phase 3 — Coverage-preserving extraction  *(P2, F7, ~1 day)*

**Problem:** `extract_from_step_result` (`knowledge_graph.py:140-164`) only captures `key: value` lines and silently drops everything else. Aggressive write-time filtering loses multi-hop context (F7).

**Changes — `application/services/knowledge_graph.py`:**
- Keep the cheap heuristic as a fast path, but:
  - Attach the **surrounding raw line context** as `evidence` on each extracted fact (so late-stage retrieval can recover detail).
  - Store both user- and tool-origin lines (F7: keep both turns).
- Add an **optional** LLM schema-constrained extraction path (entity–relation triplets), gated behind a feature flag + `ModelCascadeService` (FREE/BUDGET tier first, per CLAUDE.md model-cascading rule). Off by default to control cost; on for high-value sessions.

**Tests:**
- `test_extraction_preserves_surrounding_context_as_evidence`.
- `test_extraction_keeps_both_user_and_tool_lines`.
- `test_llm_extraction_gated_by_flag`.

---

### Phase 4 — Lighten lossy compression  *(P2, F6, ~half day)*

**Problem:** `lossy_context_compressor.py:111,118` hard-cuts mid-content; exact dates/numbers/names lost.

**Changes — `lossy_context_compressor.py`:**
- Replace single head cut with **head + tail** retention for long messages (keep first ~120 and last ~120 chars with an elision marker) so trailing facts (often the answer) survive.
- Keep short messages (< threshold) **verbatim** (F6: raw > summary for exact recall).
- Preserve numeric/date tokens when truncating (cheap regex guard) — these are the highest-value exact details.
- Make caps configurable via `ContextBudget` rather than the hardcoded `150`/`2000`.

**Tests:**
- `test_short_messages_kept_verbatim`.
- `test_long_message_keeps_head_and_tail`.
- `test_dates_and_numbers_survive_compression`.

---

### Phase 5 — Verify maintenance timing (F9) + optional workload routing (F1)  *(P3)*

- **F9 verify:** audit consolidation paths (`memory_compactor.py`, any flush in `cron_delivery_service` / summary repo) to confirm no delayed-flush regime. `MemoryCompactor` already conservative — likely doc-only. Add a regression test asserting consolidation is synchronous (no buffered-merge window).
- **F1 optional:** make `ContextManager` strategy pluggable by task type (conversational → summary-first; cross-session fact recall → graph/hybrid; execution trace → raw append). Larger change; defer until Phases 0–4 land and are measured.

---

## 4. Sequencing & risk

| Phase | Value | Risk | Depends on |
|---|---|---|---|
| 0 FTS fix | High (unblocks all search) | Low | — |
| 1 Recency merge | High (F3, core failure mode) | Med (merge semantics) | — |
| 2 Hybrid retrieval | High (F8) | Med (embeddings wiring) | Phase 0 |
| 3 Extraction | Med (F7) | Low | — |
| 4 Compression | Med (F6) | Low | — |
| 5 Verify/route | Low | Low | 0–4 |

**Recommended order:** 0 → 1 → 2 → 3 → 4 → 5. Phase 0 first: it's a genuine bug and a prerequisite for measuring Phases 1–2.

## 5. Validation

- Per-phase pytest (TDD, failing test first).
- After Phase 2, a small retrieval eval: seed KG with paraphrased + temporally-spaced facts, assert hybrid recall > sparse-only and that superseded facts are not returned (combines F3+F8). Reuse the existing eval harness (`application/eval/`) if a memory task fits.
- Keep changes behind the existing feature-flag/cascade machinery so each phase is independently revertible.

## 6. Highest-value single change

**Phase 0** — the dead FTS index. It is a real, silent bug fixable in ~20 lines, and it unblocks the evidence-retrieval and hybrid work (F2/F8) that the rest of the plan builds on. Ship it first regardless of how far the rest proceeds.
