"""Where each resolved secret came from, and which references failed (H19).

Names and source labels only, never a value: ``weebot doctor`` and the startup log read it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache


@dataclass
class SecretProvenance:
    resolved: dict[str, str] = field(default_factory=dict)  # env name -> source label
    failed: dict[str, str] = field(default_factory=dict)  # env name -> why (no value)

    def clear(self) -> None:
        self.resolved.clear()
        self.failed.clear()


@lru_cache(maxsize=1)
def provenance() -> SecretProvenance:
    return SecretProvenance()
