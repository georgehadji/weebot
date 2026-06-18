"""Cross-Model Transfer handler — evaluate skill transfer performance.

The ValidateTransferHandler runs validation tasks on a target (model, harness)
pair with and without the skill to measure transfer Δ.  The flow_factory is
injected by DI — this handler MUST NOT import from interfaces/.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, TYPE_CHECKING

from weebot.application.cqrs.base import CommandHandler, CommandResult
from weebot.application.cqrs.commands.transfer_commands import ValidateTransferCommand

if TYPE_CHECKING:
    from weebot.application.ports.skill_store_port import SkillStorePort
    from weebot.application.ports.state_repo_port import StateRepositoryPort
    from weebot.domain.models.session import Session
    from weebot.domain.models.skill import Skill

logger = logging.getLogger(__name__)


class ValidateTransferHandler(CommandHandler):
    """Evaluate skill transfer to a different model/harness pair.

    flow_factory is injected by DI — it must NOT import from interfaces/.
    The factory signature is: Callable[[Session, str | None], BaseFlow]
    """

    def __init__(
        self,
        state_repo: StateRepositoryPort,
        skill_store: SkillStorePort,
        flow_factory: Callable,              # injected, not imported
    ):
        self._state_repo = state_repo
        self._skill_store = skill_store
        self._create_flow = flow_factory

    async def handle(self, command: ValidateTransferCommand) -> CommandResult:
        from weebot.domain.models.session import Session
        from weebot.domain.models.trajectory import TrajectorySummary

        try:
            skill = await self._skill_store.load(command.skill_name)
            if skill is None:
                return CommandResult.fail(
                    error=f"Skill '{command.skill_name}' not found",
                    error_code="SKILL_NOT_FOUND",
                )

            t0 = time.monotonic()

            # Phase 1: baseline (no-skill) — runs in parallel
            async def run_baseline(task: str) -> float:
                session = Session(id=f"transfer-base-{task}", user_id="skillopt", agent_id="transfer-runner")
                flow = self._create_flow(session=session, model=command.target_model, harness=command.target_harness, skill_content=None)
                return await self._run_and_score(session, flow, task)

            baseline_scores = await asyncio.gather(*[run_baseline(t) for t in command.validation_tasks])

            # Phase 2: with skill — runs in parallel
            skill_content = skill.export_best()
            async def run_transfer(task: str) -> float:
                session = Session(id=f"transfer-skill-{task}", user_id="skillopt", agent_id="transfer-runner", context={"skill_content": skill_content, "skill_name": command.skill_name})
                flow = self._create_flow(session=session, model=command.target_model, harness=command.target_harness, skill_content=skill_content)
                return await self._run_and_score(session, flow, task)

            transfer_scores = await asyncio.gather(*[run_transfer(t) for t in command.validation_tasks])

            elapsed_s = time.monotonic() - t0
            avg_baseline = sum(baseline_scores) / len(baseline_scores) if baseline_scores else 0.0
            avg_transfer = sum(transfer_scores) / len(transfer_scores) if transfer_scores else 0.0
            delta = avg_transfer - avg_baseline

            # Store result in the skill model
            from weebot.domain.models.skill import TransferResult
            key = f"{command.target_model}:{command.target_harness}"
            result = TransferResult(
                target_model=command.target_model,
                target_harness=command.target_harness,
                baseline_score=avg_baseline,
                transfer_score=avg_transfer,
                delta=delta,
                n_tasks=len(command.validation_tasks),
                latency_s=elapsed_s,
            )

            skill = skill.model_copy(update={
                "transfer_scores": {
                    **skill.transfer_scores,
                    key: result.model_dump(),
                }
            })
            await self._skill_store.save(skill)

            return CommandResult.ok(data={
                "skill_name": command.skill_name,
                "target": f"{command.target_model}@{command.target_harness}",
                "baseline": avg_baseline,
                "transfer": avg_transfer,
                "delta": delta,
                "latency_s": elapsed_s,
                "n_tasks": len(command.validation_tasks),
            })

        except Exception as exc:
            logger.error("Transfer evaluation failed: %s", exc)
            return CommandResult.fail(
                error=str(exc), error_code="TRANSFER_ERROR"
            )

    async def _run_and_score(self, session: Session, flow, task: str) -> float:
        """Run a flow on a single validation task and return a score (0.0–1.0).

        The scoring is a placeholder that returns a score based on whether
        the flow completed without errors.  Real scoring requires a
        ScoringPort implementation per harness.
        """
        try:
            async for event in flow.run(task):
                pass  # accumulate events, final scoring at end

            # Heuristic score: 1.0 if no errors, 0.0 if errors
            from weebot.domain.models.event import ErrorEvent
            error_count = sum(1 for e in session.events if isinstance(e, ErrorEvent))
            if error_count > 0:
                return 0.0
            return 0.5  # placeholder — real score via ScoringPort
        except Exception:
            logger.warning("Transfer validation task '%s' raised an exception", task, exc_info=True)
            return 0.0
