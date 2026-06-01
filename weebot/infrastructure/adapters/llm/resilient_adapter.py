"""Resilient LLM adapter wrapper with retry, circuit breaker, and timeout."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Callable

from weebot.application.ports.llm_port import LLMPort, LLMResponse
from weebot.core.circuit_breaker import CircuitBreaker, BreakerState
from weebot.core.error_classifier import ErrorClassifier, ErrorCategory
from weebot.infrastructure.observability import metrics as _metrics
from weebot.utils.backoff import RetryWithBackoff, BackoffConfig

# Optional caching support
try:
    from weebot.infrastructure.cache.llm_cache import LLMCache, CacheKey
    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False
    LLMCache = None
    CacheKey = None

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
        cache: Optional[Any] = None,
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
        self._timeout = timeout
        self._enable_caching = enable_caching
        self._cache = cache
        
        # Configure retry with exponential backoff
        if enable_retry:
            self._retry = RetryWithBackoff(
                BackoffConfig(
                    delays=[1, 2, 4, 8, 15, 30],
                    jitter=0.25,
                    retryable=self._is_retryable_error
                )
            )
        else:
            self._retry = None
        
        # Configure circuit breaker
        if enable_circuit_breaker:
            self._circuit = CircuitBreaker(
                failure_threshold=3,
                cooldown_seconds=60.0,
                jitter_percent=0.2
            )
        else:
            self._circuit = None
        
        logger.debug(
            f"Initialized ResilientLLMAdapter for {model_name} "
            f"(timeout={timeout}s, circuit_breaker={enable_circuit_breaker}, "
            f"retry={enable_retry}, caching={enable_caching})"
        )
    
    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = "auto",
        response_format: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
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
        # Step 1: Circuit breaker check
        if self._circuit:
            result = await self._circuit.evaluate(self._model_name)
            if not result.allowed:
                raise CircuitBreakerOpen(
                    f"Circuit open for {self._model_name}: {result.reason}"
                )
        
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
                    max_tokens=max_tokens
                )
            else:
                response = await self._execute_with_timeout(
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    response_format=response_format,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens
                )

            # Duration & success counter
            _duration = asyncio.get_event_loop().time() - _start
            try:
                _metrics.llm_calls_total.labels(model=_model_id, provider=_provider, status="success").inc()
                _metrics.llm_call_duration_seconds.labels(model=_model_id, provider=_provider).observe(_duration)
            except Exception:
                pass

            # Step 4: Record success
            if self._circuit:
                await self._circuit.record_success(self._model_name)

            # Step 5: Cache response
            if cache_key and self._cache:
                try:
                    await self._cache.set(cache_key, response)
                except Exception as e:
                    logger.warning(f"Cache write error: {e}")

            return response

        except asyncio.TimeoutError as e:
            if self._circuit:
                await self._circuit.record_failure(self._model_name)
            try:
                _metrics.llm_calls_total.labels(model=_model_id, provider=_provider, status="timeout").inc()
            except Exception:
                pass
            raise LLMTimeoutError(
                f"Request to {self._model_name} timed out after {self._timeout}s"
            ) from e

        except Exception as e:
            # Auth errors are unrecoverable — fail fast without circuit recording
            if ErrorClassifier.should_fail_fast(e):
                try:
                    _metrics.llm_calls_total.labels(model=_model_id, provider=_provider, status="auth_error").inc()
                except Exception:
                    pass
                raise
            # Record failure if retryable
            if self._circuit and self._is_retryable_error(e):
                await self._circuit.record_failure(self._model_name)
            try:
                _metrics.llm_calls_total.labels(model=_model_id, provider=_provider, status="error").inc()
            except Exception:
                pass
            raise
    
    async def _execute_with_timeout(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = "auto",
        response_format: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
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
            timeout=self._timeout
        )
    
    def _is_retryable_error(self, exc: Exception) -> bool:
        """Delegate retry decision to ErrorClassifier.

        AUTH and CONTEXT_LENGTH are not retryable:
        - AUTH: credentials won't change between retries
        - CONTEXT_LENGTH: compressor must handle this, not blind retry
        - UNKNOWN: preserve safe default of not retrying unknown errors
        """
        cat = ErrorClassifier.classify(exc)
        return cat not in (ErrorCategory.AUTH, ErrorCategory.CONTEXT_LENGTH, ErrorCategory.UNKNOWN)
    
    def _should_cache(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        temperature: Optional[float]
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
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        model: Optional[str],
        temperature: Optional[float]
    ) -> "CacheKey":
        """Create deterministic cache key from request parameters."""
        if not CACHE_AVAILABLE:
            raise RuntimeError("Caching not available")
        
        return CacheKey.from_request(
            messages=messages,
            model=model or self._model_name,
            temperature=temperature or 0.0,
            tools=tools
        )
    
    # -------------------------------------------------------------------------
    # Inspection API
    # -------------------------------------------------------------------------
    
    def get_circuit_state(self) -> Optional[str]:
        """Get current circuit breaker state for this model."""
        if self._circuit:
            state = self._circuit.get_state(self._model_name)
            return state.value
        return None
    
    def get_metrics(self) -> Dict[str, Any]:
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
            circuit_metrics = self._circuit.get_metrics()
            metrics["circuit_metrics"] = circuit_metrics
        
        return metrics
    
    async def reset_circuit(self) -> None:
        """Manually reset circuit breaker to CLOSED state."""
        if self._circuit:
            await self._circuit.reset(self._model_name)
            logger.info(f"Circuit breaker reset for {self._model_name}")
