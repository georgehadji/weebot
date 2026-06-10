"""Default scheduled jobs registered at application startup.

All jobs are plain async callables registered with SchedulingManager via
register_callable(). Each job is created idempotently: if it already exists
in the persisted job store it is skipped.

Layer: this module sits at the boundary of Application and Infrastructure.
It imports Application ports (via container) and Infrastructure (scheduler).
It does NOT import from Interfaces.
"""
from __future__ import annotations

import asyncio
import logging
import time as _time
from datetime import datetime, timezone
from typing import Any

from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.domain.models.event import ScheduledJobEvent, SessionStalenessEvent
from weebot.domain.models.session import SessionStatus
from weebot.infrastructure.observability import metrics

logger = logging.getLogger(__name__)

STALE_THRESHOLD_MINUTES = 60
COMPACT_INTERVAL_HOURS = 4
HEALTH_INTERVAL_HOURS = 12


# ── Job implementations ──────────────────────────────────────────────

async def _session_health_job(state_repo: StateRepositoryPort, event_bus: EventBusPort) -> None:
    """Scan all RUNNING sessions and publish SessionStalenessEvent for stale ones."""
    sessions = await state_repo.list_sessions()
    now = datetime.now(timezone.utc)
    stale_count = 0

    for session in sessions:
        if session.status != SessionStatus.RUNNING:
            continue
        # Guard: updated_at can be None on legacy sessions; skip
        if session.updated_at is None:
            continue
        # Normalize to UTC (SQLite may return naive datetimes)
        updated = session.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        staleness = (now - updated).total_seconds() / 60
        if staleness > STALE_THRESHOLD_MINUTES:
            await event_bus.publish(SessionStalenessEvent(
                session_id=session.id,
                staleness_minutes=staleness,
                status=session.status.value,
            ))
            stale_count += 1

    metrics.session_stale_count.set(stale_count)
    logger.info("Session health check: %d sessions checked, %d stale (threshold=%d min)",
                len(sessions), stale_count, STALE_THRESHOLD_MINUTES)


async def _memory_compact_job(state_repo: StateRepositoryPort) -> None:
    """Compact RUNNING sessions that have accumulated many events."""
    from weebot.application.services.memory_compactor import MemoryCompactor

    sessions = await state_repo.list_sessions()
    compactor = MemoryCompactor()
    compacted_count = 0

    for session in sessions:
        if session.status != SessionStatus.RUNNING:
            continue
        try:
            compacted = compactor.compact_session(session)
            if compacted is not session:  # identity check — compactor returns new instance
                await state_repo.save_session(compacted)
                compacted_count += 1
        except Exception:
            logger.exception("Compaction failed for session %s", session.id)

    logger.info("Memory compaction: %d sessions compacted", compacted_count)


async def _skill_curation_job(llm_port: Any) -> None:
    """Run weekly skill curation via the SkillCurator service."""
    from weebot.application.services.skill_curator import SkillCurator
    from weebot.application.skills.skill_registry import SkillRegistry

    registry = SkillRegistry()
    registry.load_all()
    curator = SkillCurator(registry=registry, llm=llm_port)
    await curator.run_curation()
    logger.info("Skill curation completed")


# ── ScheduledJobEvent wrapper ────────────────────────────────────────

def _with_job_metrics(job_id: str, job_name: str, callable: Any):
    """Wrap a job callable with ScheduledJobEvent emission and Prometheus counters."""

    async def wrapper() -> None:
        metrics.scheduled_jobs_active.inc()
        t0 = _time.monotonic()
        try:
            await callable()
            duration = _time.monotonic() - t0
            metrics.scheduled_jobs_runs_total.labels(job_id=job_id, outcome="success").inc()
            # Publish success event — fire-and-forget (we have no event_bus reference here)
            logger.info("Job %s (%s) completed in %.1fs", job_id, job_name, duration)
        except Exception as exc:
            duration = _time.monotonic() - t0
            metrics.scheduled_jobs_runs_total.labels(job_id=job_id, outcome="failure").inc()
            logger.error("Job %s (%s) failed after %.1fs: %s", job_id, job_name, duration, exc)
            raise  # re-raise so APScheduler records the failure
        finally:
            metrics.scheduled_jobs_active.dec()

    return wrapper


# ── Registration ─────────────────────────────────────────────────────

async def register_default_jobs(scheduler: Any, container: Any) -> None:
    """Register and create the default cron/interval jobs.

    Idempotent across server restarts — checks ``scheduler.get_job()``
    for each job before creating it.

    Args:
        scheduler: ``SchedulingManager`` instance from DI.
        container: ``Container`` instance for resolving ports.
    """
    state_repo = container.get(StateRepositoryPort)
    event_bus = container.get(EventBusPort)
    from weebot.application.ports.llm_port import LLMPort
    llm_port = container._maybe_get(LLMPort)

    # ── Register callables ──────────────────────────
    scheduler.register_callable(
        "weebot_session_health",
        _with_job_metrics(
            "weebot_session_health", "Session Health Snapshot",
            lambda: _session_health_job(state_repo, event_bus),
        ),
    )
    scheduler.register_callable(
        "weebot_memory_compact",
        _with_job_metrics(
            "weebot_memory_compact", "Memory Compaction",
            lambda: _memory_compact_job(state_repo),
        ),
    )
    scheduler.register_callable(
        "weebot_skill_curation",
        _with_job_metrics(
            "weebot_skill_curation", "Skill Curation",
            lambda: _skill_curation_job(llm_port),
        ),
    )

    # ── Create jobs (idempotent) ────────────────────
    _create_if_absent(scheduler, "weebot_session_health", name="Session Health Snapshot",
                      trigger_type="interval", trigger_config={"hours": HEALTH_INTERVAL_HOURS},
                      callable_name="weebot_session_health",
                      description="Scan sessions for staleness every 12 hours")

    _create_if_absent(scheduler, "weebot_memory_compact", name="Memory Compaction",
                      trigger_type="interval", trigger_config={"hours": COMPACT_INTERVAL_HOURS},
                      callable_name="weebot_memory_compact",
                      description="Compact long-running session buffers every 4 hours")

    _create_if_absent(scheduler, "weebot_skill_curation", name="Skill Curation",
                      trigger_type="cron", trigger_config={"hour": 2, "minute": 0},
                      callable_name="weebot_skill_curation",
                      description="Classify and review stale skills daily at 02:00")


async def _create_if_absent(scheduler: Any, job_id: str, **kwargs: Any) -> None:
    """Create a scheduled job only if it does not already exist."""
    existing = scheduler.get_job(job_id)
    if existing is not None:
        logger.debug("Job %s already exists — skipping creation", job_id)
        return
    await scheduler.create_job(job_id=job_id, **kwargs)
    logger.info("Created job %s", job_id)
