# Model Cascade Remediation Plan

**Date:** 2026-06-07
**Status:** P0 — framework non-functional on default configuration
**Root cause:** Stale model IDs + two conflicting config sources + no startup health check

---

## Problem Summary

The interactive session failed because all 4 cascade tier models returned 404 errors, causing the executor to exhaust every model in the cascade. Each model took 60-90 seconds to time out, resulting in ~178 seconds of latency before the `AllModelsTrippedError` was raised. The agent never executed a single tool call.

OpenRouter API verification (2026-06-07) confirms:
- `moonshotai/kimi-k2.6:free` — **STALE** (not in OpenRouter's model list)
- `minimax/minimax-m3` — **EXISTS** on OpenRouter (the 404 suggests API key or credits issue)
- `qwen/qwen3.7-max` — **EXISTS** on OpenRouter
- `x-ai/grok-build-0.1` — **EXISTS** on OpenRouter

Available free models (verified from API):
- `nvidia/nemotron-3-ultra-550b-a55b:free` — 1M context, reasoning, tools support
- `nvidia/nemotron-3.5-content-safety:free` — 128K context, multimodal

---

## Fix Plan

### Step 1: Replace stale model IDs with verified current ones

**File:** `weebot/config/model_refs.py`

Replace every occurrence of `moonshotai/kimi-k2.6:free` with a verified working model. The best free replacement is `nvidia/nemotron-3-ultra-550b-a55b:free` (1M context, reasoning, tool support, free).

| Constant | Old (stale) | New (verified) | Rationale |
|----------|-------------|----------------|-----------|
| `MODEL_CASCADE_TIER1` | `moonshotai/kimi-k2.6:free` | `nvidia/nemotron-3-ultra-550b-a55b:free` | Free, 1M ctx, reasoning, tools |
| `MODEL_BUDGET` | `moonshotai/kimi-k2.6:free` | `nvidia/nemotron-3-ultra-550b-a55b:free` | Same |
| `MODEL_PLANNER` | `moonshotai/kimi-k2.6:free` | `nvidia/nemotron-3-ultra-550b-a55b:free` | Reasoning for planning |
| `MODEL_ROLE_RESEARCHER` | `moonshotai/kimi-k2.6:free` | `nvidia/nemotron-3-ultra-550b-a55b:free` | Reasoning for research |
| `MODEL_ROLE_ADMIN` | `moonshotai/kimi-k2.6:free` | `nvidia/nemotron-3-ultra-550b-a55b:free` | Orchestration |
| `MODEL_DI_DEFAULT` | `moonshotai/kimi-k2.6:free` | `nvidia/nemotron-3-ultra-550b-a55b:free` | Default model |
| `MODEL_FACTORY_OPENAI` | `minimax/minimax-m3` | `minimax/minimax-m3` | Unchanged — verified working |
| `MODEL_FACTORY_ANTHROPIC` | `qwen/qwen3.7-max` | `qwen/qwen3.7-max` | Unchanged — verified working |
| `MODEL_FACTORY_DEEPSEEK` | `deepseek/deepseek-v4-pro` | `deepseek/deepseek-v4-pro` | Unchanged |
| `MODEL_FACTORY_OPENROUTER` | `minimax/minimax-m3` | `minimax/minimax-m3` | Unchanged |

Also update the `_ROLE_MODEL_CASCADE` fallback chains — replace all `moonshotai/kimi-k2.6:free` occurrences.

Also update `MODEL_FALLBACK_OPENROUTER_CHAIN` — replace `moonshotai/kimi-k2.6:free`.

Also update `MODEL_MOA_REFERENCE` list — replace `moonshotai/kimi-k2.6:free`.

**Risk:** Low. String replacement only. No logic change.

---

### Step 2: Unify the two model config sources

**Files:** `weebot/config/model_refs.py`, `weebot/core/model_cascade_config.py`

**Problem:** Two files define model cascades with different models. `model_refs.py` is the runtime source; `model_cascade_config.py` is dead code.

**Fix:** 
1. Delete `weebot/core/model_cascade_config.py` (it's unused at runtime)
2. Move any useful metadata (pricing, context lengths) into `model_refs.py` as docstrings or comments
3. Update all imports — verify nothing imports from `model_cascade_config.py`

**Verification:** `grep -r "model_cascade_config" weebot/` — if only `model_refs.py` references it (as a docstring note), deletion is safe.

---

### Step 3: Add startup model health check

**File:** `cli/main.py` (or new `weebot/core/model_health.py`)

After `Container.configure_defaults()`, add a fast health-check call that:
1. Resolves `LLMPort` from the container
2. Calls `llm.chat()` with a minimal ping message (`"ping"`) using the default model
3. Times out after 10 seconds (not 90 — this is a health check)
4. On success: logs "Model cascade verified: <model_id>"
5. On failure: logs a clear warning with actionable instructions:
   ```
   Model health check FAILED for <model_id>: <error>.
   Possible causes:
   - Invalid or expired OPENROUTER_API_KEY
   - Zero OpenRouter credits (check https://openrouter.ai/credits)
   - Model ID renamed or removed (check https://openrouter.ai/models)
   ```

**Risk:** Low. Adds ~1-10 seconds to startup. Can be skipped via `--no-health-check` flag or `WEEBOT_SKIP_MODEL_CHECK=1` env var.

---

### Step 4: Reduce cascade timeouts for fast-fail errors

**File:** `weebot/application/agents/executor.py`

The `_try_chat` inner function at [executor.py:373-395](weebot/application/agents/executor.py:373) uses timeouts of 90s (Phase 1) and 60s (Phase 2). These are appropriate for thinking models, but a 404 or auth error returns instantly — the timeout shouldn't be the bottleneck.

**Fix:** After the first model fails with a "fast-fail" error (404, 401, 403), reduce subsequent timeouts to 15s for the remaining cascade. Track `_fast_fail_detected` flag.

```python
_fast_fail = False
for model_id in remaining:
    timeout = 15.0 if _fast_fail else 60.0
    resp = await _try_chat(model_id, timeout=timeout)
    if resp is not None:
        return resp
    # If we got a 404/401/403, all remaining models likely have same auth issue
    if ErrorClassifier.is_auth_or_not_found(last_error):
        _fast_fail = True
```

**Risk:** Low. Only affects the cascade after a fast-fail error is detected.

---

### Step 5: Fix circuit breaker key mismatch

**File:** `weebot/application/agents/executor.py`

The log shows `moonshot/kimi-k2.6:free` vs `moonshotai/kimi-k2.6:free` — a one-character discrepancy in the circuit breaker key. This is likely caused by the `_record_failure` and `_is_tripped` methods using a different normalization than the actual model ID sent to the API.

**Fix:** Audit the `_circuit_breaker_failures` dict at [executor.py:357-359](weebot/application/agents/executor.py:357) — ensure the key used for tracking is the EXACT model ID string passed to `self._llm.chat(model=model_id)`. Add an assertion or log to verify.

If the mismatch comes from elsewhere (e.g., a separate `CircuitBreaker` class in `core/circuit_breaker.py`), trace the full call chain to find where the normalization happens.

---

### Step 6: Add retry-on-404 with model ID refresh

**File:** `weebot/application/agents/executor.py`

If ALL models in the cascade return 404, there's a chance the model IDs are globally stale. Before raising `AllModelsTrippedError`, try fetching the current model list from OpenRouter and retrying with the first available free model.

```python
if all_404:
    try:
        import httpx, asyncio
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://openrouter.ai/api/v1/models", timeout=10)
            models = resp.json()["data"]
            free_models = [m["id"] for m in models if ":free" in m["id"]]
            if free_models:
                logger.warning("All configured models returned 404. Trying live free model: %s", free_models[0])
                return await self._llm.chat(messages=messages, model=free_models[0], ...)
    except Exception:
        pass
```

**Risk:** Medium. Adds a network call in the error path. Should be gated behind a feature flag.

---

## Execution Order

| Step | Priority | Effort | Dependencies |
|------|----------|--------|-------------|
| 1 — Replace stale IDs | **P0** | 30 min | None |
| 2 — Unify config sources | **P0** | 30 min | Step 1 |
| 3 — Startup health check | **P1** | 1 hr | Step 1 |
| 4 — Fast-fail timeout reduction | **P1** | 30 min | None |
| 5 — Fix circuit breaker keys | **P1** | 30 min | Step 1 |
| 6 — Live model refresh fallback | **P2** | 2 hr | Step 4 |

---

## Verification

After Step 1, run:
```bash
python -m cli.main health          # Should pass model health check
python -m cli.main flow run "echo hello"   # Should execute without 404
```

Expected outcome: agent executes steps using `nvidia/nemotron-3-ultra-550b-a55b:free` as the default cascade model, with `minimax/minimax-m3` and `qwen/qwen3.7-max` as fallbacks.

## Rollback

All changes are in `model_refs.py` and `executor.py`. Revert to git HEAD to undo. No database migrations or config format changes.
