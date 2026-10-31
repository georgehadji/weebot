---
type: object
name: LLM adapters (factory + resilience layer)
code: AdapterFactory, ResilientLLMAdapter
cluster: infrastructure
universe: live
status: verified
verified: 2026-10-30
commit: 8e6d1cca
---

# LLM adapters

`create_adapter(provider, model)` returns an `LLMPort` that is always a `ResilientLLMAdapter` wrapping a concrete provider adapter. Concrete adapters (OpenAI, Anthropic, DeepSeek, Moonshot, OpenRouter; the `ollama` and `free` providers reuse `OpenAIAdapter` on another base URL) turn one `chat(...)` call into a provider request; the wrapper adds timeout, retry with backoff and a per-model circuit breaker. The container then wraps that result in a `BoundedLLMAdapter` (bulkhead, below).

## Why this shape
Resilience is added in one place, so provider adapters stay plain (`weebot/infrastructure/adapters/llm/adapter_factory.py:30-47`). The layering exists because stacking retry layers multiplied: the source records that one logical `chat()` once issued **210** HTTP requests (cascade × backoff × OpenAI's own 10-model chain × SDK retries) and that the cascade could receive an answer from a model it never chose; `apply_client_policy` now sets SDK retries to 0, passes the timeout to the SDK client and disables the OpenAI adapter's private model fallback (`_client_policy.py:1-28`, `adapter_factory.py:174-183`, regression test `tests/unit/adapters/test_retry_amplification.py`).

## Shape
`AdapterFactory.create_adapter` (`adapter_factory.py:124`):
1. Cache lookup keyed `provider:model:api_key:caching-flag` (`:153-162`).
2. Provider defaults for timeout and model (`:57-81`, applied `:164-167`): openai 60 s, anthropic 90, deepseek 120, moonshot 180, xai 120, openrouter 180, ollama 300, free 60.
3. `_create_inner_adapter` (`:238-377`) by provider. deepseek, moonshot and xai return a `DirectOrFallbackAdapter` (direct provider first, OpenRouter on failure) **only if** the direct API key is set, else OpenRouter alone (`:263-335`). minimax always goes via OpenRouter (`:304-311`). `ollama` and `free` are described under Local models (`:340-366`). Any other `vendor/model` id is built as an OpenRouter id (`:368-374`); a provider with no `/` in the model raises `ValueError` (`:377`).
4. `apply_client_policy(inner, timeout, sdk_max_retries=0, model_fallback=False)` (`:181-183`).
5. If caching is on and the model supports it, wrap in `CachingLLMAdapter` (Anthropic prompt-caching breakpoints) (`:194-198`).
6. Wrap in `ResilientLLMAdapter` (`:205-217`); `retry_rate_limits` is off for provider `free`.
7. When Ollama or free roles are switched on, wrap in `LocalModelRouter` (`:219-231`).

`ResilientLLMAdapter.chat` (`resilient_adapter.py:174-338`): trace span → circuit check (key = the runtime `model` argument, else the adapter's model, so each cascade tier has its own breaker, `:220, 227-231`) → optional cache lookup (`:233-243`) → `_execute_with_timeout` inside `RetryWithBackoff` with delays `[1, 2, 4, 8, 15, 30]` s and 25% jitter (`:147-155`); the retry stops scheduling a sleep that would cross the deadline the cascade set around the call (`weebot/utils/backoff.py:82-83`, set at `application/agents/executor/_cascade.py:393`) → success resets the breaker. Breaker: 3 failures, 60 s cooldown, 20% jitter (`:159-161`).
Retry policy is built per call (`_retry_for_one_call`, `:364-385`): a timeout is retried at most once, a 429 is handed straight back when `retry_rate_limits` is off (free tiers), other retryable errors follow the delay ladder. Error handling: timeout → `LLMTimeoutError`, counted as a breaker failure (`:298-309`); fail-fast errors (auth) skip the breaker, credentials are redacted from the message and an HTTP 401 is re-raised as the domain type `LLMAuthenticationError` (`:311-327`); other retryable errors count against the breaker (`:328-330`); every error message is passed through `_sanitize_error` (`:320, 337`).

Configuration is read from environment variables in the factory (`LLM_TIMEOUT`, `LLM_ENABLE_CIRCUIT_BREAKER`, `LLM_ENABLE_RETRY`, `LLM_ENABLE_CACHING`, `:99-104, 109-122`); provider keys come from `WeebotSettings` first, then `os.getenv` (`:408-439`). One flag, `LLM_ENABLE_CACHING`, switches both prompt caching and response caching (`:189-194`).

## Bulkhead (outside this layer)
`FactoriesMixin._bounded_llm` wraps every LLM the container builds in `BoundedLLMAdapter`, so each `chat()` takes a slot in the shared `LLMPool` and logs one `llm_call` record (`weebot/application/di/_factories.py:133-148`; `weebot/application/strategies/llm_pool.py:62-290`). A call already inside the cascade's slot passes through (`llm_pool.py:117-149`). Code that needs the concrete adapter calls `unwrap_llm` (`llm_pool.py:348-353`; `weebot/interfaces/web/main.py:267, 370`). Pinned by `tests/stress/test_llm_bulkhead.py:171`.

## Local models (off unless `OLLAMA_ENABLED`)
`create_adapter` wraps the finished adapter in `LocalModelRouter` only when Ollama is on or `WEEBOT_FREE_ROLES` names a role with its key set (`weebot/infrastructure/adapters/llm/adapter_factory.py:219-231`, switches at `:442` and `:452`). The router sends `ollama/<tag>` ids to a second adapter built on first use and `free/<provider>/<model>` ids to that provider's adapter, stripping the prefix (`weebot/infrastructure/adapters/llm/local_router_adapter.py:57-62`); the `ollama` provider branch is an `OpenAIAdapter` on `OLLAMA_BASE_URL` with a dummy key (`adapter_factory.py:340-350`), and the `free` branch an `OpenAIAdapter` on the provider's URL with its own key, refusing without one so the OpenRouter key never leaks (`adapter_factory.py:352-366`); `ModelProvider.from_model_name` maps both prefixes (`weebot/config/model_registry.py:69-72`). `unwrap_llm` sees through the router via `_llm_wrapper`. `OLLAMA_ROLES` maps roles to tags, so a local and a `-cloud` tag can serve different roles (`weebot/config/local_models.py:31`); `WEEBOT_FREE_ROLES` maps roles to Groq or Gemini models (`weebot/config/free_models.py:80`). Both go first in the role cascade, Ollama then free (`weebot/config/model_refs.py:154`); a `-cloud` tag runs on Ollama's servers, and Gemini's free tier may train on prompts, so the cascade drops it, and any OpenRouter `:free` variant, for a session that read untrusted content (`keep_private`, `weebot/application/agents/executor/_session_scope.py:165-179`). Single-model callers skip free ids (`role_primary_model`, `weebot/config/model_refs.py:163-169`). Setup and role choice: `docs/OLLAMA.md`.

## Connected to
- **Port:** `LLMPort` (`application/ports/llm_port.py`).
- **Created by** `FactoriesMixin._create_llm` (`application/di/_factories.py:167-173`, provider from `ModelProvider.from_model_name`), `di/_skillopt.py:137-142` and `FactoriesMixin.create_llm_for_model` (`_factories.py:150-165`, the public per-model route) — all bounded by `_bounded_llm` (`_factories.py:133-148`). Role adapters (critic, verifier) are built with `_create_llm_for_role` (`_factories.py:270-281`). Nothing outside `application/di/` constructs one: `test_the_adapter_factory_is_only_called_by_the_composition_root` fails if anything does (WB-02).
- **Consumed by** `CascadeExecutor` (which has its **own** per-model breaker, tripped at 5, see its card), `PlannerAgent`, the verifier and critic services.
- **Looks like but is not:** `CascadeExecutor` (chooses *which* model; this layer makes one model reliable); `ProviderAccountPort` / `OpenRouterAccountAdapter` (credits and model list, not chat).

## If you change this
**Hits:** every LLM call in the system; cascade timing (the cascade's per-call timeouts wrap this layer's own timeout and retries); cost and request counts (retries here are billed); error types the application catches (`LLMAuthenticationError`, `CircuitBreakerOpen`, `LLMTimeoutError`); tests `tests/unit/adapters/test_retry_amplification.py`, `tests/stress/test_llm_resilience.py`, `tests/integration/test_real_api.py`, `tests/integration/test_real_api_openrouter.py`.
**Does not hit:** state persistence; flow states; the cascade's model ordering.

## Surfaces
Indirect. Provider choice is driven by model names and API keys in `.env`.

## See
`weebot/infrastructure/adapters/llm/adapter_factory.py`, `weebot/infrastructure/adapters/llm/resilient_adapter.py`
