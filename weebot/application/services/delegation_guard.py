"""DelegationGuard: the one choke point every spawned child passes through (H4).

Depth travels in a ``ContextVar``, the same mechanism ``approval_scope`` uses: asyncio copies
it into child tasks, so a grandchild sees depth 2 without anyone passing it down. The guard is
a DI singleton, so its bulkhead and per-session counts are shared by every spawn path.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

from weebot.domain.models.delegation import DelegationDenied, DelegationPolicy

logger = logging.getLogger(__name__)

_depth: ContextVar[int] = ContextVar("weebot_delegation_depth", default=0)


def current_depth() -> int:
    """How many delegations deep the running task is. 0 is the top-level agent."""
    return _depth.get()


class DelegationGuard:
    def __init__(self, policy: DelegationPolicy | None = None) -> None:
        self.policy = policy or DelegationPolicy()
        self._bulkhead = asyncio.Semaphore(self.policy.max_concurrent_children)
        self._spawned: Counter[str] = Counter()

    @asynccontextmanager
    async def enter(self, parent_session_id: str) -> AsyncIterator[int]:
        """Run a child inside the policy. Yields the child's depth.

        Raises ``DelegationDenied`` at the depth limit, over the per-session count, or when no
        slot frees up within the child timeout.
        """
        policy, depth = self.policy, _depth.get()
        if depth >= policy.max_depth:
            raise DelegationDenied(
                f"delegation depth limit reached (max_depth={policy.max_depth}): "
                "a sub-agent may not start more agents"
            )
        if self._spawned[parent_session_id] >= policy.max_children_per_session:
            raise DelegationDenied(
                f"session {parent_session_id!r} already started "
                f"{policy.max_children_per_session} sub-agents (max_children_per_session)"
            )
        try:
            if self._bulkhead.locked():
                await asyncio.wait_for(self._bulkhead.acquire(), policy.child_timeout_s)
            else:
                await self._bulkhead.acquire()
        except TimeoutError:
            raise DelegationDenied(
                f"no free sub-agent slot after {policy.child_timeout_s}s "
                f"(max_concurrent_children={policy.max_concurrent_children})"
            ) from None
        self._spawned[parent_session_id] += 1
        token = _depth.set(depth + 1)
        try:
            yield depth + 1
        finally:
            try:
                _depth.reset(token)
            except ValueError:
                # Closed from another task's context; that task's own depth is unaffected.
                logger.debug("delegation depth token reset from a different context")
            self._bulkhead.release()

    def forget(self, parent_session_id: str) -> None:
        """Drop a finished session's count."""
        self._spawned.pop(parent_session_id, None)

    def wrap(self, flow: Any, parent_session_id: str) -> DelegatedFlow:
        return DelegatedFlow(flow, self, parent_session_id)


class DelegatedFlow:
    """A child flow whose ``run`` happens inside ``guard.enter`` and under the child timeout."""

    def __init__(self, inner: Any, guard: DelegationGuard, parent_session_id: str) -> None:
        self._inner, self._guard, self._parent = inner, guard, parent_session_id

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def run(self, prompt: str) -> AsyncIterator[Any]:
        timeout = self._guard.policy.child_timeout_s
        async with self._guard.enter(self._parent):
            deadline = time.monotonic() + timeout
            events = self._inner.run(prompt).__aiter__()
            try:
                while True:
                    left = max(deadline - time.monotonic(), 0.001)
                    try:
                        event = await asyncio.wait_for(events.__anext__(), left)
                    except StopAsyncIteration:
                        return
                    except TimeoutError:
                        raise TimeoutError(
                            f"sub-agent exceeded child_timeout_s={timeout} (delegation policy)"
                        ) from None
                    yield event
            finally:
                aclose = getattr(events, "aclose", None)
                if aclose is not None:
                    await aclose()
