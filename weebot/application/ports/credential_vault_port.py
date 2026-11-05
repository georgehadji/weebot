"""CredentialVaultPort -- fill a login field without the model ever holding the value (H19).

A handle is an opaque id bound to one origin (``https://github.com``). The model names the
handle (``vault:github``); the adapter reads the secret, checks that the page is on the handle's
origin, and types it into the field. The value is never returned, so it cannot reach an event,
a log or the transcript through this port.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal


class CredentialError(RuntimeError):
    """The fill was refused or failed. The message never contains a secret value."""


@dataclass(frozen=True)
class CredentialHandle:
    id: str
    origin: str
    label: str = ""


class CredentialVaultPort(ABC):
    @abstractmethod
    def list_handles(self, origin: str) -> list[CredentialHandle]:
        """The handles bound to *origin* (scheme, host and port)."""

    @abstractmethod
    async def fill(
        self,
        handle_id: str,
        page: Any,
        *,
        selector: str,
        field: Literal["username", "password"] = "password",
        timeout_ms: int = 30000,
    ) -> None:
        """Type the handle's *field* into *selector* on *page*.

        Raises CredentialError for an unknown handle, a page on another origin, or a secret
        that cannot be read.
        """

    @abstractmethod
    def redact(self, text: str) -> str:
        """*text* with every value this vault has filled replaced by a marker."""
