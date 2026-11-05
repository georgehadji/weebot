"""SecretSourcePort -- where a secret reference such as ``op://vault/item/field`` is read (H19).

A reference replaces a plaintext value in ``.env``; a source turns it into the value once, at
startup. Sources only read.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class SecretSourceError(RuntimeError):
    """The source could not be asked: tool missing, timed out, refused. Never carries a value."""


@dataclass(frozen=True)
class ResolvedSecret:
    value: str = field(repr=False)  # repr and logs show the source, never this
    source: str


class SecretSourcePort(ABC):
    scheme: str  # the reference prefix this source handles, without ``://``
    name: str  # what provenance shows

    @abstractmethod
    def resolve(self, ref: str) -> ResolvedSecret | None:
        """The secret *ref* names, or None when the source has none. Raises SecretSourceError."""
