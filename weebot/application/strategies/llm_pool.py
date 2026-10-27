"""Global LLM concurrency pool — bounds concurrent API requests across all sessions.

Without this, every PlanActFlow session fires parallel LLM calls simultaneously
(via the cascade's Phase 1 probes). Under 10x load, 30+ concurrent sessions
could produce 90+ parallel API requests, overwhelming both the network layer
and OpenRouter rate limits.

The pool uses an asyncio.Semaphore to cap concurrent in-flight LLM calls.

History, because it explains the shape. This class was registered in the
container at WP-8 and then never passed to anything: ``CascadeExecutor``
accepted an ``llm_pool`` argument that no construction site supplied, so the
bounded branch of its guard never ran, and an audit document recorded the bound
as wired and verified. Phase 1.3 of
``tasks/specs/arch_audit_2026_09_remediation_plan.md`` wires it. Two things
had to change first, and both were invisible only because nothing had ever
contended the semaphore:

1. **Saturation raises its own error.** The acquire timeout used to raise
   ``TimeoutError``, which the cascade catches as "this model timed out". A
   full local pool would have been recorded as a failure of whichever healthy
   model happened to be next, walked the whole cascade, and ended the step in
   ``AllModelsTrippedError`` -- local load reported as every provider down.

2. **One semaphore per event loop.** ``asyncio.Semaphore`` binds to the first
   loop that has to wait on it; a second loop then fails with ``RuntimeError``
   the moment it contends. The pool is a process-wide DI singleton, and this
   process runs more than one loop (pytest, and background work that calls
   ``asyncio.run`` in threads). So the bound is per loop. In the web server
   there is one loop, which makes it per process -- the case it exists for.
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import time
import weakref
from collections.abc import Awaitable, Callable
from typing import Any

from weebot.application.ports.llm_port import LLMPort
from weebot.domain.exceptions import LLMCapacityExhaustedError
from weebot.domain.models.llm_response import LLMResponse

logger = logging.getLogger(__name__)

# How deep the current call is inside an admitted section (0 = holds no slot).
_ADMITTED: contextvars.ContextVar[int] = contextvars.ContextVar("llm_pool_admitted", default=0)

# Generous on purpose. The old hardcoded 120s had never executed in
# production, and a queued call now waits for a slot without that wait
# counting against the model's own timeout -- so this only has to cover how
# long it is reasonable to queue, not how long a model may take. Tune it from
# measurements; do not tighten it on a guess.
DEFAULT_ACQUIRE_TIMEOUT_S = 300.0


class LLMPool:
    """Bounded pool for concurrent LLM calls.

    Usage::

        pool = LLMPool(max_concurrent=12)
        async with pool:
            resp = await provider.chat(...)

    Raises :class:`LLMCapacityExhaustedError` if no slot frees up within
    ``acquire_timeout`` seconds.
    """

    def __init__(
        self,
        max_concurrent: int = 12,
        acquire_timeout: float = DEFAULT_ACQUIRE_TIMEOUT_S,
    ) -> None:
        if max_concurrent < 1:
            raise ValueError(f"max_concurrent must be >= 1, got {max_concurrent}")
        self._max = max_concurrent
        self._acquire_timeout = acquire_timeout
        # Keyed weakly so a finished loop takes its semaphore with it.
        self._semaphores: weakref.WeakKeyDictionary[
            asyncio.AbstractEventLoop, asyncio.Semaphore
        ] = weakref.WeakKeyDictionary()
        self._in_use: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, int] = (
            weakref.WeakKeyDictionary()
        )

    @property
    def max_concurrent(self) -> int:
        return self._max

    @property
    def acquire_timeout(self) -> float:
        return self._acquire_timeout

    @property
    def available(self) -> int:
        """Free slots on the running loop (``max_concurrent`` if none has run)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return self._max
        return self._max - self._in_use.get(loop, 0)

    def _semaphore(self) -> tuple[asyncio.AbstractEventLoop, asyncio.Semaphore]:
        loop = asyncio.get_running_loop()
        sem = self._semaphores.get(loop)
        if sem is None:
            sem = asyncio.Semaphore(self._max)
            self._semaphores[loop] = sem
        return loop, sem

    async def __aenter__(self) -> LLMPool:
        """Acquire a slot, waiting up to ``acquire_timeout`` seconds.

        Re-entrant per task: a caller that already holds a slot (the cascade,
        which acquires OUTSIDE its ``wait_for`` so queueing never counts against a
        model's timeout) passes through any ``BoundedLLMAdapter`` below it without
        taking a second slot. Two acquisitions by one call would deadlock a pool of
        size 1. The admission depth lives in a ContextVar, so it follows the call
        into the tasks ``wait_for`` creates and never leaks to unrelated callers.
        """
        depth = _ADMITTED.get()
        if depth > 0:
            _ADMITTED.set(depth + 1)
            return self
        loop, sem = self._semaphore()
        try:
            await asyncio.wait_for(sem.acquire(), timeout=self._acquire_timeout)
        except TimeoutError:
            logger.error(
                "LLMPool: all %d slots busy for %.0fs -- refusing the call rather "
                "than charging the wait to a model",
                self._max,
                self._acquire_timeout,
            )
            raise LLMCapacityExhaustedError(
                f"All {self._max} LLM concurrency slots stayed busy for "
                f"{self._acquire_timeout:.0f}s"
            ) from None
        self._in_use[loop] = self._in_use.get(loop, 0) + 1
        _ADMITTED.set(1)
        return self

    async def __aexit__(self, *args: object) -> None:
        """Release the slot on the loop that acquired it (the outermost exit only)."""
        depth = _ADMITTED.get()
        if depth > 1:
            _ADMITTED.set(depth - 1)
            return
        _ADMITTED.set(0)
        loop, sem = self._semaphore()
        self._in_use[loop] = self._in_use.get(loop, 1) - 1
        sem.release()


class BoundedLLMAdapter(LLMPort):
    """Bulkhead decorator: every call through this adapter takes a pool slot.

    The pool used to bound only the cascade (``_cascade.py``); the planner,
    optimizer, verifiers, critics and ~20 other services called ``LLMPort.chat``
    directly, so 68 call sites were invisible to the bound. Wrapping the port, once,
    where the container hands it out, bounds all of them without touching a call
    site (ORCH-1 of ``tasks/specs/arch_audit_2026_10_remediation_plan.md``).

    Feature-level semaphores (``dispatch_agents``, ``mixture_of_agents``,
    ``sub_agent_factory``, ``harness/runner``, ``workflow_orchestrator``) stay.
    They bound fan-out *width*, this bounds total in-flight calls: bulkheads
    inside a bulkhead, not drift.

    A call made inside an already-admitted section (the cascade holds the slot)
    passes straight through; see :meth:`LLMPool.__aenter__`. Saturation raises
    :class:`LLMCapacityExhaustedError`, never ``TimeoutError``.
    """

    def __init__(
        self,
        inner: LLMPort,
        pool: LLMPool,
        on_completed: Callable[[Any], Awaitable[None]] | None = None,
    ) -> None:
        self._inner = inner
        self._pool = pool
        # Publishes ``LLMCallCompleted`` for calls that do not go through the cascade
        # (planner, verifiers, critics ...), so cost metering is complete (OBS-1, 2.4).
        self._on_completed = on_completed

    @property
    def inner(self) -> LLMPort:
        return self._inner

    @property
    def pool(self) -> LLMPool:
        return self._pool

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
        # A call made inside an admitted section is the cascade's, and the cascade
        # reports its own completion: reporting here too would count it twice.
        direct = _ADMITTED.get() == 0
        started = time.monotonic()
        outcome = "ok"
        response: LLMResponse | None = None
        try:
            async with self._pool:
                response = await self._inner.chat(
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    response_format=response_format,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            return response
        except LLMCapacityExhaustedError:
            outcome = "saturated"
            raise
        except Exception:
            outcome = "error"
            raise
        finally:
            await self._record_call(
                messages, model, response, outcome, time.monotonic() - started, direct, tools
            )

    async def _record_call(
        self,
        messages: list[dict[str, Any]],
        model: str | None,
        response: LLMResponse | None,
        outcome: str,
        elapsed_s: float,
        direct: bool,
        tools: list[dict[str, Any]] | None = None,
    ) -> None:
        """One structured record per call; never raises into the caller's call."""
        try:
            usage = (getattr(response, "usage", None) or {}) if response is not None else {}
            prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens = int(usage.get("completion_tokens", 0) or 0)
            used_model = getattr(response, "model", None) or model or "unknown"
            logger.info(
                "llm_call model=%s outcome=%s latency_ms=%d prompt_tokens=%d "
                "completion_tokens=%d prompt_sha=%s tools_sha=%s",
                used_model,
                outcome,
                int(elapsed_s * 1000),
                prompt_tokens,
                completion_tokens,
                prompt_sha(messages),
                tools_sha(tools),
            )
            if direct and outcome == "ok" and self._on_completed is not None:
                from weebot.core.log_context import session_id_var
                from weebot.config.model_registry import get_model_config
                from weebot.core.model_cascade_config import estimate_cost
                from weebot.domain.models.event import LLMCallCompleted

                # Price the id the caller asked for when the catalog lists it, as the
                # cascade does: a direct provider answers with a bare id the catalog lacks.
                priced = model if model and get_model_config(model) else used_model

                await self._on_completed(
                    LLMCallCompleted(
                        session_id=session_id_var.get() or "",
                        model=used_model,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        cost=estimate_cost(
                            priced, prompt_tokens, completion_tokens,
                            cached_prompt=int(usage.get("cached_tokens", 0) or 0),
                        ),
                    )
                )
        except Exception:
            logger.warning("could not record an LLM call", exc_info=True)

    async def build_multimodal_message(
        self, role: str, text: str, image_base64: str, media_type: str = "image/png"
    ) -> dict[str, Any]:
        # Builds a dict, makes no request: no slot.
        return await self._inner.build_multimodal_message(role, text, image_base64, media_type)

    def __getattr__(self, name: str) -> Any:
        # Adapter-specific surface (get_metrics, get_circuit_state, reset_circuit, ...)
        # that callers reach through the port's concrete type.
        if name.startswith("__") or name in ("_inner", "_pool"):
            raise AttributeError(name)
        attr = getattr(self._inner, name)
        if name == "stream":
            # StreamingLLMPort is structural: present only when the inner adapter
            # streams, and then it holds a slot for the whole stream.
            return self._bounded_stream(attr)
        return attr

    def _bounded_stream(self, stream_fn: Any) -> Any:
        pool = self._pool

        async def stream(*args: Any, **kwargs: Any):
            async with pool:
                async for chunk in stream_fn(*args, **kwargs):
                    yield chunk

        return stream


def prompt_sha(messages: list[dict[str, Any]]) -> str:
    """A 12-hex digest of the system prompt, to tell prompt versions apart in the logs.

    Prompts are assembled in several places (executor, planner, harness); hashing the
    system message at the one choke point versions all of them with no call-site change.
    "none" when the call carries no system message.
    """
    for message in messages or []:
        if isinstance(message, dict) and message.get("role") == "system":
            content = message.get("content")
            text = content if isinstance(content, str) else str(content)
            return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:12]
    return "none"


def tools_sha(tools: list[dict[str, Any]] | None) -> str:
    """A 12-hex digest of the tool schema, alongside `prompt_sha`.

    Without it the prompt version is only half-visible: a change to a tool's description
    or parameters alters behaviour exactly as a prompt change does, and used to look like
    an unchanged prompt in the log.
    """
    if not tools:
        return "none"
    blob = json.dumps(tools, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8", "replace")).hexdigest()[:12]


def unwrap_llm(llm: Any) -> Any:
    """The adapter under any bulkhead wrappers, for ``isinstance`` checks on a concrete type."""
    # `_llm_wrapper`: other pass-through layers (the local-model router) expose `.inner` too.
    while isinstance(llm, BoundedLLMAdapter) or getattr(llm, "_llm_wrapper", False) is True:
        llm = llm.inner
    return llm
