"""SchedulingManager - APScheduler-based task scheduling with persistence."""
from __future__ import annotations

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
        self._save_job(job)

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
        self._save_job(job)

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

        # Remove from database
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('DELETE FROM jobs WHERE job_id = ?', (job_id,))
            conn.commit()

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

        self._running_jobs.add(job_id)
        try:
            # Update status
            job.status = JobStatus.RUNNING.value
            job.last_run = datetime.now()
            self._save_job(job)

            # Execute callable if registered
            if job.callable_name and job.callable_name in self._callables:
                func = self._callables[job.callable_name]
                if callable(func):
                    result = func()
                    if hasattr(result, '__await__'):
                        await result
                logger.info("Executed job: %s", job_id)

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
            self._save_job(job)

    def _save_job(self, job: ScheduledJob) -> None:
        """Save job to database.

        Args:
            job: ScheduledJob to save
        """
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

    async def start(self) -> None:
        """Start the scheduler."""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Scheduler started")

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
        self._save_job(job)
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
        self._save_job(job)

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
