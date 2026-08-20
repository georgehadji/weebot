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
from datetime import datetime, UTC
from typing import Any

from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.domain.models.event import SessionStalenessEvent
from weebot.domain.models.session import SessionStatus
from weebot.infrastructure.observability import metrics

logger = logging.getLogger(__name__)

STALE_THRESHOLD_MINUTES = 60
COMPACT_INTERVAL_HOURS = 4
HEALTH_INTERVAL_HOURS = 12
# Backup: once daily at 03:00 UTC.  Paths set via env vars.
BACKUP_DB_PATH_ENV = "WEEBOT_SESSIONS_DB"
BACKUP_DEST_DIR_ENV = "WEEBOT_BACKUP_DIR"


# ── Job implementations ──────────────────────────────────────────────


async def _session_health_job(state_repo: StateRepositoryPort, event_bus: EventBusPort) -> None:
    """Scan all RUNNING sessions and publish SessionStalenessEvent for stale ones."""
    sessions = await state_repo.list_sessions()
    now = datetime.now(UTC)
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
            updated = updated.replace(tzinfo=UTC)
        staleness = (now - updated).total_seconds() / 60
        if staleness > STALE_THRESHOLD_MINUTES:
            await event_bus.publish(
                SessionStalenessEvent(
                    session_id=session.id, staleness_minutes=staleness, status=session.status.value
                )
            )
            stale_count += 1

    metrics.session_stale_count.set(stale_count)
    logger.info(
        "Session health check: %d sessions checked, %d stale (threshold=%d min)",
        len(sessions),
        stale_count,
        STALE_THRESHOLD_MINUTES,
    )


async def _memory_compact_job(state_repo: StateRepositoryPort) -> None:
    """Compact RUNNING sessions that have accumulated many events."""
    from weebot.application.services.memory_compactor import MemoryCompactor

    # list_sessions() is a lightweight listing (events not populated — see
    # SQLiteStateRepository._row_to_session's load_events=False fast path),
    # so re-load each RUNNING session in full before compacting it.
    sessions = await state_repo.list_sessions()
    compactor = MemoryCompactor()
    compacted_count = 0

    for session_summary in sessions:
        if session_summary.status != SessionStatus.RUNNING:
            continue
        try:
            session = await state_repo.load_session(session_summary.id)
            if session is None:
                continue
            compacted = compactor.compact_session(session)
            if compacted is not session:  # identity check — compactor returns new instance
                await state_repo.save_session(compacted)
                compacted_count += 1
        except Exception:
            logger.exception("Compaction failed for session %s", session_summary.id)

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


async def _database_backup_job() -> None:
    """Run daily online backup of the sessions database.

    Reads database path from ``WEEBOT_SESSIONS_DB`` and backup destination
    directory from ``WEEBOT_BACKUP_DIR``.  Skips silently if ``WEEBOT_BACKUP_DIR``
    is not set (local dev mode).
    """
    import os
    import sys
    from pathlib import Path

    import weebot.config.settings as _settings

    settings = _settings.WeebotSettings()
    db_path = settings.sessions_db_path or os.environ.get("WEEBOT_SESSIONS_DB")
    backup_dir = os.environ.get("WEEBOT_BACKUP_DIR")

    if not db_path or not backup_dir:
        logger.info("Database backup skipped: set WEEBOT_BACKUP_DIR to enable")
        return

    db_file = Path(db_path)
    dest_dir = Path(backup_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    import asyncio

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(Path(__file__).resolve().parent.parent.parent / "scripts" / "backup.py"),
            "--db",
            str(db_file),
            "--dest",
            str(dest_dir),
            "--label",
            "weebot_sessions",
            "--retention",
            "30",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        logger.error(
            "Database backup failed to start: %s (executable=%s, db=%s)",
            exc,
            sys.executable,
            db_file,
        )
        return

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    except TimeoutError:
        proc.kill()
        await proc.wait()  # prevent zombie
        logger.error("Database backup timed out after 300s")
        return

    if proc.returncode == 0:
        logger.info("Database backup completed: %s", stdout.decode()[:500].strip())
    else:
        logger.error(
            "Database backup FAILED (exit %d): %s", proc.returncode, stderr.decode()[:2000].strip()
        )


async def _memory_salience_sweep_job(state_repo: StateRepositoryPort) -> None:
    """Evict low-salience memory entries that are past their TTL."""
    from weebot.application.services.memory_lifecycle_service import MemoryLifecycleService

    stats = await MemoryLifecycleService().sweep(repo=state_repo)
    logger.info("Memory salience sweep: checked=%d, evicted=%d", stats["checked"], stats["evicted"])


async def _commitment_heartbeat_job(state_repo: StateRepositoryPort) -> None:
    """Scan for overdue commitments and refresh their statuses."""
    from weebot.domain.services.commitment_engine import CommitmentEngine

    stats = await CommitmentEngine(state_repo=state_repo).heartbeat()
    logger.info(
        "Commitment heartbeat: checked=%d, overdue=%d, pending=%d",
        stats["checked"],
        stats["marked_overdue"],
        stats["active_pending"],
    )


async def _behavioral_consolidation_job(state_repo: StateRepositoryPort) -> None:
    """Rebuild the consolidated user model from recorded behaviour."""
    from weebot.application.services.user_model_consolidator import UserModelConsolidator

    profile = await UserModelConsolidator(state_repo=state_repo).consolidate()
    logger.info(
        "User-model consolidation: profile (%d chars, %d words)", len(profile), len(profile.split())
    )


async def _integrity_check_job() -> None:
    """Report uncommitted work and low disk space."""
    import shutil
    import subprocess
    from pathlib import Path

    issues: list[str] = []
    try:
        result = await asyncio.to_thread(
            lambda: subprocess.run(
                ["git", "status", "--porcelain"], capture_output=True, text=True, timeout=10
            )
        )
        if result.stdout.strip():
            issues.append(f"Uncommitted changes: {len(result.stdout.strip().splitlines())} files")
    except Exception as exc:
        issues.append(f"Git check failed: {exc}")

    _total, _used, free = shutil.disk_usage(Path.cwd())
    if free // (2**30) < 1:
        issues.append("Low disk space")

    logger.info("Integrity check: %s", issues or "all clear")


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
            "weebot_session_health",
            "Session Health Snapshot",
            lambda: _session_health_job(state_repo, event_bus),
        ),
    )
    scheduler.register_callable(
        "weebot_memory_compact",
        _with_job_metrics(
            "weebot_memory_compact", "Memory Compaction", lambda: _memory_compact_job(state_repo)
        ),
    )
    scheduler.register_callable(
        "weebot_skill_curation",
        _with_job_metrics(
            "weebot_skill_curation", "Skill Curation", lambda: _skill_curation_job(llm_port)
        ),
    )
    scheduler.register_callable(
        "weebot_database_backup",
        _with_job_metrics(
            "weebot_database_backup", "Database Backup", lambda: _database_backup_job()
        ),
    )

    # ── Callables for the jobs declared in config/jobs.yaml ──────────
    for _job_id, _job_name, _job_call in (
        (
            "memory_salience_sweep",
            "Memory Salience Sweep",
            lambda: _memory_salience_sweep_job(state_repo),
        ),
        (
            "commitment_heartbeat",
            "Commitment Heartbeat",
            lambda: _commitment_heartbeat_job(state_repo),
        ),
        (
            "behavioral_consolidation",
            "Behavioural Rule Consolidation",
            lambda: _behavioral_consolidation_job(state_repo),
        ),
        ("integrity_check", "Self Integrity Check", _integrity_check_job),
    ):
        scheduler.register_callable(_job_id, _with_job_metrics(_job_id, _job_name, _job_call))

    # ── Create jobs (idempotent) ────────────────────
    await _create_if_absent(
        scheduler,
        "weebot_session_health",
        name="Session Health Snapshot",
        trigger_type="interval",
        trigger_config={"hours": HEALTH_INTERVAL_HOURS},
        callable_name="weebot_session_health",
        description="Scan sessions for staleness every 12 hours",
    )

    await _create_if_absent(
        scheduler,
        "weebot_memory_compact",
        name="Memory Compaction",
        trigger_type="interval",
        trigger_config={"hours": COMPACT_INTERVAL_HOURS},
        callable_name="weebot_memory_compact",
        description="Compact long-running session buffers every 4 hours",
    )

    await _create_if_absent(
        scheduler,
        "weebot_skill_curation",
        name="Skill Curation",
        trigger_type="cron",
        trigger_config={"hour": 2, "minute": 0},
        callable_name="weebot_skill_curation",
        description="Classify and review stale skills daily at 02:00",
    )

    await _create_if_absent(
        scheduler,
        "weebot_database_backup",
        name="Database Backup",
        trigger_type="cron",
        trigger_config={"hour": 3, "minute": 0},
        callable_name="weebot_database_backup",
        description="Online backup of sessions database daily at 03:00",
    )

    # ── Jobs declared in config/jobs.yaml ────────────
    # Disabled entries are persisted but never scheduled.
    await scheduler.load_from_config()


async def _create_if_absent(scheduler: Any, job_id: str, **kwargs: Any) -> None:
    """Create a scheduled job only if it does not already exist."""
    existing = scheduler.get_job(job_id)
    if existing is not None:
        logger.debug("Job %s already exists — skipping creation", job_id)
        return
    await scheduler.create_job(job_id=job_id, **kwargs)
    logger.info("Created job %s", job_id)
