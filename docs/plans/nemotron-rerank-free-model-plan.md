# Implementation Plan — NVIDIA Nemotron Rerank Free Model Integration

> **Date:** 2026-06-10
> **Plan type:** Cost optimization — add free reranking model to existing pipeline
> **Architecture guardrails:** All changes respect Hexagonal architecture. Model constant changes touch Config layer only; DI wiring changes touch Infrastructure composition root only; no domain or port changes needed.

---

## Summary

The NVIDIA Llama Nemotron Rerank VL 1B V2 model (`nvidia/llama-nemotron-rerank-vl-1b-v2:free`) is a free reranking model available via OpenRouter's `/api/v1/rerank` endpoint. It is already registered in `weebot/config/model_registry.py` as commit `nvidia/llama-nemotron-rerank-vl-1b-v2:free → OPENROUTER`.

The existing reranking infrastructure is model-agnostic — every consumer delegates to `RerankPort.rerank(query, documents, model=...)`. The `OpenRouterRerankAdapter` already supports any OpenRouter rerank-capable model string. **No port, domain, or adapter changes are needed.**

This plan adds the model to the cost-tier ladder in `model_refs.py` and routes high-throughput/low-criticality use cases to it, replacing paid Cohere models on those paths.

---

## Current state

### Model tier ladder (7 use cases → 3 paid Cohere models)

| Use case | Model | Context | Cost/search | Quality sensitivity |
|----------|-------|---------|-------------|---------------------|
| `"research"` | Cohere Rerank 4 Pro | 32K | ~$0.0025 | High |
| `"skills"` | Cohere Rerank 4 Pro | 32K | ~$0.0025 | High |
| `"evaluation"` | Cohere Rerank 4 Pro | 32K | ~$0.0025 | High |
| `"search"` | Cohere Rerank 4 Fast | 32K | $$ | Medium |
| `"compressor"` | Cohere Rerank 4 Fast | 32K | $$ | Low |
| `"memory"` | Cohere Rerank v3.5 | 4K | $ | Low |
| `"knowledge"` | Cohere Rerank v3.5 | 4K | $ | Low |

### Direct constant consumers (bypass `get_rerank_model_for()`)

| File | Constant used | Line |
|------|---------------|------|
| `web_search.py` | `RERANK_MODEL_FAST` | 99 |
| `multi_source_research.py` | `RERANK_MODEL_PRO` | 365 |
| `reranking_skill_retriever.py` | `RERANK_MODEL_PRO` (constructor default) | import |
| `openrouter_rerank_adapter.py` | `RERANK_MODEL_FAST` (constructor default) | 43 |

### DI wiring

| Factory | Creates | Model override? |
|---------|---------|-----------------|
| `di/_factories.py:_create_rerank_adapter()` | `OpenRouterRerankAdapter()` | None → inherits adapter default (`RERANK_MODEL_FAST`) |
| `di/_skills.py:_create_skill_retriever()` | `RerankingSkillRetriever(base, rerank)` | None → inherits class default (`RERANK_MODEL_PRO`) |
| `di/_skills.py` log message | `"BM25 + Cohere rerank"` | Outdated after this change |

---

## Target state

### Expanded model tier ladder (7 use cases → 4 models, 1 free)

| Use case | Model | Context | Cost/search |
|----------|-------|---------|-------------|
| `"research"` | Cohere Rerank 4 Pro | 32K | ~$0.0025 |
| `"skills"` | Cohere Rerank 4 Pro | 32K | ~$0.0025 |
| `"evaluation"` | Cohere Rerank 4 Pro | 32K | ~$0.0025 |
| `"search"` | **NVIDIA Nemotron Rerank (FREE)** | 4K | **$0.00** |
| `"compressor"` | **NVIDIA Nemotron Rerank (FREE)** | 4K | **$0.00** |
| `"memory"` | **NVIDIA Nemotron Rerank (FREE)** | 4K | **$0.00** |
| `"knowledge"` | **NVIDIA Nemotron Rerank (FREE)** | 4K | **$0.00** |

### Direct constant consumers (post-change)

| File | Constant used | Change |
|------|---------------|--------|
| `web_search.py` | `get_rerank_model_for("search")` | Replace hardcoded constant with centralized lookup |
| `multi_source_research.py` | `RERANK_MODEL_PRO` | Unchanged (quality-sensitive) |
| `reranking_skill_retriever.py` | `RERANK_MODEL_PRO` (constructor default) | Unchanged (quality-sensitive) |
| `openrouter_rerank_adapter.py` | `RERANK_MODEL_FREE` (new constructor default) | Changed — all callers get free model unless they override |

---

## Changes (5 files)

### Change 1 — `weebot/config/model_refs.py` — Add `RERANK_MODEL_FREE` constant

**Layer:** Config
**Risk:** Low — additive only

Insert after `RERANK_MODEL_V35` (line 414):

```python
RERANK_MODEL_FREE: str = "nvidia/llama-nemotron-rerank-vl-1b-v2:free"
"""NVIDIA Llama Nemotron Rerank VL 1B V2 — FREE via OpenRouter.
4K context, vision-language capable. Ideal for high-throughput or
development reranking where budget is constrained.
OpenRouter slug: nvidia/llama-nemotron-rerank-vl-1b-v2:free

WARNING: This is a 1B-parameter model. It is NOT a Cohere model —
results may differ in quality. Validate on representative queries
before using in production quality-sensitive paths."""
```

### Change 2 — `weebot/config/model_refs.py` — Update `get_rerank_model_for()`

**Layer:** Config
**Risk:** Low — `get_rerank_model_for()` has zero callers in production code (searched: only defined, never imported). Updating it has no live impact on existing behavior; it prepares the routing function for future adoption.

Update the routing map to use `RERANK_MODEL_FREE` for high-throughput use cases:

```python
def get_rerank_model_for(use_case: str) -> str:
    _rerank_map = {
        "research": RERANK_MODEL_PRO,      # multi-source synthesis — quality matters
        "skills": RERANK_MODEL_PRO,        # BM25 → semantic — quality matters
        "evaluation": RERANK_MODEL_PRO,    # staged evaluator — quality matters
        "search": RERANK_MODEL_FREE,       # web search — latency-sensitive, quality-tolerant
        "compressor": RERANK_MODEL_FREE,   # conversation compressor — high-throughput
        "memory": RERANK_MODEL_FREE,       # memory archivist — high-throughput
        "knowledge": RERANK_MODEL_FREE,    # knowledge graph FTS5 — high-throughput
    }
    return _rerank_map.get(use_case, RERANK_MODEL_FREE)
```

Note: The default fallback changes from `RERANK_MODEL_FAST` → `RERANK_MODEL_FREE`. Unknown/non-existent use cases will now default to the free model instead of the paid fast model. This is intentional — failsafe should be cheapest option.

### Change 3 — `weebot/infrastructure/adapters/openrouter_rerank_adapter.py` — New constructor default

**Layer:** Infrastructure (Adapter)
**Risk:** Low — changes default, consumers can still override per-call

Line 43: Change constructor default from `RERANK_MODEL_FAST` to `RERANK_MODEL_FREE`.

```python
# Before:
default_model: str = RERANK_MODEL_FAST,

# After:
default_model: str = RERANK_MODEL_FREE,
```

Also update the import at line 18:
```python
from weebot.config.model_refs import RERANK_MODEL_FREE
```

The docstring should also be updated to reflect this.

**Architecture note:** This is an infrastructure adapter importing from `config/model_refs.py` — the adapter already has this import for `RERANK_MODEL_FAST`. Changing the imported symbol does not add a new dependency direction. ✅

**Impact analysis:** All DI-resolved `RerankPort` instances will now default to the free model. This affects:
- `RerankingSkillRetriever` — but only when NO model is passed to its constructor (which `di/_skills.py` currently doesn't pass — it inherits the constructor default of `RERANK_MODEL_PRO`). **No change** to skill reranking.
- `WebSearchTool` — but it hardcodes `RERANK_MODEL_FAST` in its `set_rerank()` method, overriding the adapter default. **No change** (yet — see Change 4).
- `MultiSourceResearchEngine` — hardcodes `RERANK_MODEL_PRO`. **No change.**
- Any future code that calls `RerankPort.rerank()` without a model override will now use the free model — which is the desired default.

### Change 4 — `weebot/tools/web_search.py` — Use centralized model lookup

**Layer:** Tools
**Risk:** Low — replaces hardcoded constant with function call

Lines 91-99: Replace `RERANK_MODEL_FAST` inline import with `get_rerank_model_for("search")`.

```python
# Before:
if self._rerank is not None and len(all_results) > num_results:
    try:
        from weebot.config.model_refs import RERANK_MODEL_FAST
        ...
        model=RERANK_MODEL_FAST,
        ...

# After:
if self._rerank is not None and len(all_results) > num_results:
    try:
        from weebot.config.model_refs import get_rerank_model_for
        ...
        model=get_rerank_model_for("search"),
        ...
```

**Why not use RERANK_MODEL_FREE directly:** Using `get_rerank_model_for("search")` keeps the model routing centralized in `model_refs.py`. If the model changes again (e.g., a better free reranker appears), only one file changes.

### Change 5 — `weebot/application/di/_skills.py` — Update log message

**Layer:** Application (DI Composition Root)
**Risk:** None — cosmetic only

Line 43: Change log message to be model-agnostic.

```python
# Before:
logger.info("Skill retriever: BM25 + Cohere rerank")

# After:
logger.info("Skill retriever: BM25 + rerank (RerankPort configured)")
```

**Why:** The reranker is no longer necessarily Cohere. The log should reflect what was configured, not assume a specific model family.

---

## No-change confirmations

| File | Reason |
|------|--------|
| `weebot/domain/models/rerank.py` | Pure data models — model-agnostic. `RerankRequest.model` is `str | None`. ✅ |
| `weebot/application/ports/rerank_port.py` | Abstract interface — `model: str | None` parameter. ✅ |
| `weebot/application/services/reranking_skill_retriever.py` | Constructor default `RERANK_MODEL_PRO` unchanged (quality-sensitive). ✅ |
| `weebot/application/services/multi_source_research.py` | Hardcoded `RERANK_MODEL_PRO` unchanged (quality-sensitive). ✅ |
| `weebot/config/model_registry.py` | Model entry already added. ✅ |
| `weebot/tools/tool_registry.py` | Injects `RerankPort` — model-agnostic. ✅ |
| `weebot/mcp/server.py` | Injects `RerankPort` — model-agnostic. ✅ |
| `weebot/application/ports/knowledge_graph_port.py` | No reranking integration yet — future work. ✅ |

---

## Verification plan

### Unit test

```python
# tests/unit/test_rerank_model_refs.py (new file)

import pytest
from weebot.config.model_refs import (
    RERANK_MODEL_FREE,
    RERANK_MODEL_PRO,
    get_rerank_model_for,
)

def test_rerank_model_free_is_nvidia_nemotron():
    """RERANK_MODEL_FREE points to the NVIDIA Nemotron 1B free model."""
    assert RERANK_MODEL_FREE == "nvidia/llama-nemotron-rerank-vl-1b-v2:free"

def test_quality_cases_use_pro():
    """Quality-sensitive use cases still use RERANK_MODEL_PRO."""
    for case in ("research", "skills", "evaluation"):
        assert get_rerank_model_for(case) == RERANK_MODEL_PRO

def test_throughput_cases_use_free():
    """High-throughput, low-criticality cases use RERANK_MODEL_FREE."""
    for case in ("search", "compressor", "memory", "knowledge"):
        assert get_rerank_model_for(case) == RERANK_MODEL_FREE

def test_unknown_case_defaults_to_free():
    """Unknown/unmapped use case defaults to free model (failsafe = cheapest)."""
    assert get_rerank_model_for("nonexistent") == RERANK_MODEL_FREE

def test_model_is_in_registry():
    """The free model is registered in the model registry."""
    from weebot.config.model_registry import get_model_info
    info = get_model_info(RERANK_MODEL_FREE)
    assert info is not None
    assert info.model_name == "nvidia/llama-nemotron-rerank-vl-1b-v2:free"
    assert info.input_cost_per_token == 0.0
    assert info.output_cost_per_token == 0.0
```

### Integration test (manual)

1. **Set `OPENROUTER_API_KEY`** in `.env`
2. **Run:** `python -c "from weebot.config.model_refs import RERANK_MODEL_FREE; print(RERANK_MODEL_FREE)"` → should print `nvidia/llama-nemotron-rerank-vl-1b-v2:free`
3. **Run:** `python -c "
import asyncio
from weebot.infrastructure.adapters.openrouter_rerank_adapter import OpenRouterRerankAdapter
async def test():
    adapter = OpenRouterRerankAdapter()
    results = await adapter.rerank(
        query='What is the capital of France?',
        documents=['Paris is the capital of France.', 'London is in England.', 'Berlin is in Germany.']
    )
    for r in results:
        print(f'  [{r.score:.4f}] {r.document}')
    # Expected: top result should be the Paris document with highest score
asyncio.run(test())
"` → rerank call succeeds with scores
4. **Verify regression:** `python -m pytest tests/unit/test_step_result_validator.py -v` → all 22 pass
5. **Verify import:** `python -m pytest tests/unit/test_rerank_model_refs.py -v` → all 5 new tests pass

---

## Execution order

1. **Change 1** — Add `RERANK_MODEL_FREE` constant in `model_refs.py` (enables all other changes)
2. **Change 2** — Update `get_rerank_model_for()` in `model_refs.py`
3. **Verification** — Run unit tests for model_refs (new test file)
4. **Change 3** — Update adapter default in `openrouter_rerank_adapter.py`
5. **Change 4** — Update `web_search.py` to use `get_rerank_model_for("search")`
6. **Change 5** — Update log message in `di/_skills.py`
7. **Verification** — Run full integration smoke test
8. **Verification** — Run existing test suite (`pytest tests/ -v`) to confirm no regressions

---

## Rollback plan

- **Change 1 + 2:** `git checkout -- weebot/config/model_refs.py`
- **Change 3:** `git checkout -- weebot/infrastructure/adapters/openrouter_rerank_adapter.py`
- **Change 4:** `git checkout -- weebot/tools/web_search.py`
- **Change 5:** `git checkout -- weebot/application/di/_skills.py`

All changes are a single constant-swap or function-call swap each. No structural refactoring. Rollback is `git checkout` on each file independently.

---

## Layer-impact summary

| Change | Layer | Dependency direction |
|--------|-------|---------------------|
| `model_refs.py` constants | Config | No code deps |
| `model_refs.py` `get_rerank_model_for()` | Config | No code deps |
| `openrouter_rerank_adapter.py` default | Infrastructure | Config → Infra ✓ (existing pattern) |
| `web_search.py` model lookup | Tools | Config → Tools ✓ |
| `di/_skills.py` log message | Application (DI) | No code deps |

No cross-layer violations. No new import directions. All changes are internal to existing layers.
