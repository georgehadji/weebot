"""A durable record of outbound actions already taken, so a retry does not repeat them.

ORCH-2 of ``tasks/specs/arch_audit_2026_10_remediation_plan.md``. A failed session
is re-run from the start by ``TaskRunner`` (``_run_flow`` retries), and states
retry steps; nothing stopped the second run from sending the mail again. An
Idempotent Receiver fixes that at the one place every tool call passes:
``ToolExecutor`` asks this ledger before an egress call and records after it.

Storage is the append-only event store, through the existing ``EventStorePort``
(``log_event`` / ``get_session_events``): no new port, no new table. The plan
named session facts instead, but the runner rewrites the whole session on every
event, so a fact written beside it can be lost; an appended event cannot.

What this guarantees, stated honestly: it narrows at-least-once to a single
in-flight call. A crash between the provider accepting a send and the ledger
write can still duplicate it. Exactly-once needs a provider idempotency key; pass
the ``effect_key`` through where an adapter's API takes one.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from weebot.application.ports.event_store_port import EventStorePort

logger = logging.getLogger(__name__)

RECORDED = "effect_recorded"
FLAG = "session_flag"
REPLAYED = "effect_replayed"
_SUMMARY_CHARS = 500


class EffectLedger:
    def __init__(self, event_store: EventStorePort) -> None:
        self._store = event_store

    async def lookup(self, session_id: str, key: str) -> dict[str, Any] | None:
        """The successful record for *key* in this session, or None.

        A ledger that cannot be read answers None (the call proceeds), because
        refusing a send over a bookkeeping failure would be the worse error; the
        failure is logged.
        """
        try:
            rows = await self._store.get_session_events(session_id, RECORDED)
        except Exception:
            logger.warning("effect ledger unreadable for session %s", session_id, exc_info=True)
            return None
        for row in rows:
            data = row.get("data", row)
            if data.get("key") == key and data.get("ok"):
                return data
        return None

    async def record(self, session_id: str, key: str, tool: str, summary: str, ok: bool) -> None:
        await self._log(
            session_id,
            RECORDED,
            {
                "key": key,
                "tool": tool,
                "summary": summary[:_SUMMARY_CHARS],
                "ok": ok,
                "at": datetime.now(UTC).isoformat(),
            },
        )

    async def note_replay(self, session_id: str, key: str, tool: str) -> None:
        logger.warning(
            "effect replay suppressed: %s (session %s, key %s)", tool, session_id, key[:12]
        )
        await self._log(
            session_id,
            REPLAYED,
            {"key": key, "tool": tool, "at": datetime.now(UTC).isoformat()},
        )

    # ── per-session security state (plan Phase 8, input to Sep 5.3) ────────────
    # The executor's taint, local-tab and written-file sets used to live only in process
    # dicts, so a restart changed security decisions. They are appended here as small
    # ``session_flag`` rows and replayed once per session per process.

    async def note_flag(self, session_id: str, kind: str, **data: Any) -> None:
        await self._log(session_id, FLAG, {"kind": kind, **data})

    async def flags(self, session_id: str) -> list[dict[str, Any]]:
        """Every flag row for the session, oldest first ([] when the store is unreadable)."""
        try:
            rows = await self._store.get_session_events(session_id, FLAG)
        except Exception:
            logger.warning("session flags unreadable for %s", session_id, exc_info=True)
            return []
        return [row.get("data", row) for row in rows]

    async def _log(self, session_id: str, event_type: str, data: dict[str, Any]) -> None:
        try:
            await self._store.log_event(session_id, event_type, data)
        except Exception:
            logger.warning("effect ledger write failed (%s)", event_type, exc_info=True)
