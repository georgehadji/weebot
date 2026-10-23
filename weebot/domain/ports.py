"""Domain ports (interfaces) for weebot — zero external dependencies."""

from __future__ import annotations
from typing import Any, Protocol, runtime_checkable

from weebot.domain.models import Project


@runtime_checkable
class IModelProvider(Protocol):
    """Port for AI model providers (Kimi, DeepSeek, Claude, GPT)."""

    async def generate(
        self,
        prompt: str,
        task_type: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> str: ...

    async def estimate_cost(self, prompt: str, task_type: str) -> float: ...


@runtime_checkable
class IRepository(Protocol):
    """Port for persistent project storage."""

    async def save_project(self, project: Project) -> None: ...
    async def load_project(self, project_id: str) -> Project: ...
    async def list_projects(self) -> list[dict[str, Any]]: ...
    async def delete_project(self, project_id: str) -> None: ...


@runtime_checkable
class INotifier(Protocol):
    """Port for multi-channel notifications."""

    async def notify(
        self, title: str, message: str, level: str = "info", project_id: str | None = None
    ) -> None: ...


@runtime_checkable
class ITool(Protocol):
    """Port for execution tools (PowerShell, Browser, etc.)."""

    @property
    def name(self) -> str: ...

    async def execute(self, command: str) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Domain Event Publisher — lightweight protocol so domain services can emit
# events without depending on any outer-layer event bus implementation.
# ---------------------------------------------------------------------------


class EventPublisher(Protocol):
    """Protocol for publishing domain events.

    Domain services (e.g. WorkingMemory) depend on this protocol, not on
    any concrete bus (EventBroker, AsyncEventBus, etc.).  The application
    or infrastructure layer injects the actual implementation.
    """

    async def publish(
        self, event_type: str, agent_id: str, data: dict[str, Any] | None = None
    ) -> bool:
        """Publish a domain event.

        Returns:
            True if delivery succeeded, False otherwise.
        """
        ...


# ---------------------------------------------------------------------------
# Repository roles (W5.1, F26). StateRepositoryPort holds the session methods;
# these are the other persistence roles a repository may also play. A caller
# resolves its role with ``as_role`` and skips the feature when it is absent,
# instead of duck typing into an AttributeError.
# ---------------------------------------------------------------------------


def as_role(obj: Any, role: type) -> Any:
    """*obj* when it has every method of the *role* protocol, else None.

    By attribute lookup rather than ``isinstance``: on Python 3.12 a
    runtime-checkable protocol checks attributes statically, which a test
    double built on ``MagicMock`` never satisfies.
    """
    if obj is None:
        return None
    members = getattr(role, "__protocol_attrs__", None) or {
        name for name in vars(role) if not name.startswith("_")
    }
    return obj if all(callable(getattr(obj, name, None)) for name in members) else None


@runtime_checkable
class PlanTemplateStore(Protocol):
    """Read side of the plan-template cache."""

    async def find_plan_templates_by_hash(self, task_hash: str, limit: int = 3) -> list[dict]: ...
    async def list_all_plan_templates(self, limit: int = 200) -> list[dict]: ...


@runtime_checkable
class CommitmentStore(Protocol):
    """Commitments the agent made, as domain objects."""

    async def save_commitment(self, commitment: Any, commit: bool = True) -> None: ...
    async def list_commitments(self, status: str | None = None) -> list[Any]: ...
    async def update_commitment_status(
        self, commitment_id: str, status: str, failure_reason: str | None = None
    ) -> None: ...
