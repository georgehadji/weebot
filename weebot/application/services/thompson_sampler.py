"""ThompsonSampler — orchestrates archive-based search for SkillOptFlow (RQGM §3.3).

At each step, the sampler decides whether to EXPAND (create a new skill
variant via the optimizer) or EVALUATE (score an existing node on a task).

The decision uses a UCB-Air gate: expand if ``evaluations^alpha >= archive_size``.
When expanding, the node to branch from is selected by Thompson sampling
over the Beta posterior of each node's clade metaproductivity (CMP).

When evaluating, the node is selected by Thompson sampling over individual
success rates (not CMP — evaluation costs are per-node, not per-clade).

Usage::

    sampler = ThompsonSampler(
        optimizer=optimizer,
        skill_store=skill_store,
        trajectory_repo=trajectory_repo,
        archive=archive,
    )
    decision = await sampler.step(epoch, skill)
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from weebot.domain.models.skill_archive import SkillArchive, SkillArchiveNode

logger = logging.getLogger(__name__)


class ThompsonSampler:
    """Orchestrates archive-based search for SkillOptFlow.

    Maintains the archive tree and decides at each step whether to
    expand (create a new variant) or evaluate (score an existing one).
    """

    def __init__(
        self,
        optimizer: Any,
        skill_store: Any,
        trajectory_repo: Any,
        archive: Optional[SkillArchive] = None,
        growth_alpha: float = 0.3,
    ):
        self._optimizer = optimizer
        self._skill_store = skill_store
        self._trajectory_repo = trajectory_repo
        self._archive = archive or SkillArchive()
        self._growth_alpha = growth_alpha
        self._step_count = 0

    @property
    def archive(self) -> SkillArchive:
        return self._archive

    @property
    def step_count(self) -> int:
        return self._step_count

    async def step(
        self,
        epoch: int,
        current_skill: Any,
        train_tasks: list[str],
    ) -> tuple[str, Optional[SkillArchiveNode], Optional[SkillArchiveNode]]:
        """Execute one search step.

        Returns:
            ``(decision, parent_node, child_node)`` where:
            - *decision* is ``"expand"`` or ``"evaluate"``
            - *parent_node* is the node selected for expansion/evaluation
            - *child_node* is the new node (only for ``"expand"``)
        """
        self._step_count += 1

        # UCB-Air gate
        if SkillArchiveNode.should_expand(
            evaluations_done=self._archive.total_evaluations,
            archive_size=len(self._archive.nodes),
            alpha=self._growth_alpha,
        ):
            return await self._expand(epoch, current_skill)
        else:
            return await self._evaluate(epoch, train_tasks)

    async def _expand(
        self,
        epoch: int,
        current_skill: Any,
    ) -> tuple[str, SkillArchiveNode, Optional[SkillArchiveNode]]:
        """Select a parent node via Thompson sampling, then create a child.

        The optimizer proposes edits to the parent's skill to create
        a new variant (child).
        """
        if not self._archive.nodes:
            # Root node — first expansion
            node = SkillArchiveNode(
                node_id=f"root-{epoch}",
                parent_id=None,
                skill_version="v0",
                created_at_epoch=epoch,
            )
            self._archive.add_node(node)
            logger.info("Archive: created root node %s", node.node_id)
            return ("expand", node, node)

        # Select parent via Thompson sampling
        parent = self._archive.select_node()
        logger.debug("Archive: selected parent %s for expansion", parent.node_id)

        # The optimizer proposes edits based on the parent's skill
        # In the integrated flow, this calls optimizer.reflect_on_failures etc.
        # Here we create a placeholder child — the flow populates it.
        child_id = f"n{len(self._archive.nodes)}-e{epoch}"
        child = SkillArchiveNode(
            node_id=child_id,
            parent_id=parent.node_id,
            skill_version=f"v{len(self._archive.nodes)}",
            created_at_epoch=epoch,
            meta={"parent_successes": parent.successes, "parent_failures": parent.failures},
        )
        self._archive.add_node(child)
        logger.info("Archive: expanded %s → %s (size=%d)",
                    parent.node_id, child_id, len(self._archive.nodes))
        return ("expand", parent, child)

    async def _evaluate(
        self,
        epoch: int,
        train_tasks: list[str],
    ) -> tuple[str, SkillArchiveNode, None]:
        """Select a node via Thompson sampling and return it for evaluation.

        The actual evaluation (running the node's skill on train tasks)
        is done by the caller (SkillOptFlow).
        """
        if not self._archive.nodes:
            logger.warning("Archive: empty archive, cannot evaluate")
            return ("evaluate", self._archive.nodes.get(list(self._archive.nodes.keys())[0]), None)

        node = self._archive.select_node()
        logger.debug("Archive: selected %s for evaluation (S=%d, F=%d)",
                     node.node_id, node.successes, node.failures)
        return ("evaluate", node, None)

    async def record_evaluation(self, node_id: str, passed: bool) -> None:
        """Record a evaluation outcome for a node."""
        self._archive.record_evaluation(node_id, passed)
        logger.debug("Archive: recorded %s for %s (total evals=%d)",
                     "PASS" if passed else "FAIL", node_id,
                     self._archive.total_evaluations)

    def stats(self) -> dict[str, Any]:
        """Return archive statistics."""
        return {
            "archive_size": len(self._archive.nodes),
            "total_evaluations": self._archive.total_evaluations,
            "step_count": self._step_count,
            "leaf_count": len(self._archive.get_leaves()),
            "root_id": self._archive.root_id,
        }
