"""SkillOptFlow — full optimization epoch loop (paper Figure 2).

Rollout → Reflect → Merge → Rank → Apply → Validate → Accept/Reject → Slow Update.

This flow orchestrates the entire SkillOpt training process.  It leverages
the CQRS mediator for all state mutations (commands flow through pipeline
behaviours including the ValidationGateBehavior) and the TaskRunner for
parallel rollout execution.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator, Callable, Optional

from weebot.application.flows.base_flow import BaseFlow
from weebot.application.flows.states.base import FlowState
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.optimizer_port import OptimizerPort
from weebot.application.services.lr_scheduler import LearningRateScheduler
from weebot.application.services.self_improver import SelfImprover
from weebot.domain.models.event import (
    AgentEvent,
    DoneEvent,
    EpochCompleted,
    SkillEditAccepted,
    SkillEditRejected,
)
from weebot.application.cqrs.commands.skill_edit_commands import ApplySkillEditsCommand
from weebot.domain.models.session import Session
from weebot.domain.models.skill import Skill
from weebot.domain.models.trajectory import OptimizationBatch
if TYPE_CHECKING:
    from weebot.application.ports.skill_store_port import SkillStorePort
    from weebot.application.ports.trajectory_repository_port import TrajectoryRepositoryPort
    from weebot.application.services.evolution_tracker import EvolutionTracker

logger = logging.getLogger(__name__)


class SkillOptFlow(BaseFlow):
    """Paper Figure 2 — optimization epoch loop for agent skills."""

    def __init__(
        self,
        skill_name: str,
        target_flow_factory: Callable,
        optimizer: OptimizerPort,
        skill_store: "SkillStorePort",
        trajectory_repo: "TrajectoryRepositoryPort",
        event_bus: EventBusPort | None,
        mediator,
        epochs: int = 4,
        steps_per_epoch: int = 5,
        batch_size: int = 40,
        minibatch_size: int = 8,
        validation_tasks: Optional[list[str]] = None,
        train_tasks: Optional[list[str]] = None,
        output_path: str = "best_skill.md",
        evolution_tracker: Optional["EvolutionTracker"] = None,
        use_planning: bool = False,
        self_improver: Optional[SelfImprover] = None,
        self_improve_contracts: bool = False,
        evaluator_slot: Optional[Any] = None,
        evaluator_selector: Optional[Any] = None,
        selective_erasure: Optional[Any] = None,
        adversarial_pool: Optional[Any] = None,
        use_archive_search: bool = False,
        thompson_sampler: Optional[Any] = None,
    ):
        self._skill_name = skill_name
        self._target_flow_factory = target_flow_factory
        self._optimizer = optimizer
        self._skill_store = skill_store
        self._trajectory_repo = trajectory_repo
        self._event_bus = event_bus
        self._mediator = mediator
        self._epochs = epochs
        self._steps_per_epoch = steps_per_epoch
        self._batch_size = batch_size
        self._minibatch_size = minibatch_size
        self._validation_tasks = validation_tasks or []
        self._train_tasks = train_tasks or []
        self._output_path = output_path
        self._evolution_tracker = evolution_tracker
        self._use_planning = use_planning
        self._self_improver = self_improver
        self._self_improve_contracts = self_improve_contracts
        self._evaluator_slot = evaluator_slot
        self._evaluator_selector = evaluator_selector
        self._selective_erasure = selective_erasure
        self._adversarial_pool = adversarial_pool
        self._use_archive_search = use_archive_search
        self._thompson_sampler = thompson_sampler

        self._scheduler = LearningRateScheduler(
            initial=8, floor=2, schedule="cosine"
        )
        self._done = False

    async def _ensure_archive_seeded(self, skill: Any, epoch: int) -> None:
        """Ensure the archive has a root node before archive search begins."""
        if self._thompson_sampler is not None and not self._thompson_sampler.archive.nodes:
            from weebot.domain.models.skill_archive import SkillArchiveNode
            root = SkillArchiveNode(
                node_id=f"root-e{epoch}",
                parent_id=None,
                skill_version=skill.current_version,
                created_at_epoch=epoch,
            )
            self._thompson_sampler.archive.add_node(root)
            logger.info("Archive: seeded root node from skill %s", skill.current_version)

    def is_done(self) -> bool:
        return self._done

    async def run(self, prompt: str = "") -> AsyncGenerator[AgentEvent, None]:
        """Execute the full epoch loop (paper Algorithm 1)."""
        skill = await self._skill_store.load(self._skill_name)
        if skill is None:
            raise ValueError(f"Skill '{self._skill_name}' not found in store")

        total_steps = self._epochs * self._steps_per_epoch
        step_counter = 0
        previous_skill = skill

        for epoch in range(self._epochs):
            logger.info("Starting epoch %d/%d for skill '%s'",
                        epoch + 1, self._epochs, self._skill_name)

            epoch_accepted = 0
            epoch_rejected = 0

            steps_iter = range(self._steps_per_epoch)

            # ── Archive-based search (Thompson sampling) ──────────
            if self._use_archive_search and self._thompson_sampler is not None:
                steps_iter = range(self._steps_per_epoch * 2)  # More steps for tree search
                await self._ensure_archive_seeded(skill, epoch)

            for step in steps_iter:
                budget = self._scheduler.budget_for_step(step_counter, total_steps)
                step_counter += 1

                # ── Archive-based step (Thompson sampling) ────────
                if self._use_archive_search and self._thompson_sampler is not None:
                    decision, parent_node, child_node = await self._thompson_sampler.step(
                        epoch, skill, self._train_tasks,
                    )

                    if decision == "expand" and child_node is not None:
                        # Propose edits from the parent skill
                        batch = await self._run_rollout(skill, epoch, step)
                        evolution_ctx = self._build_evolution_context(skill)

                        failure_edits = await self._optimizer.reflect_on_failures(
                            batch, skill,
                            evolution_context=evolution_ctx,
                        )
                        success_edits = await self._optimizer.reflect_on_successes(
                            batch, skill,
                            evolution_context=evolution_ctx,
                        )

                        if failure_edits or success_edits:
                            merged = await self._optimizer.merge_edits(
                                failure_edits, success_edits,
                            )
                            ranked = await self._optimizer.rank_edits(
                                merged, budget, skill,
                            )
                            if ranked:
                                # Apply the best edit to create a new skill variant
                                cmd = ApplySkillEditsCommand(
                                    skill_name=self._skill_name,
                                    edits=[e.to_dict() for e in ranked],
                                    source="archive_search",
                                )
                                result = await self._mediator.send(cmd)
                                if result.success:
                                    skill = result.skill
                                    epoch_accepted += 1
                                else:
                                    epoch_rejected += 1

                        # Continue to next step — archive handles evaluation separately
                        continue

                    elif decision == "evaluate":
                        # Evaluate the selected node's skill on a train task
                        if self._train_tasks:
                            import random
                            task = random.choice(self._train_tasks)
                            try:
                                session = Session(
                                    id=f"archive-eval-{uuid.uuid4().hex[:8]}",
                                    user_id="skillopt",
                                    agent_id="skillopt-agent",
                                )
                                flow = self._target_flow_factory(session)
                                async for _ in flow.run(task):
                                    pass
                                passed = True
                            except Exception:
                                passed = False

                            node_id = parent_node.node_id if parent_node else None
                            if node_id:
                                await self._thompson_sampler.record_evaluation(node_id, passed)
                                if passed:
                                    epoch_accepted += 1
                                else:
                                    epoch_rejected += 1
                        continue

                # ── Standard linear step (fallback) ──────────────
                # 1. ROLLOUT — collect trajectories
                batch = await self._run_rollout(skill, epoch, step)

                # Build longitudinal context from evolution history
                evolution_ctx = self._build_evolution_context(skill)

                # Optional SIA-inspired pre-reflect planning step
                if self._use_planning:
                    plan_json = await self._optimizer.plan_edits(batch, skill, evolution_ctx)
                    if plan_json:
                        evolution_ctx += f"\n\n## Improvement Plan\n```json\n{plan_json}\n```"

                # 2. REFLECT — analyse failures and successes
                failure_edits = await self._optimizer.reflect_on_failures(
                    batch, skill, evolution_context=evolution_ctx
                )
                success_edits = await self._optimizer.reflect_on_successes(
                    batch, skill, evolution_context=evolution_ctx
                )

                if not failure_edits and not success_edits:
                    logger.info("No edits proposed at step %d (epoch %d)", step, epoch)
                    continue

                # 3. MERGE — hierarchical merge with failure priority
                merged = await self._optimizer.merge_edits(failure_edits, success_edits)

                # 4. RANK + CLIP — rank by utility, clip to budget
                ranked = await self._optimizer.rank_edits(merged, budget, skill)

                if not ranked:
                    logger.info("No edits survived ranking at step %d", step)
                    continue

                # 5. APPLY + VALIDATE — through CQRS mediator
                result = await self._mediator.send(
                    ApplySkillEditsCommand(
                        skill_name=self._skill_name,
                        edits=[e.model_dump() for e in ranked],
                        budget=budget,
                        validation_task_ids=self._validation_tasks,
                    )
                )

                if result.success:
                    # Validation gate passed — accept the candidate
                    data = result.data or {}
                    candidate_skill = data.get("skill")
                    if candidate_skill:
                        skill = candidate_skill
                        skill = skill.accept_current(
                            validation_score=batch.batch_score
                        )
                        await self._skill_store.save(skill)
                        epoch_accepted += 1

                        yield SkillEditAccepted(
                            skill_name=self._skill_name,
                            old_version=skill.current_version - 1,
                            new_version=skill.current_version,
                            validation_score_delta=0.0,
                            edit=None,
                        )
                else:
                    # Validation gate rejected
                    epoch_rejected += 1
                    yield SkillEditRejected(
                        skill_name=self._skill_name,
                        skill_version=skill.current_version,
                        score_drop=0.0,
                        edit=None,
                        failure_analysis=result.error or "Validation gate rejected",
                    )

            # 6. EPOCH BOUNDARY — slow update + meta skill
            if epoch > 0:
                longitudinal = await self._collect_longitudinal(
                    previous_skill, skill
                )
                slow_guidance = await self._optimizer.slow_update(
                    previous_skill, skill, longitudinal
                )
                meta = await self._optimizer.meta_skill(
                    previous_skill, skill, longitudinal
                )

                if slow_guidance:
                    skill = skill.apply_slow_update(slow_guidance)
                if meta:
                    skill = skill.model_copy(update={"meta_skill": meta})
                await self._skill_store.save(skill)

            # ── Evaluator co-evolution at epoch boundaries ────────
            evaluator_replacement_data = None
            if self._evaluator_slot is not None and self._evaluator_selector is not None and epoch > 0:
                try:
                    # Score the current evaluator on the anchor dataset
                    scored_current = await self._evaluator_selector.score_evaluator(
                        self._evaluator_slot,
                    )

                    # Build adversarial context if there's a pool from prior replacements
                    eval_evolution_ctx = ""
                    if self._adversarial_pool is not None:
                        adv_obj = self._adversarial_pool.build_adversarial_objective(epoch)
                        if adv_obj:
                            eval_evolution_ctx = f"\n\n{adv_obj}"
                            logger.info(
                                "Adversarial regularisation: %d artifacts in pool for epoch %d",
                                len(self._adversarial_pool.get_artifacts_for_epoch(epoch)), epoch,
                            )

                    # Propose evaluator edits from trajectories
                    batch = await self._run_rollout(skill, epoch, 0)
                    evaluator_edits = await self._optimizer.reflect_on_evaluator(
                        batch, scored_current,
                        evolution_context=eval_evolution_ctx,
                    )

                    if evaluator_edits and self._selective_erasure is not None:
                        # Create a challenger with updated prompt
                        new_prompt = evaluator_edits[-1].content  # Use best edit
                        challenger = scored_current.model_copy(update={
                            "prompt": new_prompt,
                            "anchor_accuracy": 0.0,  # Force re-scoring
                            "anchor_total": 0,
                            "evaluator_id": f"{scored_current.evaluator_id}_challenger",
                        })

                        # Compare incumbent vs challenger
                        promoted, result_evaluator, reason = (
                            await self._evaluator_selector.compare_and_replace(
                                incumbent=scored_current,
                                challenger=challenger,
                                epoch=epoch,
                            )
                        )

                        if promoted:
                            self._evaluator_slot = result_evaluator
                            if self._selective_erasure is not None:
                                self._selective_erasure.on_evaluator_replaced(
                                    old_evaluator_id=scored_current.evaluator_id,
                                    new_evaluator_id=result_evaluator.evaluator_id,
                                    epoch=epoch,
                                )
                            evaluator_replacement_data = {
                                "old_id": scored_current.evaluator_id,
                                "new_id": result_evaluator.evaluator_id,
                                "old_acc": scored_current.anchor_accuracy,
                                "new_acc": result_evaluator.anchor_accuracy,
                            }

                            # Populate adversarial pool from old evaluator's mis-scored artifacts
                            if self._adversarial_pool is not None and hasattr(
                                self._evaluator_selector, "_anchor_tasks",
                            ):
                                artifacts = [
                                    {
                                        "task_id": task.get("prompt", "")[:80],
                                        "description": task.get("prompt", "")[:120],
                                        "evaluator_score": scored_current.anchor_accuracy,
                                        "ground_truth": task.get("ground_truth_score", 0.5),
                                    }
                                    for task in getattr(
                                        self._evaluator_selector, "_anchor_tasks", []
                                    )
                                ]
                                self._adversarial_pool.on_evaluator_replaced(
                                    old_evaluator_id=scored_current.evaluator_id,
                                    new_evaluator_id=result_evaluator.evaluator_id,
                                    epoch=epoch,
                                    artifacts=artifacts,
                                )

                            logger.info(
                                "Evaluator co-evolution: %s at epoch %d", reason, epoch,
                            )
                except Exception as exc:
                    logger.warning("Evaluator co-evolution failed at epoch %d: %s", epoch, exc)

            best_score = skill.best.validation_score or 0.0
            epoch_event = EpochCompleted(
                skill_name=self._skill_name,
                epoch=epoch,
                best_validation_score=best_score,
                edits_accepted=epoch_accepted,
                edits_rejected=epoch_rejected,
                slow_update_applied=epoch > 0,
            )

            # Record evolution narrative (SIA-inspired longitudinal memory)
            if self._evolution_tracker is not None:
                try:
                    skill = await self._evolution_tracker.record_epoch(
                        skill, previous_skill, epoch_event,
                        evaluator_replacement=evaluator_replacement_data,
                    )
                    await self._skill_store.save(skill)
                except Exception as exc:
                    logger.warning("EvolutionTracker.record_epoch failed: %s — continuing", exc)

            # ── Capability 6: Self-Improvement — propose contract/rule edits ──
            if self._self_improver is not None and self._self_improve_contracts:
                try:
                    await self._run_self_improvement(skill, epoch, epoch_accepted, epoch_rejected)
                except Exception as sic_exc:
                    logger.warning("Self-improvement step failed: %s", sic_exc)
            # ─────────────────────────────────────────────────────────────────

            previous_skill = skill
            yield epoch_event

        # Export best skill
        await self._skill_store.export_best_md(self._skill_name, self._output_path)
        logger.info("Exported best skill '%s' to %s", self._skill_name, self._output_path)
        self._done = True
        yield DoneEvent()

    @staticmethod
    def _build_evolution_context(skill: Skill) -> str:
        """Format the last 5 evolution log entries as a markdown context block."""
        if not skill.evolution_log:
            return ""
        lines = ["## Evolution History (recent epochs)"]
        for entry in skill.evolution_log[-5:]:
            delta_sign = "+" if entry.score_delta >= 0 else ""
            lines.append(
                f"- Epoch {entry.epoch} "
                f"(score {entry.best_score:.3f}, Δ{delta_sign}{entry.score_delta:.3f}, "
                f"accepted {entry.accepted_count}, rejected {entry.rejected_count}): "
                f"{entry.narrative}"
            )
        return "\n".join(lines)

    async def _run_rollout(
        self,
        skill: Skill,
        epoch: int,
        step: int,
    ) -> OptimizationBatch:
        """Run target model on training tasks, accumulate trajectories."""
        trajectories = []

        for i, task_id in enumerate(self._train_tasks):
            if i >= self._batch_size:
                break
            # Create a session with the current skill
            session = Session(
                id=f"opt-{epoch}-{step}-{i}",
                user_id="skillopt",
                agent_id="target-model",
                context={
                    "skill_name": self._skill_name,
                    "skill_version": skill.current_version,
                    "skill_content": skill.content,
                    "last_prompt": task_id,
                },
            )
            flow = self._target_flow_factory(session)
            try:
                async for _ in flow.run(task_id):
                    pass
            except Exception as exc:
                logger.warning("Rollout task '%s' failed: %s", task_id, exc)

            # Retrieve trajectory from repo
            stored = await self._trajectory_repo.get_by_session(session.id)
            if stored:
                trajectories.extend(stored)

        if not trajectories:
            return OptimizationBatch(
                skill_name=self._skill_name,
                skill_version=skill.current_version,
            )

        batch = OptimizationBatch(
            skill_name=self._skill_name,
            skill_version=skill.current_version,
            trajectories=trajectories,
            batch_score=sum(t.score for t in trajectories) / len(trajectories),
            failure_count=sum(1 for t in trajectories if not t.passed),
            success_count=sum(1 for t in trajectories if t.passed),
        )
        return batch

    async def _collect_longitudinal(
        self,
        prev_skill: Skill,
        curr_skill: Skill,
        n_samples: int = 20,
    ) -> list[tuple]:
        """Collect longitudinal comparison data for slow/meta update.

        Samples up to *n_samples* tasks under both the previous and current
        skill, producing pairs of TrajectorySummary objects for comparison.
        """
        import random

        tasks = list(self._train_tasks)
        sampled = random.sample(tasks, min(n_samples, len(tasks)))
        comparisons = []

        for task_id in sampled:
            prev_traj = await self._trajectory_repo.get_by_session(
                f"opt-*-*-{task_id}"
            )
            curr = await self._trajectory_repo.get_by_skill(
                self._skill_name, curr_skill.current_version, limit=1
            )
            if prev_traj and curr:
                comparisons.append((prev_traj[0], curr[0]))

        return comparisons

    async def _run_self_improvement(
        self,
        skill: Skill,
        epoch: int,
        epoch_accepted: int,
        epoch_rejected: int,
    ) -> None:
        """Propose and apply patches to contract/rule files based on epoch results.

        Called after each epoch boundary if self-improver is configured.
        Targets:
          - Contract YAML files (weebot/config/contracts/)
          - Rule files (weebot/config/prompts/rules/)

        Args:
            skill: The current Skill after epoch edits.
            epoch: Current epoch number.
            epoch_accepted: Number of accepted edits this epoch.
            epoch_rejected: Number of rejected edits this epoch.
        """
        if self._self_improver is None:
            return

        # Only propose patches when there's meaningful feedback
        if epoch_accepted == 0 and epoch_rejected == 0:
            return

        # Determine which files to propose patches for
        _contract_base = Path(__file__).resolve().parent.parent.parent / "config" / "contracts"
        _rules_base = Path(__file__).resolve().parent.parent.parent / "config" / "prompts" / "rules"

        # Check contract files
        for contract_file in sorted(_contract_base.glob("*.yaml")):
            rel_path = contract_file.relative_to(
                Path(__file__).resolve().parent.parent.parent
            ).as_posix()
            current = contract_file.read_text(encoding="utf-8")
            context = {
                "target_file": rel_path,
                "target_type": "contract",
                "current_content": current,
                "new_content": current,  # No change unless optimizer proposes one
                "validation_tasks": self._validation_tasks,
            }
            patch = await self._self_improver.propose_patch(context)
            if patch is not None:
                score = await self._self_improver.validate_patch(patch)
                if score >= 0.5:
                    applied = await self._self_improver.apply_patch(patch)
                    if applied:
                        logger.info(
                            "Self-improvement: applied patch to %s (score: %.2f)",
                            rel_path, score,
                        )

        # Check rule files
        for rule_file in sorted(_rules_base.glob("*.md")):
            rel_path = rule_file.relative_to(
                Path(__file__).resolve().parent.parent.parent
            ).as_posix()
            current = rule_file.read_text(encoding="utf-8")
            context = {
                "target_file": rel_path,
                "target_type": "rule",
                "current_content": current,
                "new_content": current,
                "validation_tasks": self._validation_tasks,
            }
            patch = await self._self_improver.propose_patch(context)
            if patch is not None:
                score = await self._self_improver.validate_patch(patch)
                if score >= 0.5:
                    applied = await self._self_improver.apply_patch(patch)
                    if applied:
                        logger.info(
                            "Self-improvement: applied patch to %s (score: %.2f)",
                            rel_path, score,
                        )
