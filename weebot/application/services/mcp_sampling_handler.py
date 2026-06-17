"""MCP Sampling Handler — processes sampling/createMessage requests from MCP servers.

When an MCP server requests an LLM sampling via the `sampling/createMessage`
notification, this handler dispatches the request through Weebot's configured
LLM provider with rate limiting, model allowlists, and token caps.

The handler is pluggable so that different sampling policies can be applied
per MCP server (configured via MCPSamplingPolicy in the server config).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from weebot.domain.models.mcp import MCPSamplingPolicy

logger = logging.getLogger(__name__)


class SamplingRequest:
    """Represents an MCP sampling/createMessage request.

    Mirrors the JSON-RPC params from the MCP specification.
    """

    def __init__(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        stop_sequences: list[str] | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
        include_context: dict[str, Any] | None = None,
        temperature: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.messages = messages
        self.max_tokens = max_tokens
        self.stop_sequences = stop_sequences or []
        self.model = model
        self.system_prompt = system_prompt
        self.include_context = include_context or {}
        self.temperature = temperature
        self.metadata = metadata or {}


@dataclass
class SamplingResult:
    """Result of a sampling/createMessage operation."""
    content: list[dict[str, Any]]
    model: str
    stop_reason: str | None = None
    usage: dict[str, int] | None = None


class RateLimiter:
    """Simple token-bucket rate limiter for sampling requests."""

    def __init__(self, rate_per_minute: int) -> None:
        self._rate = rate_per_minute
        self._tokens: float = float(rate_per_minute)
        self._last_refill: float = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        """Try to acquire a token. Returns True if allowed, False if rate-limited."""
        if self._rate <= 0:
            return True  # Unlimited
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._rate, self._tokens + elapsed * (self._rate / 60.0))
            self._last_refill = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False


class MCPSamplingHandler:
    """Handles MCP sampling/createMessage requests.

    Dispatches LLM calls through Weebot's LLM provider, applying
    per-server rate limits and model allowlists.  Can be extended
    with an actual LLM port reference for real inference.
    """

    def __init__(
        self,
        llm_provider: Any | None = None,
        audit_log: logging.Logger | None = None,
    ) -> None:
        self._llm_provider = llm_provider
        self._audit_log = audit_log or logger
        self._rate_limiters: dict[str, RateLimiter] = {}

    def _get_rate_limiter(self, server_name: str, policy: MCPSamplingPolicy) -> RateLimiter:
        if server_name not in self._rate_limiters:
            self._rate_limiters[server_name] = RateLimiter(policy.rate_limit_per_minute)
        return self._rate_limiters[server_name]

    def _check_model_allowlist(
        self, server_name: str, model: str | None, policy: MCPSamplingPolicy
    ) -> str | None:
        """Check if *model* is allowed by the policy. Returns the resolved model name.

        Returns None if the model is rejected by the allowlist.
        When allowlist is None (no restrictions), returns the requested model
        or 'default' if no model was specified.
        """
        if policy.model_allowlist is None:
            return model or "default"  # Allow any model

        candidate = model or "default"
        for allowed in policy.model_allowlist:
            if candidate == allowed or candidate.endswith(f"/{allowed}"):
                return candidate

        logger.warning(
            "MCP server %s requested sampling with model %r, "
            "which is not in its allowlist: %s",
            server_name, candidate, policy.model_allowlist,
        )
        return None

    async def handle_sampling(
        self,
        server_name: str,
        request: SamplingRequest,
        policy: MCPSamplingPolicy,
    ) -> SamplingResult | None:
        """Process a sampling/createMessage request from *server_name*.

        Returns None if the request is denied (rate-limited, model not allowed,
        or sampling disabled).
        """
        if not policy.enabled:
            logger.info("Sampling disabled for server %s — denying request", server_name)
            return None

        # Rate limit
        limiter = self._get_rate_limiter(server_name, policy)
        allowed = await limiter.acquire()
        if not allowed:
            self._audit_log.warning(
                "Rate-limited sampling request from MCP server %s", server_name,
            )
            return None

        # Model allowlist
        resolved_model = self._check_model_allowlist(
            server_name, request.model, policy,
        )
        if resolved_model is None:
            return None

        # Token cap
        effective_max_tokens = min(request.max_tokens, policy.max_tokens_per_request)

        # Dispatch
        if self._llm_provider is not None:
            return await self._dispatch_to_provider(
                server_name, request, resolved_model, effective_max_tokens,
            )

        # If no provider is configured, return a stub result (useful during
        # development or when MCP servers don't require real sampling).
        self._audit_log.info(
            "Sampling request from %s (stub — no LLM provider configured): "
            "%d message(s), model=%s, max_tokens=%d",
            server_name, len(request.messages), resolved_model, effective_max_tokens,
        )
        return SamplingResult(
            content=[{"type": "text", "text": "[Sampling not available — no LLM provider configured]"}],
            model=resolved_model or "unknown",
            stop_reason="endTurn",
        )

    async def _dispatch_to_provider(
        self,
        server_name: str,
        request: SamplingRequest,
        model: str,
        max_tokens: int,
    ) -> SamplingResult:
        """Dispatch a sampling request to the configured LLM provider.

        This method should be extended to use the actual LLM port
        interface when a provider is configured.
        """
        self._audit_log.info(
            "Dispatching sampling request from %s to %s (%d messages, %d max tokens)",
            server_name, model, len(request.messages), max_tokens,
        )
        # Stub: return a placeholder until integrated with real LLM port
        return SamplingResult(
            content=[{"type": "text", "text": f"[Sampling request processed for {server_name}]"}],
            model=model,
            stop_reason="endTurn",
        )
