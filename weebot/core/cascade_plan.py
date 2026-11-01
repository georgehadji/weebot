"""The order in which one LLM call tries its models.

A pure function of the role's whole model list, so a table of cases tests it with no mocks.
The cascade shell filters the result (tripped breakers, server errors, soft cost limit,
tainted-session privacy) and runs it; this module only decides the order.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

# Role-list entries that run as hedged phase-1 probes: the primary and the first fallback.
PROBE_ROLE_SLOTS = 2


@dataclass(frozen=True)
class CascadePlan:
    probes: tuple[str, ...]
    """Phase 1, hedged: one runs and the next starts when it fails or the delay runs out."""
    fallbacks: tuple[str, ...]
    """Phase 2, one at a time: the rest of the role list in order, the premium model last."""


def _unique(names: Iterable[str | None]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(n for n in names if n))


def build_cascade_plan(
    role_cascade: list[str],
    *,
    tier2: str,
    tier3: str,
    tier4: str,
    pinned: str | None = None,
    extra_probes: Iterable[str | None] = (),
) -> CascadePlan:
    """Order every model of *role_cascade*, so none is skipped and premium comes last.

    Entries from index 3 on used to be unreachable, and a local or free model prepended to the
    list shifted paid models out of their slots (audit F12). A list shorter than the slots falls
    back to *tier2* and *tier3*, as before.
    """
    primary = role_cascade[:1]
    first_fallback = role_cascade[1:PROBE_ROLE_SLOTS] or [tier2]
    probes = _unique([pinned, *primary, *extra_probes, *first_fallback])

    rest = role_cascade[PROBE_ROLE_SLOTS:] or [tier3]
    fallbacks = (*(n for n in _unique(rest) if n != tier4), tier4)
    return CascadePlan(probes=probes, fallbacks=fallbacks)
