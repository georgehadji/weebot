"""Memory archivist — TTL-based eviction + LLM summarization for old session events."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from weebot.application.ports.llm_port import LLMPort
from weebot.domain.models.event import AgentEvent, MessageEvent
from weebot.domain.models.session import Session


class SessionSummarizer:
    """Condenses a list of archived events into a single summary message."""

    def __init__(self, llm: Optional[LLMPort] = None, model: Optional[str] = None) -> None:
        self._llm = llm
        self._model = model

    async def summarize(self, events: list[AgentEvent]) -> str:
        """Return a brief textual summary of the archived events."""
        if not events:
            return "No prior activity."
        if self._llm is None:
            # Fallback: simple concatenation of event types
            types = [ev.type for ev in events]
            return f"Previous activity: {', '.join(types)}."

        prompt = (
            "Summarize the following agent events in one concise paragraph. "
            "Focus on what was planned and what was accomplished.\n\n"
        )
        for ev in events:
            prompt += f"- {ev.type}: {getattr(ev, 'message', getattr(ev, 'description', str(ev)))}\n"

        response = await self._llm.chat(
            messages=[{"role": "user", "content": prompt}],
            model=self._model,
            temperature=TEMPERATURE_BALANCED,
        )
        return response.content or "Previous activity occurred."


class MemoryArchivist:
    """Archives old session events based on TTL and replaces them with a summary."""

    def __init__(
        self,
        ttl: timedelta = timedelta(hours=1),
        summarizer: Optional[SessionSummarizer] = None,
    ) -> None:
        self._ttl = ttl
        self._summarizer = summarizer

    async def archive_old_events(self, session: Session) -> Session:
        """Remove events older than TTL and prepend a summary message."""
        if not session.events:
            return session

        cutoff = datetime.now(timezone.utc) - self._ttl
        recent_events: list[AgentEvent] = []
        archived_events: list[AgentEvent] = []

        for ev in session.events:
            # Pydantic BaseModel timestamps may be datetime or str
            ts = ev.timestamp
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            if ts >= cutoff:
                recent_events.append(ev)
            else:
                archived_events.append(ev)

        if not archived_events:
            return session

        summary_text = "Previous activity summarized."
        if self._summarizer is not None:
            summary_text = await self._summarizer.summarize(archived_events)

        summary_event = MessageEvent(role="assistant", message=summary_text)
        new_events = [summary_event, *recent_events]
        return session.model_copy(update={"events": new_events})
