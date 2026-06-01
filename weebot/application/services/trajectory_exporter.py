"""TrajectoryExporter — serialize session events to JSONL for analysis or fine-tuning.

Each output line is one JSON object representing a single AgentEvent
(ToolEvent, StepEvent, MessageEvent, etc.) serialized via Pydantic model_dump().

Optional compress_to_budget parameter rewrites the middle turns (using
ConversationCompressor) before export so the trajectory fits within a target
token budget — useful for creating fine-tuning datasets.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.state_repo_port import StateRepositoryPort

logger = logging.getLogger(__name__)

__all__ = ["TrajectoryExporter"]


class TrajectoryExporter:
    """Export session event trajectories from SQLite to JSONL files.

    Args:
        repo: StateRepositoryPort to load sessions from.
    """

    def __init__(self, repo: StateRepositoryPort) -> None:
        self._repo = repo

    async def export_session(
        self,
        session_id: str,
        output_path: str | Path,
        compress_to_budget: Optional[int] = None,
        llm: Optional[LLMPort] = None,
    ) -> int:
        """Export a single session as JSONL.

        Args:
            session_id: ID of the session to export.
            output_path: Destination .jsonl file path.
            compress_to_budget: If set, summarize middle events to fit token budget.
                                Requires *llm* to be provided.
            llm: LLMPort instance for compression (only used when compress_to_budget set).

        Returns:
            Number of event lines written.

        Raises:
            ValueError: If the session is not found in the repository.
        """
        session = await self._repo.load_session(session_id)
        if session is None:
            raise ValueError(f"Session not found: {session_id!r}")

        events = list(session.events)

        if compress_to_budget is not None and llm is not None and events:
            events = await self._compress_events(events, compress_to_budget, llm)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        written = 0
        with output_path.open("w", encoding="utf-8") as fh:
            for event in events:
                row = self._event_to_dict(event)
                fh.write(json.dumps(row, default=str, ensure_ascii=False) + "\n")
                written += 1

        logger.info(
            "Exported %d events from session %s → %s",
            written,
            session_id,
            output_path,
        )
        return written

    async def export_all(
        self,
        user_id: str,
        output_dir: str | Path,
        compress_to_budget: Optional[int] = None,
        llm: Optional[LLMPort] = None,
    ) -> Dict[str, int]:
        """Export all sessions for *user_id* as separate JSONL files.

        Args:
            user_id: User whose sessions to export.
            output_dir: Directory to write files into (one .jsonl per session).
            compress_to_budget: If set, compress each session before export.
            llm: LLMPort for compression.

        Returns:
            Mapping of session_id → events_written (-1 on failure).
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        sessions = await self._repo.list_sessions(user_id=user_id)
        results: Dict[str, int] = {}

        for session in sessions:
            safe_id = session.id.replace("/", "_").replace("\\", "_")
            dest = output_dir / f"{safe_id}.jsonl"
            try:
                count = await self.export_session(
                    session.id,
                    dest,
                    compress_to_budget=compress_to_budget,
                    llm=llm,
                )
                results[session.id] = count
            except Exception as exc:
                logger.warning("Failed to export session %s: %s", session.id, exc)
                results[session.id] = -1

        logger.info(
            "Exported %d sessions for user %r to %s",
            len(results),
            user_id,
            output_dir,
        )
        return results

    @staticmethod
    def _event_to_dict(event: Any) -> Dict[str, Any]:
        """Serialize an AgentEvent to a JSON-safe dict."""
        try:
            return event.model_dump()
        except Exception:
            return {"type": getattr(event, "type", "unknown"), "raw": str(event)}

    async def _compress_events(
        self,
        events: List[Any],
        budget_tokens: int,
        llm: LLMPort,
    ) -> List[Any]:
        """Drop middle events to fit within *budget_tokens* while preserving type fidelity.

        Uses the same head/tail protection as ConversationCompressor (KEEP_HEAD=3,
        KEEP_TAIL=6) but operates directly on AgentEvents rather than converting
        them to message dicts. This preserves the event-type discriminators
        (ToolEvent, StepEvent, etc.) that are critical for fine-tuning datasets.

        The dropped middle events are replaced by a single synthetic MessageEvent
        whose content is a human-readable summary produced by ConversationCompressor.
        Head and tail events are emitted verbatim.
        """
        from weebot.application.services.conversation_compressor import (
            ConversationCompressor,
            KEEP_HEAD,
            KEEP_TAIL,
        )
        from weebot.domain.models.event import MessageEvent

        chars_per_token = 4
        total_chars = sum(len(str(e)) for e in events)
        if total_chars // chars_per_token <= budget_tokens:
            return events  # Already fits — no compression needed

        total = len(events)
        min_compressible = KEEP_HEAD + KEEP_TAIL + 1
        if total < min_compressible:
            return events  # Too short to compress

        head = events[:KEEP_HEAD]
        middle = events[KEEP_HEAD : total - KEEP_TAIL]
        tail = events[total - KEEP_TAIL :]

        # Summarize the middle section as plain text
        messages = [{"role": "assistant", "content": str(e)} for e in middle]
        compressor = ConversationCompressor(llm=llm)
        summary = await compressor._summarize(messages)

        summary_event = MessageEvent(
            role="assistant",
            message=f"[Trajectory summary — {len(middle)} events compressed]\n{summary}",
        )

        return list(head) + [summary_event] + list(tail)
