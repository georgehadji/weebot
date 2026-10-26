"""StrategyStorePort — the application's contract for cross-domain strategy storage.

`StrategyTransferService` annotated its collaborator with the SQLite adapter it happened
to be handed (`weebot.infrastructure.persistence.strategy_store.StrategyStore`). A
type-only import is still a dependency edge: grimp counts it, and `app-no-infrastructure`
forbids it (WB-01). The service already refuses to construct its own store — this port is
the other half of that rule.

Structural (`Protocol`) rather than an ABC so the existing adapter satisfies it without
inheriting anything: the port describes the two methods this service actually calls.
"""

from __future__ import annotations

from typing import Protocol

from weebot.domain.models.self_improvement import ImprovementStrategy


class StrategyStorePort(Protocol):
    """Persistence for `ImprovementStrategy` rows, queried across domains."""

    async def insert(self, strategy: ImprovementStrategy) -> str:
        """Persist *strategy* and return its id."""
        ...

    async def get_for_domain(
        self, *, target_domain: str, min_score: float, limit: int
    ) -> list[ImprovementStrategy]:
        """Return strategies from OTHER domains with effectiveness >= *min_score*."""
        ...
