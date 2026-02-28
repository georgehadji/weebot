"""Domain models for weebot — zero external dependencies."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Task / Project models (refactor plan Task 6)
# ---------------------------------------------------------------------------

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ProjectStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    name: str
    description: str
    prompt: str
    task_type: str = "chat"
    system_prompt: str = ""
    depends_on: list[str] = field(default_factory=list)
    checkpoint: bool = False
    checkpoint_desc: str = ""
    temperature: float = 0.7
    max_tokens: int = 2000
    use_cache: bool = True
    status: TaskStatus = TaskStatus.PENDING
    result: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def mark_complete(self, result: str) -> None:
        self.status = TaskStatus.COMPLETED
        self.result = result
        self.completed_at = datetime.now()

    def mark_failed(self, error: str) -> None:
        self.status = TaskStatus.FAILED
        self.error = error
        self.completed_at = datetime.now()

    def mark_running(self) -> None:
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.now()


@dataclass
class Checkpoint:
    task_name: str
    description: str
    requires_input: bool = False
    input_prompt: str = ""
    resolved: bool = False
    resolution: str | None = None


@dataclass
class AgentConfig:
    project_id: str
    description: str
    auto_resume: bool = True
    daily_budget: float = 10.0
    max_retries: int = 3
    notification_channels: list[str] = field(default_factory=list)


@dataclass
class Project:
    project_id: str
    description: str
    status: ProjectStatus = ProjectStatus.PENDING
    tasks: list[Task] = field(default_factory=list)
    checkpoints: list[Checkpoint] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    total_cost: float = 0.0

    def add_task(self, task: Task) -> None:
        self.tasks.append(task)

    @property
    def pending_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == TaskStatus.PENDING)

    @property
    def completed_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)

    @property
    def is_complete(self) -> bool:
        return all(
            t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED, TaskStatus.FAILED)
            for t in self.tasks
        )


# ---------------------------------------------------------------------------
# OpenManus-style Message / Memory / AgentState (Task 2)
# ---------------------------------------------------------------------------

class Role(Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class AgentState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    FINISHED = "finished"
    ERROR = "error"


@dataclass
class ToolCallSpec:
    """Minimal spec for a single tool call from LLM response."""
    id: str
    name: str
    arguments: str  # raw JSON string


@dataclass
class Message:
    """A single chat message in the agent's memory."""
    role: Role
    content: str = ""
    tool_calls: list[ToolCallSpec] = field(default_factory=list)
    tool_call_id: str | None = None

    def to_openai_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role.value, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in self.tool_calls
            ]
        if self.tool_call_id is not None:
            d["tool_call_id"] = self.tool_call_id
        return d

    @classmethod
    def system(cls, content: str) -> "Message":
        return cls(role=Role.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str) -> "Message":
        return cls(role=Role.USER, content=content)


@dataclass
class Memory:
    """Conversation memory with automatic truncation of non-system messages."""
    max_messages: int = 100
    messages: list[Message] = field(default_factory=list)

    def add(self, message: Message) -> None:
        self.messages.append(message)
        self._trim()

    def _trim(self) -> None:
        system = [m for m in self.messages if m.role == Role.SYSTEM]
        non_system = [m for m in self.messages if m.role != Role.SYSTEM]
        if len(non_system) > self.max_messages:
            non_system = non_system[-self.max_messages:]
        self.messages = system + non_system

    def to_openai_format(self) -> list[dict[str, Any]]:
        return [m.to_openai_dict() for m in self.messages]

    def clear(self) -> None:
        system = [m for m in self.messages if m.role == Role.SYSTEM]
        self.messages = system
