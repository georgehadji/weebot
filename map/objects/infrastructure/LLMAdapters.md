---
type: object
name: LLM adapters (factory + resilience layer)
code: AdapterFactory, ResilientLLMAdapter
cluster: infrastructure
universe: live
status: verified
verified: 2026-10-24
commit: eeb0e80e
---

# LLM adapters

`create_adapter(provider, model)` returns an `LLMPort` that is always a `ResilientLLMAdapter` wrapping a concrete provider adapter. Concrete adapters (OpenAI, Anthropic, DeepSeek, Moonshot, OpenRouter) turn one `chat(...)` call into a provider request; the wrapper adds timeout, retry with backoff and a per-model circuit breaker. The container then wraps that result in a `BoundedLLMAdapter` (bulkhead, below).

## Why this shape
Resilience is added in one place, so provider adapters stay plain (`weebot/infrastructure/adapters/llm/adapter_factory.py:26-43`). The layering exists because stacking retry layers multiplied: the source records that one logical `chat()` once issued **210** HTTP requests (cascade × backoff × OpenAI's own 10-model chain × SDK retries) and that the cascade could receive an answer from a model it never chose; `apply_client_policy` now sets SDK retries to 0, passes the timeout to the SDK client and disables the OpenAI adapter's private model fallback (`_client_policy.py:1-28`, `adapter_factory.py:166-175`, regression test `tests/unit/adapters/test_retry_amplification.py`).

## Shape
`AdapterFactory.create_adapter` (`adapter_factory.py:116`):
1. Cache lookup keyed `provider:model:api_key:caching-flag` (`:145-154`).
2. Provider defaults for timeout and model (`:54-73`, applied `:156-159`): openai 60 s, anthropic 90, deepseek 120, moonshot 180, xai 120, openrouter 180.
3. `_create_inner_adapter` (`:215-326`) by provider. deepseek, moonshot and xai return a `DirectOrFallbackAdapter` (direct provider first, OpenRouter on failure) **only if** the direct API key is set, else OpenRouter alone (`:240-312`). minimax always goes via OpenRouter (`:281-288`). Any other `vendor/model` id is built as an OpenRouter id (`:317-323`); a provider with no `/` in the model raises `ValueError` (`:326`).
4. `apply_client_policy(inner, timeout, sdk_max_retries=0, model_fallback=False)` (`:173-175`).
5. If caching is on and the model supports it, wrap in `CachingLLMAdapter` (Anthropic prompt-caching breakpoints) (`:186-190`).
6. Wrap in `ResilientLLMAdapter` (`:197-208`).

`ResilientLLMAdapter.chat` (`resilient_adapter.py:167-331`): trace span → circuit check (key = the runtime `model` argument, else the adapter's model, so each cascade tier has its own breaker, `:213, 220-224`) → optional cache lookup (`:226-236`) → `_execute_with_timeout` inside `RetryWithBackoff` with delays `[1, 2, 4, 8, 15, 30]` s and 25% jitter (`:140-148`); the retry stops scheduling a sleep that would cross the deadline the cascade set around the call (`weebot/utils/backoff.py:82-83`, set at `application/agents/executor/_cascade.py:348`) → success resets the breaker. Breaker: 3 failures, 60 s cooldown, 20% jitter (`:152-154`).
Error handling: timeout → `LLMTimeoutError`, counted as a breaker failure (`:291-302`); fail-fast errors (auth) skip the breaker, credentials are redacted from the message and an HTTP 401 is re-raised as the domain type `LLMAuthenticationError` (`:304-320`); other retryable errors count against the breaker (`:322-323`); every error message is passed through `_sanitize_error` (`:313, 330`).

Configuration is read from environment variables in the factory (`LLM_TIMEOUT`, `LLM_ENABLE_CIRCUIT_BREAKER`, `LLM_ENABLE_RETRY`, `LLM_ENABLE_CACHING`, `:91-96, 101-114`); provider keys come from `WeebotSettings` first, then `os.getenv` (`:357-388`). One flag, `LLM_ENABLE_CACHING`, switches both prompt caching and response caching (`:181-185`).

## Bulkhead (outside this layer)
`FactoriesMixin._bounded_llm` wraps every LLM the container builds in `BoundedLLMAdapter`, so each `chat()` takes a slot in the shared `LLMPool` and logs one `llm_call` record (`weebot/application/di/_factories.py:110-133`; `weebot/application/strategies/llm_pool.py:61-236`). A call already inside the cascade's slot passes through (`:116-146`). Code that needs the concrete adapter calls `unwrap_llm` (`:324-328`; `weebot/interfaces/web/main.py:366`). Pinned by `tests/stress/test_llm_bulkhead.py:171`.

## Local models (off unless `OLLAMA_ENABLED`)
`create_adapter` wraps the finished adapter in `LocalModelRouter` only when Ollama is on (`weebot/infrastructure/adapters/llm/adapter_factory.py:219`, switch at `:414`). The router sends `ollama/<tag>` ids to a second adapter built on first use and strips the prefix (`weebot/infrastructure/adapters/llm/local_router_adapter.py:19, 47-49`); the `ollama` provider branch is an `OpenAIAdapter` on `OLLAMA_BASE_URL` with a dummy key (`adapter_factory.py:328`). `unwrap_llm` sees through the router via `_llm_wrapper`. `OLLAMA_ROLES` maps roles to tags, so a local and a `-cloud` tag can serve different roles (`weebot/config/local_models.py:30`; first in the role cascade, `weebot/config/model_refs.py:158`); a `-cloud` tag runs on Ollama's servers. Setup and role choice: `docs/OLLAMA.md`.

## Connected to
- **Port:** `LLMPort` (`application/ports/llm_port.py`).
- **Created by** `FactoriesMixin._create_llm` (`application/di/_factories.py:144-150`, provider from `ModelProvider.from_model_name`), `di/_skillopt.py:137-142` and `FactoriesMixin.create_llm_for_model` (`_factories.py:127-142`, the public per-model route) — all bounded by `_bounded_llm` (`_factories.py:110-125`). Role adapters (critic, verifier) are built with `_create_llm_for_role` (`_factories.py:247-256`). Nothing outside `application/di/` constructs one: `test_the_adapter_factory_is_only_called_by_the_composition_root` fails if anything does (WB-02).
- **Consumed by** `CascadeExecutor` (which has its **own** per-model breaker, tripped at 5, see its card), `PlannerAgent`, the verifier and critic services.
- **Looks like but is not:** `CascadeExecutor` (chooses *which* model; this layer makes one model reliable); `ProviderAccountPort` / `OpenRouterAccountAdapter` (credits and model list, not chat).

## If you change this
**Hits:** every LLM call in the system; cascade timing (the cascade's per-call timeouts wrap this layer's own timeout and retries); cost and request counts (retries here are billed); error types the application catches (`LLMAuthenticationError`, `CircuitBreakerOpen`, `LLMTimeoutError`); tests `tests/unit/adapters/test_retry_amplification.py`, `tests/stress/test_llm_resilience.py`, `tests/integration/test_real_api.py`, `tests/integration/test_real_api_openrouter.py`.
**Does not hit:** state persistence; flow states; the cascade's model ordering.

## Surfaces
Indirect. Provider choice is driven by model names and API keys in `.env`.

## See
`weebot/infrastructure/adapters/llm/adapter_factory.py`, `weebot/infrastructure/adapters/llm/resilient_adapter.py`
