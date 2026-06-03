"""Session domain model — tracks a conversation/task lifecycle."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from .plan import Plan
from .event import AgentEvent
from weebot.domain.services.session_memory import SessionMemory


class SessionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


class SessionContext(BaseModel):
    """Typed session context.

    Known fields are explicit.  Extra keys from legacy/project-specific
    code are captured in ``extra`` and accessible via ``.get(key, default)``.

    The ``original_task`` field stores the first substantive prompt so
    that short follow-ups ("proceed", "yes") can be enriched with it.
    """
    skill_name: str = ""
    skill_content: str = ""
    skill_version: int = 0
    original_task: str = Field(default="", alias="_original_task")
    last_prompt: str = ""
    facts: Dict[str, Any] = Field(default_factory=dict)
    archived: bool = False
    archived_at: Optional[str] = None
    archive_ttl_days: int = 30
    detected_language: str = Field(
        default="",
        description="ISO 639-1 language code detected from user input (Enhancement 7)",
    )
    extra: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)

    @staticmethod
    def _cap_facts_dict(facts: Dict[str, Any]) -> Dict[str, Any]:
        """Evict oldest entries when facts exceed the 100-entry limit."""
        max_facts = 100
        if len(facts) > max_facts:
            keys = list(facts.keys())
            overflow = len(keys) - max_facts
            for k in keys[:overflow]:
                del facts[k]
        return facts

    @model_validator(mode="before")
    @classmethod
    def _coerce_from_dict(cls, data: Any) -> Any:
        """Accept plain dict (old serialized format) and extract known fields."""
        if isinstance(data, cls):
            return data
        if isinstance(data, BaseModel):
            return data
        if not isinstance(data, dict):
            return data
        known = {"skill_name", "skill_content", "skill_version", "_original_task",
                 "original_task", "last_prompt", "facts",
                 "archived", "archived_at", "archive_ttl_days", "extra"}
        result: dict[str, Any] = {}
        # Preserve any pre-existing extra dict (from a roundtrip dump)
        existing_extra = data.get("extra", {}) if isinstance(data.get("extra"), dict) else {}
        extra: dict[str, Any] = dict(existing_extra)
        for k, v in data.items():
            if k == "extra":
                continue  # already captured above
            # Map legacy key name to typed field
            field_key = {"_original_task": "original_task"}.get(k, k)
            if field_key in known:
                result[field_key] = v
            elif k not in known:
                extra[k] = v
        result["extra"] = extra
        return result

    @property
    def _field_names(self) -> set[str]:
        """Cached set of field names for fast membership checks (Pydantic v2 compat)."""
        return set(type(self).model_fields.keys())

    def get(self, key: str, default: Any = None) -> Any:
        """Access known fields or fall through to ``extra``.

        Provides backward compatibility with the old ``Dict[str, Any]``
        access pattern during migration.
        """
        # Handle legacy key name transparently
        mapped_key = {"_original_task": "original_task"}.get(key, key)
        if mapped_key in self._field_names:
            return getattr(self, mapped_key, default)
        return self.extra.get(key, default)

    def __getitem__(self, key: str) -> Any:
        val = self.get(key)
        if val is None:
            if key not in self.extra and key not in self._field_names:
                raise KeyError(key)
        return val

    def __setitem__(self, key: str, value: Any) -> None:
        """Set a known field or fall through to ``extra``."""
        mapped_key = {"_original_task": "original_task"}.get(key, key)
        if mapped_key in self._field_names:
            setattr(self, mapped_key, value)
        else:
            self.extra[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self._field_names or key in self.extra

    def copy(self) -> "SessionContext":
        """Return a deep copy (used by old dict-style code)."""
        return self.model_copy(deep=True)


class Session(BaseModel):
    """A user session containing events, plan history, and metadata."""
    id: str = Field(default="")
    user_id: str = Field(default="")
    agent_id: str = Field(default="")
    status: SessionStatus = Field(default=SessionStatus.PENDING)
    title: Optional[str] = Field(default=None)
    events: List[AgentEvent] = Field(default_factory=list)
    context: SessionContext = Field(default_factory=SessionContext)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    _memory_index: SessionMemory = PrivateAttr(default_factory=SessionMemory)

    @model_validator(mode="before")
    @classmethod
    def _fix_broken_context(cls, data: Any) -> Any:
        """Repair sessions saved with the broken json.dumps(context, default=str).

        Before fix: json.dumps(session.context, default=str) produced a repr
        string like \"skill_name='' ...\" instead of valid JSON.  These sessions
        have context_json containing a str instead of a dict.
        """
        if isinstance(data, dict) and isinstance(data.get("context"), str):
            # Broken serialization — context is a repr string.  Return an
            # empty context so the session loads without crashing.
            data["context"] = {}
        return data

    def add_event(self, event: AgentEvent) -> "Session":
        events = list(self.events)
        events.append(event)
        new_session = self.model_copy(update={
            "events": events,
            "updated_at": datetime.now(timezone.utc),
        })
        # Pydantic v2 model_copy() resets PrivateAttr to its default_factory
        # (a fresh empty SessionMemory), discarding the accumulated index.
        # Manually carry forward the existing index so get_last_plan() can use
        # O(1) lookup instead of falling back to an O(n) scan every call.
        new_session._memory_index = self._memory_index.copy()
        new_session._memory_index.index_event(len(events) - 1, event)
        return new_session

    def set_status(self, status: SessionStatus) -> "Session":
        return self.model_copy(update={
            "status": status,
            "updated_at": datetime.now(timezone.utc),
        })

    def get_last_plan(self) -> Optional[Plan]:
        plan = self._memory_index.find_last_plan(self.events)
        if plan is not None:
            return plan
        # Fallback scan for safety / backwards compatibility.
        # Also reconciles step statuses from StepEvents that occurred
        # after the last PlanEvent.
        from .event import PlanEvent, StepEvent
        from .plan import Plan, StepStatus as PS
        last_plan = None
        last_plan_idx = -1
        for i, event in enumerate(self.events):
            if isinstance(event, PlanEvent) and event.plan is not None:
                if isinstance(event.plan, dict):
                    last_plan = Plan.model_validate(event.plan)
                else:
                    last_plan = event.plan
                last_plan_idx = i
        if last_plan is None:
            return None

        # Apply step statuses from StepEvents after the last plan
        for event in self.events[last_plan_idx + 1:]:
            if isinstance(event, StepEvent) and event.step_id:
                status_map = {
                    "started": PS.RUNNING,
                    "running": PS.RUNNING,
                    "completed": PS.COMPLETED,
                    "failed": PS.FAILED,
                }
                new_status = status_map.get(event.status, None)
                if new_status is not None:
                    last_plan = last_plan.update_step_status(event.step_id, new_status)

        return last_plan

    def has_unresolved_wait_event(self) -> bool:
        return self._memory_index.has_unresolved_wait_event(self.events)

    def set_title(self, title: str) -> "Session":
        return self.model_copy(update={"title": title})

    def add_user_message(self, text: str) -> "Session":
        from .event import MessageEvent
        return self.add_event(MessageEvent(role="user", message=text))

    def set_fact(self, key: str, value: Any) -> "Session":
        facts = dict(self.context.facts)
        facts[key] = value
        SessionContext._cap_facts_dict(facts)
        new_ctx = self.context.model_copy(update={"facts": facts})
        return self.model_copy(update={"context": new_ctx})

    def get_fact(self, key: str, default: Any = None) -> Any:
        return self.context.facts.get(key, default)

    def get_facts(self) -> dict[str, Any]:
        try:
            return dict(self.context.facts)
        except AttributeError:
            # Old sessions may have context stored as plain dict from
            # the broken json.dumps(..., default=str) serialization.
            ctx = self.context
            if isinstance(ctx, dict):
                return dict(ctx.get("facts", {}))
            return {}
