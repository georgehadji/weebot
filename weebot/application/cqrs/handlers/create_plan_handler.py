"""CreatePlanHandler — handles CreatePlan command.

Split from weebot/application/cqrs/handlers.py during architecture remediation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from weebot.application.cqrs.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from weebot.application.ports.event_bus_port import EventBusPort
    from weebot.application.ports.llm_port import LLMPort
    from weebot.application.ports.state_repo_port import StateRepositoryPort

from weebot.application.cqrs.commands import CreatePlanCommand

import logging

logger = logging.getLogger(__name__)


class CreatePlanHandler(CommandHandler):
    """Executes plan creation through PlannerAgent and returns events.

    Previously this was a pre-flight gate only.  Now it owns the full
    planning call so pipeline behaviours (LoggingBehavior, ValidationBehavior)
    activate on every plan creation.
    """

    def __init__(
        self, state_repo: StateRepositoryPort, llm: LLMPort, event_bus: EventBusPort | None = None
    ):
        self._state_repo = state_repo
        self._llm = llm
        self._event_bus = event_bus

    async def handle(self, command: CreatePlanCommand) -> CommandResult:
        from weebot.application.agents.planner import PlannerAgent
        from weebot.domain.models.event import PlanEvent

        try:
            session = await self._state_repo.load_session(command.session_id)
            if session is None:
                return CommandResult.fail(
                    error=f"Session {command.session_id} not found", error_code="SESSION_NOT_FOUND"
                )

            # Build skill context for the planner from session context
            skill_content = session.context.get("skill_content", "")
            skill_name = session.context.get("skill_name", "")

            planner_cfg = {}
            if command.model:
                planner_cfg["model"] = command.model
            if skill_content:
                planner_cfg["skill_prompt"] = skill_content

            # ── Seed planner from template cache ─────────────────
            # meta_notes is passed to PlannerAgent.create_plan(), not __init__().
            #
            # Gated: see PLAN_TEMPLATE_CACHE_ENABLED in config/feature_flags.py.
            # This is the half that changes the planner's inputs — with the
            # flag on, `build_meta_notes` output is appended to `meta_notes` on
            # every task. The guard is a plain `if` rather than a raise into the
            # handler below, so a feature that is switched off never reports
            # itself as a failure.
            meta_list = list(command.meta_notes or [])
            from weebot.config.feature_flags import is_enabled as _flag_enabled

            if _flag_enabled("PLAN_TEMPLATE_CACHE_ENABLED"):
                try:
                    from weebot.domain.services.plan_template_cache import (
                        build_meta_notes,
                        find_matching_templates,
                    )

                    templates = await find_matching_templates(self._state_repo, command.prompt)
                    template_notes = build_meta_notes(templates)
                    if template_notes:
                        meta_list.append(template_notes)
                        # Increment use_count for matched templates (best-effort)
                        for tpl in templates:
                            try:
                                await self._state_repo.increment_template_use(tpl.template_id)
                            except Exception:
                                logger.debug(
                                    "Failed to increment template use count", exc_info=True
                                )
                        logger.info(
                            "Seeding planner with %d template(s) for %s",
                            len(templates),
                            command.session_id[:8],
                        )
                except Exception as exc:
                    # WARNING, not DEBUG. Both calls in this block raised
                    # TypeError against the repository's real signatures, and at
                    # DEBUG that was indistinguishable from "no match". (D76.)
                    logger.warning("Template cache lookup failed: %s", exc, exc_info=True)

            planner = PlannerAgent(llm=self._llm, event_bus=self._event_bus, **planner_cfg)

            events: list[dict] = []
            final_plan = None
            async for event in planner.create_plan(command.prompt, meta_notes=meta_list or None):
                events.append(event.model_dump())
                session = session.add_event(event)
                if isinstance(event, PlanEvent) and event.plan is not None:
                    final_plan = event.plan

            # Persist the updated session so SavePolicyBehavior has
            # the latest state to save (handler adds events, behavior saves).
            await self._state_repo.save_session(session)

            return CommandResult.ok(
                data={
                    "session_id": command.session_id,
                    "events": events,
                    "plan": final_plan,
                    "model": command.model,
                    "status": "plan_created",
                }
            )
        except Exception as exc:
            return CommandResult.fail(error=str(exc), error_code="PLAN_CREATION_ERROR")
