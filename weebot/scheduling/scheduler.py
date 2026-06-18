"""SchedulingManager - APScheduler-based task scheduling with persistence."""
from __future__ import annotations

import asyncio
import sqlite3
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional, Callable, Any, Dict, List
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger

logger = logging.getLogger(__name__)


class JobStatus(Enum):
    """Status of a scheduled job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class TriggerType(Enum):
    """Type of trigger for job scheduling."""
    CRON = "cron"
    INTERVAL = "interval"
    DATE = "date"
    ONCE = "once"


@dataclass
class ScheduledJob:
    """Represents a scheduled job."""
    job_id: str
    name: str
    description: Optional[str] = None
    trigger_type: str = "cron"
    trigger_config: Dict[str, Any] = None
    command: Optional[str] = None  # Command to execute
    callable_name: Optional[str] = None  # Name of callable to invoke
    status: str = "pending"
    created_at: Optional[datetime] = None
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    run_count: int = 0
    error_count: int = 0
    last_error: Optional[str] = None
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.trigger_config is None:
            self.trigger_config = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        data['created_at'] = self.created_at.isoformat() if self.created_at else None
        data['last_run'] = self.last_run.isoformat() if self.last_run else None
        data['next_run'] = self.next_run.isoformat() if self.next_run else None
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ScheduledJob:
        """Create from dictionary."""
        data = dict(data)
        if data.get('created_at'):
            data['created_at'] = datetime.fromisoformat(data['created_at'])
        if data.get('last_run'):
            data['last_run'] = datetime.fromisoformat(data['last_run'])
        if data.get('next_run'):
            data['next_run'] = datetime.fromisoformat(data['next_run'])
        # Deserialize trigger_config if it's a JSON string
        if isinstance(data.get('trigger_config'), str):
            data['trigger_config'] = json.loads(data['trigger_config'])
        return cls(**data)


class SchedulingManager:
    """Manages scheduled jobs with APScheduler and SQLite persistence."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """Initialize scheduling manager.

        Args:
            db_path: Path to SQLite database for job persistence
        """
        self.db_path = db_path or Path.home() / '.weebot' / 'jobs.db'
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.scheduler = AsyncIOScheduler()
        self._callables: Dict[str, Callable] = {}
        # Defence-in-depth: track currently executing job IDs so that
        # the update_job() race window (remove_job → re-add) cannot cause
        # double execution. APScheduler's max_instances=1 is the primary
        # guard at the scheduler level; this set is the secondary guard
        # inside _execute_job() for the edge case where a queued coroutine
        # was already dispatched before remove_job() was called.
        self._running_jobs: set = set()
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    trigger_type TEXT NOT NULL,
                    trigger_config TEXT NOT NULL,
                    command TEXT,
                    callable_name TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_run TEXT,
                    next_run TEXT,
                    run_count INTEGER DEFAULT 0,
                    error_count INTEGER DEFAULT 0,
                    last_error TEXT,
                    enabled INTEGER DEFAULT 1
                )
            ''')
            conn.commit()

    def register_callable(self, name: str, func: Callable) -> None:
        """Register a callable that can be triggered by scheduled jobs.

        Args:
            name: Name to register callable under
            func: Callable to register
        """
        self._callables[name] = func
        logger.info(f"Registered callable: {name}")

    async def create_job(
        self,
        job_id: str,
        name: str,
        trigger_type: str,
        trigger_config: Dict[str, Any],
        command: Optional[str] = None,
        callable_name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> ScheduledJob:
        """Create a new scheduled job.

        Args:
            job_id: Unique job identifier
            name: Human-readable job name
            trigger_type: Type of trigger (cron, interval, date, once)
            trigger_config: Configuration for trigger
            command: Command to execute (for bash/python)
            callable_name: Name of registered callable to invoke
            description: Job description

        Returns:
            ScheduledJob instance
        """
        if not command and not callable_name:
            raise ValueError("Either command or callable_name must be provided")

        job = ScheduledJob(
            job_id=job_id,
            name=name,
            description=description,
            trigger_type=trigger_type,
            trigger_config=trigger_config,
            command=command,
            callable_name=callable_name,
            status=JobStatus.PENDING.value,
        )

        # Store in database
        await self._save_job(job)

        # Schedule if enabled
        if job.enabled:
            await self._schedule_job(job)

        logger.info(f"Created job: {job_id} ({name})")
        return job

    async def update_job(
        self,
        job_id: str,
        **kwargs: Any,
    ) -> ScheduledJob:
        """Update a scheduled job.

        Args:
            job_id: Job to update
            **kwargs: Fields to update (name, trigger_config, enabled, etc.)

        Returns:
            Updated ScheduledJob instance
        """
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")

        # Unschedule current job
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

        # Update fields
        for key, value in kwargs.items():
            if hasattr(job, key):
                setattr(job, key, value)

        # Reschedule if enabled
        if job.enabled:
            await self._schedule_job(job)

        # Save to database
        await self._save_job(job)

        logger.info(f"Updated job: {job_id}")
        return job

    async def delete_job(self, job_id: str) -> bool:
        """Delete a scheduled job.

        Args:
            job_id: Job to delete

        Returns:
            True if deleted, False if not found
        """
        job = self.get_job(job_id)
        if not job:
            return False

        # Unschedule
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

        # Remove from database (offload to thread pool)
        def _delete():
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('DELETE FROM jobs WHERE job_id = ?', (job_id,))
                conn.commit()
        await asyncio.to_thread(_delete)

        logger.info(f"Deleted job: {job_id}")
        return True

    def get_job(self, job_id: str) -> Optional[ScheduledJob]:
        """Get a job by ID.

        Args:
            job_id: Job ID to retrieve

        Returns:
            ScheduledJob if found, None otherwise
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                'SELECT * FROM jobs WHERE job_id = ?',
                (job_id,)
            ).fetchone()
            if row:
                return ScheduledJob.from_dict(dict(row))
        return None

    def _run_db(self, func, *args, **kwargs):
        """Run a synchronous DB operation in a thread pool."""
        return asyncio.to_thread(lambda: func(*args, **kwargs))

    def list_jobs(
        self,
        status: Optional[str] = None,
        enabled_only: bool = False,
    ) -> List[ScheduledJob]:
        """List all jobs with optional filtering.

        Args:
            status: Filter by status (pending, running, completed, failed, paused)
            enabled_only: Only return enabled jobs

        Returns:
            List of ScheduledJob instances
        """
        query = 'SELECT * FROM jobs WHERE 1=1'
        params: List[Any] = []

        if status:
            query += ' AND status = ?'
            params.append(status)

        if enabled_only:
            query += ' AND enabled = 1'

        query += ' ORDER BY created_at DESC'

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [ScheduledJob.from_dict(dict(row)) for row in rows]

    async def _schedule_job(self, job: ScheduledJob) -> None:
        """Schedule a job with APScheduler.

        Args:
            job: ScheduledJob to schedule
        """
        # Create trigger based on type
        trigger = self._create_trigger(job.trigger_type, job.trigger_config)

        # Create job function
        async def job_wrapper() -> None:
            await self._execute_job(job.job_id)

        # Add to scheduler.
        # max_instances=1 is the primary guard: APScheduler will skip a new
        # invocation if the previous one hasn't finished yet.
        # coalesce=True merges missed executions (e.g. after sleep/suspend)
        # into a single catch-up run rather than firing N times.
        self.scheduler.add_job(
            job_wrapper,
            trigger=trigger,
            id=job.job_id,
            name=job.name,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        logger.info(f"Scheduled job: {job.job_id} with {job.trigger_type} trigger")

    def _create_trigger(self, trigger_type: str, config: Dict[str, Any]) -> Any:
        """Create APScheduler trigger based on type.

        Args:
            trigger_type: Type of trigger (cron, interval, date, once)
            config: Trigger configuration

        Returns:
            APScheduler trigger instance
        """
        if trigger_type == TriggerType.CRON.value:
            # Cron trigger: config = {hour: 12, minute: 30, day_of_week: 'mon-fri'}
            return CronTrigger(**config)

        elif trigger_type == TriggerType.INTERVAL.value:
            # Interval trigger: config = {seconds: 300} or {hours: 1}
            return IntervalTrigger(**config)

        elif trigger_type == TriggerType.DATE.value:
            # Date trigger: config = {run_date: '2026-03-15 14:30:00'}
            run_date = config.get('run_date')
            if isinstance(run_date, str):
                run_date = datetime.fromisoformat(run_date)
            return DateTrigger(run_date=run_date)

        elif trigger_type == TriggerType.ONCE.value:
            # One-time execution
            run_date = config.get('run_date')
            if isinstance(run_date, str):
                run_date = datetime.fromisoformat(run_date)
            return DateTrigger(run_date=run_date)

        else:
            raise ValueError(f"Unknown trigger type: {trigger_type}")

    async def _execute_job(self, job_id: str) -> None:
        """Execute a scheduled job.

        Secondary concurrency guard: the _running_jobs set prevents double
        execution in the update_job() race window (the primary guard is
        max_instances=1 in APScheduler, set at add_job() time).

        Args:
            job_id: Job to execute
        """
        # Secondary guard: if this job is already executing (e.g. a queued
        # coroutine that survived a remove_job() + re-add() cycle), skip it.
        if job_id in self._running_jobs:
            logger.warning("Job %s already executing — skipping duplicate invocation", job_id)
            return

        job = self.get_job(job_id)
        if not job or not job.enabled:
            return
        if job.status == JobStatus.PAUSED.value:
            logger.info("Job %s is paused — skipping execution", job_id)
            return

        self._running_jobs.add(job_id)
        try:
            # Update status
            job.status = JobStatus.RUNNING.value
            job.last_run = datetime.now()
            await self._save_job(job)

            # Execute payload
            if job.callable_name:
                func = self._callables.get(job.callable_name)
                if func is None:
                    raise ValueError(
                        f"Callable not registered: {job.callable_name}"
                    )
                if not callable(func):
                    raise TypeError(
                        f"Registered callable is not callable: {job.callable_name}"
                    )
                if asyncio.iscoroutinefunction(func):
                    await func()
                else:
                    func()
                logger.info("Executed job callable: %s", job_id)
            elif job.command:
                # Fail closed instead of reporting false success.
                raise NotImplementedError(
                    "Command execution is not implemented in SchedulingManager; "
                    "register a callable_name for this job."
                )
            else:
                raise ValueError(
                    f"Job {job_id} has neither callable_name nor command"
                )

            # Update success
            job.status = JobStatus.COMPLETED.value
            job.run_count += 1
            job.last_error = None

        except Exception as exc:
            logger.error("Job execution failed: %s: %s", job_id, exc)
            job.status = JobStatus.FAILED.value
            job.error_count += 1
            job.last_error = str(exc)

        finally:
            self._running_jobs.discard(job_id)
            await self._save_job(job)

    async def _save_job(self, job: ScheduledJob) -> None:
        """Save job to database (offloaded to thread pool).

        Args:
            job: ScheduledJob to save
        """
        def _save():
            with sqlite3.connect(self.db_path) as conn:
                job_dict = job.to_dict()
                # JSON-serialize trigger_config for storage
                if isinstance(job_dict.get('trigger_config'), dict):
                    job_dict['trigger_config'] = json.dumps(job_dict['trigger_config'])

                placeholders = ', '.join('?' * len(job_dict))
                cols = ', '.join(job_dict.keys())

                conn.execute(
                    f'INSERT OR REPLACE INTO jobs ({cols}) VALUES ({placeholders})',
                    tuple(job_dict.values())
                )
                conn.commit()
        await asyncio.to_thread(_save)

    async def load_from_config(self, config_path: Optional[Path] = None) -> int:
        """Load job definitions from a YAML config file.

        Args:
            config_path: Path to jobs.yaml. Defaults to project config/jobs.yaml.

        Returns:
            Number of jobs loaded.
        """
        if config_path is None:
            config_path = Path(__file__).resolve().parent.parent / "config" / "jobs.yaml"
        if not config_path.exists():
            logger.warning("Job config not found at %s", config_path)
            return 0

        try:
            import yaml
            with open(config_path) as f:
                data = yaml.safe_load(f)

            loaded = 0
            for job_def in data.get("jobs", []):
                existing = self.get_job(job_def["job_id"])
                if existing is None:
                    await self.create_job(
                        job_id=job_def["job_id"],
                        name=job_def["name"],
                        description=job_def.get("description", ""),
                        trigger_type=job_def["trigger_type"],
                        trigger_config=job_def.get("trigger_config", {}),
                        callable_name=job_def.get("callable_name"),
                    )
                    loaded += 1
            logger.info("Loaded %d jobs from %s", loaded, config_path)
            return loaded
        except Exception as exc:
            logger.error("Failed to load jobs from config: %s", exc)
            return 0

    async def load_cron_agent_jobs(self, jobs_path: Optional[Path] = None) -> int:
        """Load cron agent job records and register CronAgentRunner.

        Reads ``CronJobRecord`` JSON files and registers each as a
        scheduled job with the ``cron_agent_runner`` callable.

        Args:
            jobs_path: Path to cron_jobs.json. Defaults to ~/.weebot/cron_jobs.json.

        Returns:
            Number of cron agent jobs loaded.
        """
        if jobs_path is None:
            jobs_path = Path.home() / ".weebot" / "cron_jobs.json"
        if not jobs_path.exists():
            return 0

        # Register the CronAgentRunner callable if not already registered
        if "cron_agent_runner" not in self._callables:
            try:
                from weebot.application.services.cron_agent_runner import CronAgentRunner
                from weebot.application.di import Container

                container = Container()
                container.configure_defaults()

                async def _run_cron_job(job_id: str) -> None:
                    """Wrapper that loads CronJobRecord and runs it."""
                    import json
                    try:
                        raw = json.loads(jobs_path.read_text(encoding="utf-8"))
                        data = raw.get(job_id)
                        if data is None:
                            logger.error("Cron job %s not found in %s", job_id, jobs_path)
                            return
                        from weebot.domain.models.cron_job import CronJobRecord
                        job = CronJobRecord(**data)

                        runner = CronAgentRunner(
                            llm=container.get("llm_port"),
                            state_repo=container.get("state_repo_port"),
                        )
                        result = await runner.run(job)

                        # Deliver result
                        from weebot.application.services.cron_delivery_service import (
                            CronDeliveryService,
                        )
                        delivery = CronDeliveryService()
                        await delivery.deliver(job, result)

                        # Update job record
                        from datetime import datetime, timezone
                        raw[job_id]["last_run_at"] = datetime.now(timezone.utc).isoformat()
                        raw[job_id]["last_result"] = result[:500]
                        raw[job_id]["run_count"] = data.get("run_count", 0) + 1
                        jobs_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
                    except Exception as exc:
                        logger.error("Cron agent job %s failed: %s", job_id, exc)

                self.register_callable("cron_agent_runner", _run_cron_job)
            except Exception as exc:
                logger.error("Failed to register CronAgentRunner: %s", exc)
                return 0

        # Load jobs from file
        import json
        try:
            data = json.loads(jobs_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to read cron jobs from %s: %s", jobs_path, exc)
            return 0

        loaded = 0
        for job_id, job_data in data.items():
            if not job_data.get("enabled", True):
                continue
            existing = self.get_job(job_id)
            if existing is not None:
                continue  # Already scheduled
            schedule = job_data.get("schedule", "0 * * * *")
            try:
                trigger_config = _parse_cron_expression(schedule)
                await self.create_job(
                    job_id=job_id,
                    name=job_data.get("name", job_id),
                    description=job_data.get("prompt", "")[:100],
                    trigger_type="cron",
                    trigger_config=trigger_config,
                    callable_name="cron_agent_runner",
                )
                loaded += 1
            except Exception as exc:
                logger.error("Failed to schedule cron agent job %s: %s", job_id, exc)

        logger.info("Loaded %d cron agent jobs from %s", loaded, jobs_path)
        return loaded


def _parse_cron_expression(expr: str) -> dict:
    """Parse a cron expression into a dict of keyword args for CronTrigger.

    Supports standard 5-field cron expressions (min hour dom mon dow)
    and simple interval expressions like "30min", "1h", "2hours".
    """
    expr = expr.strip().lower()

    # Interval expressions
    import re as _cron_re
    m = _cron_re.match(r'^(\d+)\s*(min|mins|m)$', expr)
    if m:
        return {"minute": f"*/{m.group(1)}"}
    m = _cron_re.match(r'^(\d+)\s*(h|hour|hours)$', expr)
    if m:
        return {"hour": f"*/{m.group(1)}"}

    # Standard 5-field cron
    parts = expr.split()
    if len(parts) == 5:
        return {
            "minute": parts[0],
            "hour": parts[1],
            "day": parts[2],
            "month": parts[3],
            "day_of_week": parts[4],
        }
    if len(parts) == 6:
        return {
            "second": parts[0],
            "minute": parts[1],
            "hour": parts[2],
            "day": parts[3],
            "month": parts[4],
            "day_of_week": parts[5],
        }

    logger.warning("Unrecognized cron expression: %s — defaulting to hourly", expr)
    return {"minute": "0"}

    async def run_catch_up(self) -> int:
        """Run catch-up for missed scheduled jobs.

        Checks each enabled job: if its last_run is more than 2x the
        interval behind, it executes once immediately to catch up.
        Uses coalesce semantics — at most one catch-up run per job.

        Returns:
            Number of catch-up jobs executed.
        """
        caught_up = 0
        jobs = self.list_jobs(enabled_only=True)
        now = datetime.now()

        for job in jobs:
            if job.last_run is None:
                # Never run — skip catch-up (first run will happen on schedule)
                continue

            # Calculate expected interval in seconds
            interval_hours = job.trigger_config.get("hours", 0)
            interval_minutes = job.trigger_config.get("minutes", 0)
            interval_seconds = job.trigger_config.get("seconds", 0)
            total_seconds = interval_hours * 3600 + interval_minutes * 60 + interval_seconds

            if total_seconds <= 0:
                continue  # Cron-triggered jobs need different catch-up logic

            elapsed = (now - job.last_run).total_seconds()
            if elapsed > total_seconds * 2:
                logger.info(
                    "Catch-up: job '%s' last ran %.1f hours ago (interval: %.1f hrs)",
                    job.job_id, elapsed / 3600, total_seconds / 3600,
                )
                try:
                    await self._execute_job(job.job_id)
                    caught_up += 1
                except Exception as exc:
                    logger.warning("Catch-up execution failed for %s: %s", job.job_id, exc)

        if caught_up:
            logger.info("Catch-up complete: %d jobs executed", caught_up)
        return caught_up

    async def start(self) -> None:
        """Start the scheduler and run catch-up for missed jobs."""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Scheduler started")
            # Run catch-up for missed jobs
            await self.run_catch_up()

    async def stop(self) -> None:
        """Stop the scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Scheduler stopped")

    async def pause_job(self, job_id: str) -> bool:
        """Pause a job (keep scheduled, but skip execution).

        Args:
            job_id: Job to pause

        Returns:
            True if paused, False if not found
        """
        job = self.get_job(job_id)
        if not job:
            return False

        job.status = JobStatus.PAUSED.value
        await self._save_job(job)
        logger.info(f"Paused job: {job_id}")
        return True

    async def resume_job(self, job_id: str) -> bool:
        """Resume a paused job.

        Args:
            job_id: Job to resume

        Returns:
            True if resumed, False if not found
        """
        job = self.get_job(job_id)
        if not job:
            return False

        job.status = JobStatus.PENDING.value
        await self._save_job(job)

        # Reschedule if needed
        if job.enabled and not self.scheduler.get_job(job_id):
            await self._schedule_job(job)

        logger.info(f"Resumed job: {job_id}")
        return True

    def get_next_run_time(self, job_id: str) -> Optional[datetime]:
        """Get next scheduled run time for a job.

        Args:
            job_id: Job to check

        Returns:
            Datetime of next run, or None if not scheduled
        """
        scheduled_job = self.scheduler.get_job(job_id)
        if scheduled_job:
            return scheduled_job.next_run_time
        return None
