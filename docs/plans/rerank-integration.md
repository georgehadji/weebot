# Rerank Integration Plan — Cohere Rerank via OpenRouter

**Date:** 2026-06-07
**Status:** Research complete — implementation deferred
**Models:** `cohere/rerank-4-pro`, `cohere/rerank-4-fast`, `cohere/rerank-v3.5`

---

## Model Characteristics

| Model | Context | Price | Latency | Best For |
|-------|---------|-------|---------|----------|
| `cohere/rerank-4-pro` | 32K | $0.0025/search | Medium | Research synthesis, skill retrieval, evaluation |
| `cohere/rerank-4-fast` | 32K | ~$0.001/search | Low | Web search reordering, conversation compression |
| `cohere/rerank-v3.5` | 4K | ~$0.001/search | Lowest | Memory archiving, knowledge graph FTS5 |

**Critical:** These are `text->rerank` modality models — they use a **dedicated rerank endpoint** (`POST /rerank`), not the chat completions API. They cannot be called via `LLMPort.chat()`. A new `RerankPort` + adapter is required.

---

## Integration Points — Ranked by Value

### 1. 🔴 HIGH: Multi-Source Research Synthesis
**File:** `weebot/application/services/multi_source_research.py:193-210`
**Current behavior:** Sorts results by `confidence`/`reliability_score` descending — a single metadata field.
**Rerank value:** Replace the single-field sort with a cross-encoder rerank against the original query. Each result's title+snippet is scored against the research question, producing a query-aware relevance ordering that no metadata field can match.
**Model:** `cohere/rerank-4-pro` (quality matters for research)
**Estimated latency impact:** +200-500ms per research call (acceptable — research is latency-tolerant)

### 2. 🔴 HIGH: BM25 Skill Retrieval → Semantic Reranking
**File:** `weebot/application/services/bm25_skill_retriever.py:90-119`
**Current behavior:** BM25Okapi lexical scoring → normalize → top-K. Misses semantically relevant skills with different vocabulary.
**Rerank value:** Retrieve top-20 BM25 candidates, then rerank with a cross-encoder against the task description. Skills that are semantically relevant but lexically different surface to the top.
**Model:** `cohere/rerank-4-pro` (quality matters — wrong skill = wasted execution)
**Integration point:** `SkillRetrieverPort.retrieve()` — the ABC contract already says "ordered by relevance". A `RerankingSkillRetriever` wrapper would intercept BM25 results, rerank, and return.

### 3. 🟡 MEDIUM: Web Search Result Reordering
**File:** `weebot/tools/web_search.py`
**Current behavior:** Returns results in engine-returned order (DDG → Bing fallback). No scoring or reordering.
**Rerank value:** After collecting results from all engines, deduplicate and rerank against the search query. Removes the engine-order bias and surfaces the most relevant results first, regardless of which engine returned them.
**Model:** `cohere/rerank-4-fast` (latency-sensitive — users wait for search)

### 4. 🟡 MEDIUM: Conversation Compressor — Selective Turn Preservation
**File:** `weebot/application/services/conversation_compressor.py:55-90`
**Current behavior:** Protects first 3 and last 6 turns; summarizes everything in between with one LLM call.
**Rerank value:** Score each middle turn against the current step description. High-relevance turns are preserved verbatim; only low-relevance turns are compressed. This keeps contextually important information (e.g., "the API key is XYZ") from being lost in summarization.
**Model:** `cohere/rerank-4-fast` (latency-sensitive — on the critical execution path)

### 5. 🟡 MEDIUM: Memory Archivist — Relevance-Based Eviction
**File:** `weebot/application/services/memory_archivist.py:44-70`
**Current behavior:** TTL-based eviction — events older than 1 hour are replaced by a summary.
**Rerank value:** Score each event against the current task before eviction. High-relevance old events are promoted into the recent bucket (extending their TTL); low-relevance recent events can be archived early. This prevents losing critical context just because it's "old."
**Model:** `cohere/rerank-v3.5` (high-throughput — runs periodically, not per-step)

### 6. 🟡 MEDIUM: Staged Evaluator — Discriminative Probe Ordering
**File:** `weebot/application/services/staged_evaluator.py:40-78`
**Current behavior:** Splits tasks into a probe subset (first N) and a full set. If probe score < threshold, remaining tasks are skipped.
**Rerank value:** Reorder the task list so that the most discriminative tasks (those most likely to differentiate good vs. bad skills) appear first in the probe. This makes the go/no-go decision more efficient — fewer tasks needed to reach statistical confidence.
**Model:** `cohere/rerank-4-pro` (quality matters for evaluation)

### 7. 🟢 LOW: Knowledge Graph FTS5 Semantic Reordering
**File:** `weebot/application/services/knowledge_graph.py:130-157`
**Current behavior:** FTS5 MATCH returns results sorted by lexical rank; LIKE fallback is unsorted.
**Rerank value:** Rerank the FTS5/LIKE results by semantic relevance to the query. Particularly valuable when the query uses different vocabulary than the stored nodes.
**Model:** `cohere/rerank-v3.5` (high-throughput, 4K context sufficient for node titles+summaries)

---

## Architecture Design

A new `RerankPort` ABC in `application/ports/` would define:

```python
class RerankPort(ABC):
    @abstractmethod
    async def rerank(
        self, query: str, documents: list[str],
        model: str = RERANK_MODEL_FAST, top_n: int | None = None,
    ) -> list[RerankResult]: ...
```

A `CohereRerankAdapter` in `infrastructure/adapters/` would call the OpenRouter rerank endpoint:

```
POST https://openrouter.ai/api/v1/rerank
Authorization: Bearer $OPENROUTER_API_KEY
{"model": "cohere/rerank-4-pro", "query": "...", "documents": [...]}
```

**DI wiring:** Register in `Container._factories.py` → inject into services that need it.

**Cost model:** Per-search pricing (~$0.001–$0.0025 per call), not per-token. At 10-50 rerank calls per agent session, cost is <$0.10/session.

---

## Implementation Priority

| Priority | Integration Point | Model | Effort | Impact |
|----------|------------------|-------|--------|--------|
| P1 | BM25 Skill Retriever | rerank-4-pro | 2-3 hrs | High — better skill selection = better task execution |
| P1 | Multi-Source Research | rerank-4-pro | 2-3 hrs | High — research quality directly user-visible |
| P2 | Web Search | rerank-4-fast | 1-2 hrs | Medium — incremental improvement |
| P2 | Conversation Compressor | rerank-4-fast | 2-3 hrs | Medium — reduces context-loss bugs |
| P3 | Memory Archivist | rerank-v3.5 | 1-2 hrs | Low — TTL-based is already adequate |
| P3 | Staged Evaluator | rerank-4-pro | 2-3 hrs | Low — benefits SkillOpt only |
| P4 | Knowledge Graph | rerank-v3.5 | 1 hr | Low — FTS5 is adequate for current scale |

**Recommended first step:** Create `RerankPort` + `CohereRerankAdapter` + wire into `SkillRetrieverPort` as a `RerankingSkillRetriever` wrapper. This gives the highest value with the least architectural disruption (the port already expects "ordered by relevance").
