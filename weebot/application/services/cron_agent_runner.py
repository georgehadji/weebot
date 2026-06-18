"""Cron Agent Runner — spawns PlanActFlow sessions for cron jobs.

Each cron job tick creates a fresh PlanActFlow with the configured
prompt, attached skills, and toolset.  Results are captured and
forwarded to the delivery service.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from weebot.domain.models.cron_job import CronJobRecord, DeliveryTarget
from weebot.domain.models.session import Session as WeebotSession

logger = logging.getLogger(__name__)


class CronAgentRunner:
    """Runs a single cron agent task by spawning a PlanActFlow.

    The runner creates a temporary session, runs the flow with the
    configured prompt, and returns the result for delivery.
    """

    def __init__(
        self,
        llm: Any | None = None,
        state_repo: Any | None = None,
        tool_registry: Any | None = None,
    ) -> None:
        self._llm = llm
        self._state_repo = state_repo
        self._tool_registry = tool_registry

    async def run(self, job: CronJobRecord) -> str:
        import os
        # Set recursion guard before spawning the flow
        # Set recursion guard — prevents infinite scheduling loops
        os.environ["WEEBOT_CRON_CONTEXT"] = "1"
        _log.debug("Cron context guard set")
        """Execute a cron job and return the result text.

        Args:
            job: The cron job to execute.

        Returns:
            The flow's final response text.
        """
        import uuid

        session_id = f"cron-{job.id}-{uuid.uuid4().hex[:8]}"
        session = WeebotSession(
            id=session_id,
            user_id="cron-agent",
            agent_id="cron-agent",
        )

        # Build tools from configured toolset
        tools = None
        if self._tool_registry and job.attached_toolsets:
            for toolset in job.attached_toolsets:
                try:
                    tools = self._tool_registry.create_tool_collection(toolset)
                    if tools:
                        break
                except ValueError:
                    continue

        if tools is None and self._tool_registry:
            try:
                tools = self._tool_registry.create_tool_collection("automation")
            except ValueError:
                pass

        # Create and run the flow
        from weebot.interfaces.factories import create_flow

        flow = create_flow(
            flow_type="plan_act",
            session=session,
            llm=self._llm,
            tools=tools,
            state_repo=self._state_repo,
            profile_name=None,
        )

        # Build the prompt with skill injections
        prompt_parts = [job.prompt]
        if job.attached_skills:
            skill_context = "\n".join(
                f"- {skill}" for skill in job.attached_skills
            )
            prompt_parts.insert(0, f"Attached skills:\n{skill_context}\n")

        full_prompt = "\n".join(prompt_parts)

        # Run with timeout
        response = ""
        try:
            async for event in asyncio.wait_for(
                flow.run(full_prompt),
                timeout=job.max_runtime_seconds,
            ):
                if getattr(event, "type", "") == "message":
                    response = getattr(event, "message", "") or response
        except asyncio.TimeoutError:
            response = "⚠️ Cron job timed out after {} seconds.".format(job.max_runtime_seconds)
            logger.warning("Cron job %s timed out", job.id)
        except Exception as exc:
            response = f"⚠️ Cron job failed: {exc}"
            logger.error("Cron job %s failed: %s", job.id, exc)

        return response or "(no output)"
