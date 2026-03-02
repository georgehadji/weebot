"""ScheduleTool - Agent interface for creating and managing scheduled jobs."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, Dict, Any

from weebot.tools.base import BaseTool, ToolResult
from weebot.scheduling.scheduler import SchedulingManager, TriggerType


# Module-level scheduling manager (singleton)
_scheduler: Optional[SchedulingManager] = None


def get_scheduler() -> SchedulingManager:
    """Get or create the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = SchedulingManager()
    return _scheduler


class ScheduleTool(BaseTool):
    """Schedule jobs and manage scheduled task execution."""

    name: str = "schedule"
    description: str = (
        "Schedule jobs and manage automated task execution. "
        "Supports cron expressions, intervals, and one-time schedules. "
        "See the 'action' parameter for available operations."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "create_job",
                    "list_jobs",
                    "get_job",
                    "delete_job",
                    "pause_job",
                    "resume_job",
                    "start_scheduler",
                    "stop_scheduler",
                    "update_job",
                ],
                "description": "Action to perform",
            },
            "job_id": {
                "type": "string",
                "description": "Job identifier (auto-generated if not provided)",
            },
            "name": {
                "type": "string",
                "description": "Job name (required for create_job)",
            },
            "trigger_type": {
                "type": "string",
                "enum": ["cron", "interval", "date", "once"],
                "description": "Type of trigger (required for create_job)",
            },
            "trigger_config": {
                "type": "object",
                "description": "Trigger configuration (cron: {hour, minute, day_of_week}, interval: {seconds/minutes/hours}, date: {run_date})",
            },
            "description": {
                "type": "string",
                "description": "Job description",
            },
            "callable_name": {
                "type": "string",
                "description": "Name of registered callable to invoke",
            },
            "command": {
                "type": "string",
                "description": "Command to execute",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "running", "completed", "failed", "paused"],
                "description": "Filter by job status (for list_jobs)",
            },
            "enabled_only": {
                "type": "boolean",
                "description": "Only list enabled jobs (for list_jobs)",
            },
        },
        "required": ["action"],
    }

    async def execute(
        self,
        action: str,
        job_id: Optional[str] = None,
        name: Optional[str] = None,
        trigger_type: Optional[str] = None,
        trigger_config: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
        callable_name: Optional[str] = None,
        command: Optional[str] = None,
        status: Optional[str] = None,
        enabled_only: bool = False,
        **_,
    ) -> ToolResult:
        """Execute scheduling action."""
        try:
            scheduler = get_scheduler()

            if action == "create_job":
                if not name or not trigger_type:
                    return ToolResult(
                        output="",
                        error="create_job requires name and trigger_type"
                    )
                if not (callable_name or command):
                    return ToolResult(
                        output="",
                        error="create_job requires either callable_name or command"
                    )

                job_id = job_id or str(uuid.uuid4())[:8]
                trigger_config = trigger_config or {}

                job = await scheduler.create_job(
                    job_id=job_id,
                    name=name,
                    trigger_type=trigger_type,
                    trigger_config=trigger_config,
                    description=description,
                    callable_name=callable_name,
                    command=command,
                )

                return ToolResult(
                    output=f"Created job: {job.job_id} ({job.name}) with {trigger_type} trigger"
                )

            elif action == "list_jobs":
                jobs = scheduler.list_jobs(status=status, enabled_only=enabled_only)
                if not jobs:
                    return ToolResult(output="No jobs found")

                output = f"Found {len(jobs)} job(s):\n\n"
                for job in jobs[:10]:  # Limit to first 10
                    output += (
                        f"• {job.job_id}: {job.name}\n"
                        f"  Status: {job.status}, Enabled: {job.enabled}\n"
                        f"  Trigger: {job.trigger_type}\n"
                        f"  Runs: {job.run_count}, Errors: {job.error_count}\n"
                    )
                    if job.next_run:
                        output += f"  Next run: {job.next_run.isoformat()}\n"
                    output += "\n"

                if len(jobs) > 10:
                    output += f"... and {len(jobs) - 10} more jobs"

                return ToolResult(output=output)

            elif action == "get_job":
                if not job_id:
                    return ToolResult(output="", error="get_job requires job_id")

                job = scheduler.get_job(job_id)
                if not job:
                    return ToolResult(output="", error=f"Job not found: {job_id}")

                output = (
                    f"Job: {job.job_id}\n"
                    f"Name: {job.name}\n"
                    f"Status: {job.status}\n"
                    f"Trigger: {job.trigger_type}\n"
                    f"Config: {job.trigger_config}\n"
                    f"Runs: {job.run_count}\n"
                    f"Errors: {job.error_count}\n"
                )
                if job.last_run:
                    output += f"Last run: {job.last_run.isoformat()}\n"
                if job.last_error:
                    output += f"Last error: {job.last_error}\n"

                return ToolResult(output=output)

            elif action == "delete_job":
                if not job_id:
                    return ToolResult(output="", error="delete_job requires job_id")

                success = await scheduler.delete_job(job_id)
                if not success:
                    return ToolResult(output="", error=f"Job not found: {job_id}")

                return ToolResult(output=f"Deleted job: {job_id}")

            elif action == "pause_job":
                if not job_id:
                    return ToolResult(output="", error="pause_job requires job_id")

                success = await scheduler.pause_job(job_id)
                if not success:
                    return ToolResult(output="", error=f"Job not found: {job_id}")

                return ToolResult(output=f"Paused job: {job_id}")

            elif action == "resume_job":
                if not job_id:
                    return ToolResult(output="", error="resume_job requires job_id")

                success = await scheduler.resume_job(job_id)
                if not success:
                    return ToolResult(output="", error=f"Job not found: {job_id}")

                return ToolResult(output=f"Resumed job: {job_id}")

            elif action == "start_scheduler":
                await scheduler.start()
                return ToolResult(output="Scheduler started")

            elif action == "stop_scheduler":
                await scheduler.stop()
                return ToolResult(output="Scheduler stopped")

            elif action == "update_job":
                if not job_id:
                    return ToolResult(output="", error="update_job requires job_id")

                kwargs = {}
                if name:
                    kwargs['name'] = name
                if trigger_type:
                    kwargs['trigger_type'] = trigger_type
                if trigger_config:
                    kwargs['trigger_config'] = trigger_config
                if description:
                    kwargs['description'] = description

                job = await scheduler.update_job(job_id, **kwargs)
                return ToolResult(output=f"Updated job: {job.job_id}")

            else:
                return ToolResult(output="", error=f"Unknown action: {action}")

        except Exception as exc:
            return ToolResult(output="", error=str(exc))
