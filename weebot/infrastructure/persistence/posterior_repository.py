"""PosteriorRepository — durable storage for Beta-Bernoulli posterior beliefs.

Schema::

    CREATE TABLE IF NOT EXISTS acr_posteriors (
        category      TEXT NOT NULL,
        model         TEXT NOT NULL,
        alpha         REAL NOT NULL DEFAULT 1.0,
        beta          REAL NOT NULL DEFAULT 1.0,
        updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (category, model)
    );

One row per ``(category, model)`` pair.  ``alpha`` is the pseudo-count of
successes, ``beta`` the pseudo-count of failures.  Posteriors are initialised
with benchmark priors (strong, conservative pseudo-counts) at first write.
"""
from __future__ import annotations

import asyncio
import logging
import math
import sqlite3
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS acr_posteriors (
    category    TEXT NOT NULL,
    model       TEXT NOT NULL,
    alpha       REAL NOT NULL DEFAULT 1.0,
    beta        REAL NOT NULL DEFAULT 1.0,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (category, model)
);
"""

# Default decay factor for exponential forgetting (γ < 1).
# Each update multiplies alpha and beta by GAMMA before adding the new
# observation, so older observations are gradually discounted.
_DECAY_GAMMA: float = 0.95

# Strong prior pseudo-counts for cold-start.
# E.g. (alpha=5, beta=1) → prior success rate ≈ 5/6 ≈ 83%.
_PRIOR_ALPHA: float = 5.0
_PRIOR_BETA: float = 1.0


class PosteriorRepository:
    """Durable Beta-Bernoulli posterior store backed by SQLite.

    Thread-safe via per-connection locking.  Async callers offload sync
    SQLite I/O to the default thread-pool executor.

    Args:
        db_path: Path to the SQLite database file.  Defaults to
            ``acr_posteriors.db`` alongside the session DB.
        decay: Exponential forgetting factor (default 0.95).
            Each upsert multiplies (alpha, beta) by this factor before
            incrementing the relevant pseudo-count.
    """

    def __init__(
        self,
        db_path: str | Path = "acr_posteriors.db",
        decay: float = _DECAY_GAMMA,
    ) -> None:
        self._db_path = Path(db_path)
        self._decay = decay
        self._lock = asyncio.Lock()  # serialise async writes
        self._ensure_schema()

    # ── Schema management ───────────────────────────────────────────

    def _ensure_schema(self) -> None:
        """Create the posteriors table if it doesn't exist."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_DDL)
            conn.commit()
        _log.info("PosteriorRepository: schema ensured at %s", self._db_path)

    # ── Write ───────────────────────────────────────────────────────

    async def record_outcome(
        self,
        category: str,
        model: str,
        success: bool,
    ) -> None:
        """Record a single outcome for ``(category, model)``.

        Applies exponential forgetting (decay) before the increment.
        Thread-safe via async lock + exec-serialised SQLite writes.
        """
        async with self._lock:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                self._record_sync,
                category,
                model,
                success,
            )

    def _record_sync(
        self,
        category: str,
        model: str,
        success: bool,
    ) -> None:
        with sqlite3.connect(str(self._db_path)) as conn:
            # Read current posterior (or use prior defaults)
            row = conn.execute(
                "SELECT alpha, beta FROM acr_posteriors WHERE category=? AND model=?",
                (category, model),
            ).fetchone()

            if row is not None:
                alpha, beta = row[0], row[1]
                # Apply exponential forgetting
                alpha *= self._decay
                beta *= self._decay
            else:
                alpha, beta = _PRIOR_ALPHA, _PRIOR_BETA

            # Increment the appropriate pseudo-count
            if success:
                alpha += 1.0
            else:
                beta += 1.0

            conn.execute(
                """INSERT INTO acr_posteriors (category, model, alpha, beta, updated_at)
                   VALUES (?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(category, model) DO UPDATE SET
                     alpha = excluded.alpha,
                     beta = excluded.beta,
                     updated_at = datetime('now')""",
                (category, model, alpha, beta),
            )
            conn.commit()

    # ── Read ────────────────────────────────────────────────────────

    async def get_posterior(
        self,
        category: str,
        model: str,
    ) -> tuple[float, float]:
        """Return ``(alpha, beta)`` for a ``(category, model)``.

        Returns the prior pseudo-counts if no records exist.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._get_posterior_sync,
            category,
            model,
        )

    def _get_posterior_sync(
        self,
        category: str,
        model: str,
    ) -> tuple[float, float]:
        row = self._execute("SELECT alpha, beta FROM acr_posteriors WHERE category=? AND model=?", (category, model))
        if row is None:
            return (_PRIOR_ALPHA, _PRIOR_BETA)
        return (float(row[0]), float(row[1]))

    def _execute(self, query: str, params: tuple = ()):
        """Run a read query against SQLite."""
        with sqlite3.connect(str(self._db_path)) as conn:
            return conn.execute(query, params).fetchone()

    async def get_all_posteriors(self) -> dict[str, dict[str, tuple[float, float]]]:
        """Return all stored posteriors as ``{category: {model: (alpha, beta)}}``.

        Does NOT include priors for unseen (category, model) pairs.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._get_all_sync)

    def _get_all_sync(self) -> dict[str, dict[str, tuple[float, float]]]:
        result: dict[str, dict[str, tuple[float, float]]] = {}
        with sqlite3.connect(str(self._db_path)) as conn:
            rows = conn.execute(
                "SELECT category, model, alpha, beta FROM acr_posteriors",
            ).fetchall()
            for cat, model, alpha, beta in rows:
                result.setdefault(cat, {})[model] = (alpha, beta)
        return result

    async def decay_all(self) -> None:
        """Apply exponential forgetting to every stored posterior.

        Useful for batch decay on a schedule (e.g. daily) in addition to
        per-update decay.
        """
        async with self._lock:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._decay_all_sync)

    def _decay_all_sync(self) -> None:
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                "UPDATE acr_posteriors SET alpha=alpha*?, beta=beta*?, updated_at=datetime('now')",
                (self._decay, self._decay),
            )
            conn.commit()

    async def close(self) -> None:
        """No-op: connections are short-lived per operation."""
        pass
