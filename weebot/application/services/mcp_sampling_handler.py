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
from typing import Any

from weebot.application.ports.mcp_sampling_port import (
    McpSamplingPort,
    SamplingRequest,
    SamplingResult,
)
from weebot.domain.models.mcp import MCPSamplingPolicy

logger = logging.getLogger(__name__)


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


class MCPSamplingHandler(McpSamplingPort):
    """Handles MCP sampling/createMessage requests.

    Dispatches LLM calls through Weebot's LLM provider, applying
    per-server rate limits and model allowlists.  Can be extended
    with an actual LLM port reference for real inference.
    """

    def __init__(
        self,
        llm_provider: Any | None = None,
        audit_log: logging.Logger | None = None,
        cost_meter: Any | None = None,
    ) -> None:
        self._llm_provider = llm_provider
        self._cost_meter = cost_meter
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
            "MCP server %s requested sampling with model %r, " "which is not in its allowlist: %s",
            server_name,
            candidate,
            policy.model_allowlist,
        )
        return None

    async def handle_sampling(
        self,
        server_name: str,
        request: SamplingRequest,
        policy: MCPSamplingPolicy,
        *,
        session_id: str | None = None,
        tainted: bool = False,
    ) -> SamplingResult | None:
        """Process a sampling/createMessage request from *server_name*.

        Returns None if the request is denied: sampling disabled, no session to charge (pass
        ``session_id=None`` to skip that check), untrusted content in the session, the
        session's budget spent, the rate limit, or a model outside the allowlist.
        """
        if not policy.enabled:
            logger.info("Sampling disabled for server %s — denying request", server_name)
            return None
        if session_id is not None and not session_id:
            self._audit_log.warning(
                "MCP server %s asked for sampling outside a tool call; denied", server_name
            )
            return None
        if tainted and not policy.allow_when_tainted:
            self._audit_log.warning(
                "MCP server %s asked for sampling in a session with untrusted content; denied",
                server_name,
            )
            return None
        if (
            session_id
            and self._cost_meter is not None
            and self._cost_meter.hard_exceeded(session_id)
        ):
            self._audit_log.warning(
                "MCP server %s asked for sampling past the session budget; denied", server_name
            )
            return None

        # Rate limit
        limiter = self._get_rate_limiter(server_name, policy)
        allowed = await limiter.acquire()
        if not allowed:
            self._audit_log.warning("Rate-limited sampling request from MCP server %s", server_name)
            return None

        # Model allowlist
        resolved_model = self._check_model_allowlist(server_name, request.model, policy)
        if resolved_model is None:
            return None

        # Token cap
        effective_max_tokens = min(request.max_tokens, policy.max_tokens_per_request)

        # Dispatch
        if self._llm_provider is None:
            self._audit_log.info(
                "Sampling request from %s denied: no LLM provider configured", server_name
            )
            return None
        return await self._dispatch_to_provider(
            server_name, request, resolved_model, effective_max_tokens, session_id
        )

    async def _dispatch_to_provider(
        self,
        server_name: str,
        request: SamplingRequest,
        model: str,
        max_tokens: int,
        session_id: str | None,
    ) -> SamplingResult | None:
        """Ask the provider. The call is charged to *session_id* through ``session_id_var``,
        which the provider's cost event reads, so it lands on the parent session's meter."""
        from weebot.config.constants import TEMPERATURE_DETERMINISTIC
        from weebot.core.log_context import session_id_var

        self._audit_log.info(
            "Dispatching sampling request from %s to %s (%d messages, %d max tokens)",
            server_name,
            model,
            len(request.messages),
            max_tokens,
        )
        messages = list(request.messages)
        if request.system_prompt:
            messages.insert(0, {"role": "system", "content": request.system_prompt})
        token = session_id_var.set(session_id) if session_id else None
        try:
            response = await self._llm_provider.chat(
                messages=messages,
                model=None if model == "default" else model,
                temperature=(
                    TEMPERATURE_DETERMINISTIC
                    if request.temperature is None
                    else request.temperature
                ),
                max_tokens=max_tokens,
            )
        except Exception as exc:
            self._audit_log.warning("Sampling call for %s failed: %s", server_name, exc)
            return None
        finally:
            if token is not None:
                session_id_var.reset(token)
        return SamplingResult(
            content=[{"type": "text", "text": response.content or ""}],
            model=getattr(response, "model", None) or model,
            stop_reason="endTurn",
        )
