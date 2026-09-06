"""Resilient LLM adapter wrapper with retry, circuit breaker, and timeout."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from weebot.application.ports.llm_port import LLMPort, LLMResponse
from weebot.core.circuit_breaker import CircuitBreaker
from weebot.core.error_classifier import ErrorClassifier
from weebot.infrastructure.observability import metrics as _metrics
from weebot.infrastructure.observability.tracing import get_tracer
from weebot.utils.backoff import RetryWithBackoff, BackoffConfig

# Optional caching support
try:
    from weebot.infrastructure.cache.llm_cache import LLMCache, CacheKey

    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False

# Credential redaction patterns
_CREDENTIAL_REDACTIONS = [
    (
        re.compile(r"(api[_-]?key|token|secret|password)[=:]\s*\S+", re.IGNORECASE),
        r"\1=***REDACTED***",
    ),
    (re.compile(r"(sk-[a-zA-Z0-9]{20,})"), "sk-***REDACTED***"),
]


def _sanitize_error(exc: BaseException) -> None:
    """Redact credential patterns from exception messages in-place."""
    msg = str(exc)
    for pattern, replacement in _CREDENTIAL_REDACTIONS:
        msg = pattern.sub(replacement, msg)
    if msg != str(exc):
        try:
            exc.args = (msg,) + exc.args[1:]
        except (AttributeError, TypeError):
            pass


logger = logging.getLogger(__name__)


class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is open for a model."""

    pass


class LLMTimeoutError(Exception):
    """Raised when LLM request exceeds timeout."""

    pass


class ResilientLLMAdapter(LLMPort):
    """
    Wrapper that adds resilience patterns to any LLM adapter.

    Patterns applied:
    - Exponential backoff retry (weebot/utils/backoff.py)
    - Circuit breaker per model (weebot/core/circuit_breaker.py)
    - Request timeout enforcement
    - Optional request/response caching

    Usage:
        inner = OpenAIAdapter(api_key="...")
        resilient = ResilientLLMAdapter(
            inner_adapter=inner,
            model_name="gpt-4o",
            timeout=60.0,
            enable_circuit_breaker=True,
            enable_retry=True
        )
        response = await resilient.chat(messages=[...])
    """

    def __init__(
        self,
        inner_adapter: LLMPort,
        model_name: str,
        timeout: float = 60.0,
        enable_circuit_breaker: bool = True,
        enable_retry: bool = True,
        enable_caching: bool = False,
        cache: Any | None = None,
    ):
        """
        Initialize resilient adapter wrapper.

        Args:
            inner_adapter: The actual LLM adapter to wrap
            model_name: Identifier for this model (used by circuit breaker)
            timeout: Maximum seconds to wait for a response
            enable_circuit_breaker: Whether to use circuit breaker pattern
            enable_retry: Whether to retry on transient failures
            enable_caching: Whether to cache responses
            cache: Optional custom cache implementation
        """
        self._inner = inner_adapter
        self._model_name = model_name
        self._breaker_keys: set[str] = {model_name} if model_name else set()
        self._timeout = timeout
        self._enable_caching = enable_caching
        self._cache = cache

        # Configure retry with exponential backoff
        if enable_retry:
            self._retry = RetryWithBackoff(
                BackoffConfig(
                    delays=[1, 2, 4, 8, 15, 30], jitter=0.25, retryable=self._is_retryable_error
                )
            )
        else:
            self._retry = None

        # Configure circuit breaker
        if enable_circuit_breaker:
            self._circuit = CircuitBreaker(
                failure_threshold=3, cooldown_seconds=60.0, jitter_percent=0.2
            )
        else:
            self._circuit = None

        logger.debug(
            "Initialized ResilientLLMAdapter for %s (timeout=%ss, circuit_breaker=%s, retry=%s, caching=%s)",
            model_name,
            timeout,
            enable_circuit_breaker,
            enable_retry,
            enable_caching,
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = "auto",
        response_format: dict[str, Any] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """
        Send chat completion request with resilience patterns.

        Flow:
        1. Check circuit breaker state
        2. Check cache (if enabled and applicable)
        3. Execute with timeout and retry
        4. Record success/failure for circuit breaker
        5. Cache response (if enabled)
        """
        tracer = get_tracer(__name__)
        span_name = f"llm.chat.{self._model_name or 'unknown'}"
        with tracer.start_as_current_span(span_name) as span:
            provider = (
                self._model_name.split("/")[0] if "/" in (self._model_name or "") else "unknown"
            )
            span.set_attribute("llm.model", self._model_name or "unknown")
            span.set_attribute("llm.provider", provider)
            return await self._chat_with_tracing(
                messages, tools, tool_choice, response_format, model, temperature, max_tokens
            )

    async def _chat_with_tracing(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = "auto",
        response_format: dict[str, Any] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Inner chat implementation — called inside the trace span."""
        # Use the runtime model parameter for circuit breaker key.
        # This ensures each cascade tier gets its own breaker, preventing
        # one model's failure from poisoning all others.
        _breaker_key: str = model or self._model_name
        # Remembered so `get_metrics` and `reset_circuit` can reach the breakers
        # this adapter has actually driven. Without it they only ever saw
        # `self._model_name`, and a cascade that drives one adapter across
        # several models trips a breaker nobody can see or clear.
        self._breaker_keys.add(_breaker_key)

        # Step 1: Circuit breaker check
        if self._circuit:
            result = await self._circuit.evaluate(_breaker_key)
            if not result.allowed:
                raise CircuitBreakerOpen(f"Circuit open for {_breaker_key}: {result.reason}")

        # Step 2: Check cache
        cache_key = None
        if self._cache and self._should_cache(messages, tools, temperature):
            cache_key = self._make_cache_key(messages, tools, model, temperature)
            try:
                cached = await self._cache.get(cache_key)
                if cached:
                    logger.debug(f"Cache hit for {self._model_name}")
                    return cached
            except Exception as e:
                logger.warning(f"Cache read error: {e}")

        # Step 3: Execute with retry and timeout
        _model_id = model or self._model_name
        _provider = _model_id.split("/")[0] if "/" in _model_id else "unknown"
        _start = asyncio.get_event_loop().time()

        try:
            if self._retry:
                response = await self._retry.call(
                    self._execute_with_timeout,
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    response_format=response_format,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            else:
                response = await self._execute_with_timeout(
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    response_format=response_format,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

            # Duration & success counter
            _duration = asyncio.get_event_loop().time() - _start
            try:
                _metrics.llm_calls_total.labels(
                    model=_model_id, provider=_provider, status="success"
                ).inc()
                _metrics.llm_call_duration_seconds.labels(
                    model=_model_id, provider=_provider
                ).observe(_duration)
            except Exception:
                pass

            # Step 4: Record success (per-model breaker key)
            if self._circuit:
                await self._circuit.record_success(_breaker_key)

            # Step 5: Cache response
            if cache_key and self._cache:
                try:
                    await self._cache.set(cache_key, response)
                except Exception as e:
                    logger.warning(f"Cache write error: {e}")

            return response

        except TimeoutError as e:
            if self._circuit:
                await self._circuit.record_failure(_breaker_key)
            try:
                _metrics.llm_calls_total.labels(
                    model=_model_id, provider=_provider, status="timeout"
                ).inc()
            except Exception:
                pass
            raise LLMTimeoutError(
                f"Request to {self._model_name} timed out after {self._timeout}s"
            ) from e

        except Exception as e:
            # Auth errors are unrecoverable — fail fast without circuit recording
            if ErrorClassifier.should_fail_fast(e):
                try:
                    _metrics.llm_calls_total.labels(
                        model=_model_id, provider=_provider, status="auth_error"
                    ).inc()
                except Exception:
                    pass
                _sanitize_error(e)
                raise
            # Record failure if retryable (per-model breaker key)
            if self._circuit and self._is_retryable_error(e):
                await self._circuit.record_failure(_breaker_key)
            try:
                _metrics.llm_calls_total.labels(
                    model=_model_id, provider=_provider, status="error"
                ).inc()
            except Exception:
                pass
            _sanitize_error(e)
            raise

    async def _execute_with_timeout(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = "auto",
        response_format: dict[str, Any] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Execute inner adapter with timeout enforcement."""
        return await asyncio.wait_for(
            self._inner.chat(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                response_format=response_format,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            ),
            timeout=self._timeout,
        )

    def _is_retryable_error(self, exc: Exception) -> bool:
        """Delegate retry decision to ErrorClassifier using the action ladder.

        Uses ``ErrorClassifier.is_retryable()`` which checks whether the
        recommended ``RecoveryAction`` is one of: RETRY, BACKOFF, COMPRESS,
        or FALLBACK_MODEL. Errors with FAIL_FAST or ESCALATE actions
        (auth, bad requests, content filters, tool errors) are not retried.
        """
        return ErrorClassifier.is_retryable(exc)

    def _should_cache(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float | None,
    ) -> bool:
        """
        Determine if this request should be cached.

        Don't cache:
        - Requests with temperature > 0 (non-deterministic)
        - Streaming requests (not supported yet)
        """
        if temperature is not None and temperature > 0:
            return False
        return True

    def _make_cache_key(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        temperature: float | None,
    ) -> CacheKey:
        """Create deterministic cache key from request parameters."""
        if not CACHE_AVAILABLE:
            raise RuntimeError("Caching not available")

        return CacheKey.from_request(
            messages=messages,
            model=model or self._model_name,
            temperature=temperature or 0.0,
            tools=tools,
        )

    # -------------------------------------------------------------------------
    # Inspection API
    # -------------------------------------------------------------------------

    def get_circuit_state(self, model: str | None = None) -> str | None:
        """Get the circuit state for *model*, defaulting to the configured one.

        `chat` keys the breaker on the RUNTIME model (`model or
        self._model_name`) so each cascade tier gets its own, which is
        deliberate. This used to read `self._model_name` unconditionally, so
        when the cascade drove one adapter across several models it reported a
        breaker that had never been touched -- CLOSED, while requests were being
        rejected by a different one. Passing no model keeps the old behaviour.
        """
        if self._circuit:
            return self._circuit.get_state(model or self._model_name).value
        return None

    def get_metrics(self) -> dict[str, Any]:
        """Get resilience metrics for this adapter."""
        metrics = {
            "model": self._model_name,
            "timeout": self._timeout,
            "circuit_breaker_enabled": self._circuit is not None,
            "retry_enabled": self._retry is not None,
            "caching_enabled": self._enable_caching,
        }

        if self._circuit:
            metrics["circuit_state"] = self._circuit.get_state(self._model_name).value
            # Every key this adapter has driven, not just the configured name.
            # `circuit_state` above is kept as-is so existing readers are
            # unaffected; it is the one that can be misleading under a cascade.
            metrics["circuit_states"] = {
                key: self._circuit.get_state(key).value for key in sorted(self._breaker_keys)
            }
            circuit_metrics = self._circuit.get_metrics()
            metrics["circuit_metrics"] = circuit_metrics

        return metrics

    async def reset_circuit(self, model: str | None = None) -> None:
        """Manually reset a circuit breaker to CLOSED.

        With no *model*, every breaker this adapter has driven is reset -- not
        only `self._model_name`. This is the manual recovery lever, and under a
        cascade the breaker that opened is keyed on a runtime model, so the
        old single-key version reset something that had never opened and left
        the real one closed to traffic. Resetting more is safe here: these are
        exactly the keys this adapter opened, never another component's.
        """
        if not self._circuit:
            return
        keys = [model] if model else sorted(self._breaker_keys)
        for key in keys:
            await self._circuit.reset(key)
            logger.info("Circuit breaker reset for %s", key)
