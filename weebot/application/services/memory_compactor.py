"""Memory compaction service — reduces token bloat from large tool outputs."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from weebot.domain.models.event import AgentEvent, ToolEvent, MessageEvent
from weebot.domain.models.session import Session

from .constraint_extractor import ConstraintExtractor, Constraint


class MemoryCompactor:
    """Compact session events to reduce context window pressure.
    
    Now with constraint preservation — critical instructions (safety rules,
    negative constraints) are extracted before compaction and re-injected
    to prevent the amnesia problem documented in the MEMORY_ARTICLE.
    """

    def __init__(
        self,
        max_screenshot_chars: int = 5000,
        max_shell_lines: int = 50,
        shell_tail_lines: int = 20,
        preserve_constraints: bool = True,
    ):
        self.max_screenshot_chars = max_screenshot_chars
        self.max_shell_lines = max_shell_lines
        self.shell_tail_lines = shell_tail_lines
        self.preserve_constraints = preserve_constraints
        self._constraint_extractor = ConstraintExtractor() if preserve_constraints else None

    def compact_session(self, session: Session) -> Session:
        """Return a new session with compacted events.
        
        If constraint preservation is enabled, critical constraints are
        extracted before compaction and injected into the result.
        """
        # Extract constraints BEFORE any compaction
        extracted_constraints: List[Constraint] = []
        if self.preserve_constraints and self._constraint_extractor:
            all_event_text = "\n".join(str(e) for e in session.events)
            extracted_constraints = self._constraint_extractor.extract(all_event_text)
        
        # Perform compaction
        compacted: List[AgentEvent] = []
        for event in session.events:
            compacted.append(self._compact_event(event))
        compacted = self._deduplicate_repeated_tool_results(compacted)
        
        # Create compacted session
        compacted_session = session.model_copy(update={"events": compacted})
        
        # Re-inject constraints if any were found
        if extracted_constraints:
            constraint_text = self._constraint_extractor.format_constraints(extracted_constraints)
            compacted_session = self._inject_constraints(compacted_session, constraint_text)
        
        return compacted_session

    def _compact_event(self, event: AgentEvent) -> AgentEvent:
        if isinstance(event, ToolEvent):
            return self._compact_tool_event(event)
        return event

    def _deduplicate_repeated_tool_results(self, events: List[AgentEvent]) -> List[AgentEvent]:
        """Replace consecutive identical tool results with a count marker."""
        if not events:
            return events

        deduped: List[AgentEvent] = []
        prev_key: Optional[tuple] = None
        run_count = 0

        for event in events:
            if isinstance(event, ToolEvent):
                key = (event.tool_name, event.result)
                if key == prev_key and prev_key is not None:
                    run_count += 1
                    continue
                if run_count > 1 and prev_key is not None:
                    # Replace the last inserted identical event with a marker
                    last = deduped[-1]
                    if isinstance(last, ToolEvent):
                        deduped[-1] = last.model_copy(update={
                            "result": f"[Repeated {run_count}x] {last.result}"
                        })
                prev_key = key
                run_count = 1
                deduped.append(event)
            else:
                if run_count > 1 and prev_key is not None:
                    last = deduped[-1]
                    if isinstance(last, ToolEvent):
                        deduped[-1] = last.model_copy(update={
                            "result": f"[Repeated {run_count}x] {last.result}"
                        })
                prev_key = None
                run_count = 0
                deduped.append(event)

        # Finalize trailing run
        if run_count > 1 and prev_key is not None:
            last = deduped[-1]
            if isinstance(last, ToolEvent):
                deduped[-1] = last.model_copy(update={
                    "result": f"[Repeated {run_count}x] {last.result}"
                })

        return deduped

    def _compact_tool_event(self, event: ToolEvent) -> ToolEvent:
        if event.tool_name in ("browser_view", "browser_screenshot", "screen_capture"):
            result = event.result or ""
            if len(result) > self.max_screenshot_chars:
                return event.model_copy(update={
                    "result": f"[Screenshot compacted: {len(result)} chars]"
                })

        if event.tool_name in ("bash", "shell_exec", "powershell"):
            result = event.result or ""
            lines = result.splitlines()
            if len(lines) > self.max_shell_lines:
                tail = lines[-self.shell_tail_lines:]
                return event.model_copy(update={
                    "result": f"[Output truncated from {len(lines)} lines]\n" + "\n".join(tail)
                })

        return event
    
    def _inject_constraints(self, session: Session, constraint_text: str) -> Session:
        """Inject constraints into the session.
        
        Looks for an existing system message to prepend to, or creates
        a new system message if none exists.
        
        Args:
            session: The compacted session.
            constraint_text: Formatted constraint text to inject.
            
        Returns:
            Session with constraints injected.
        """
        if not constraint_text:
            return session
        
        constraint_marker = "[CONSTRAINTS]"

        # Look for an existing injected constraint message
        for i, event in enumerate(session.events):
            if isinstance(event, MessageEvent) and event.role == "assistant" and event.message.startswith(constraint_marker):
                # Refresh existing constraint message
                new_events = list(session.events)
                new_events[i] = event.model_copy(update={"message": f"{constraint_marker}\n{constraint_text}"})
                return session.model_copy(update={"events": new_events})

        # No existing constraint message found - inject at the beginning
        new_events = [MessageEvent(role="assistant", message=f"{constraint_marker}\n{constraint_text}")] + list(session.events)
        return session.model_copy(update={"events": new_events})
