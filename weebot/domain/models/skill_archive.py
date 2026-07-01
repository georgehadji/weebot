"""SkillArchiveNode — a node in the self-improvement archive tree (RQGM §3.3).

Represents one skill/evaluator variant in the archive.  Each node tracks
its own evaluation outcomes and aggregates them into a clade metaproductivity
(CMP) score — the success rate pooled over its entire descendant subtree.

Node selection uses Thompson sampling over Beta(1 + successes, 1 + failures)
for each node, balancing exploration (uncertain nodes can be sampled) against
exploitation (high-success nodes are sampled more often).

Archive growth is controlled by a UCB-Air gate: expand (create a child) if
``evaluations_done^alpha >= archive_size``, otherwise evaluate an existing node.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class SkillArchiveNode(BaseModel):
    """A node in the self-improvement archive tree.

    Each node corresponds to one skill/evaluator variant.  The tree grows
    via expansion (optimizer creates a child variant) and evaluation
    (node scored on tasks).
    """

    node_id: str = Field(description="Unique node identifier")
    parent_id: Optional[str] = Field(default=None, description="Parent node ID, None for root")
    skill_version: str = Field(default="", description="The skill document version at this node")
    successes: int = Field(default=0, ge=0, description="Successful evaluations")
    failures: int = Field(default=0, ge=0, description="Failed evaluations")
    children: list[str] = Field(default_factory=list, description="Child node IDs")
    created_at_epoch: int = Field(default=0, description="Epoch when this node was created")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    meta: dict = Field(default_factory=dict, description="Arbitrary metadata (evaluator_id, etc.)")

    @property
    def total_evaluations(self) -> int:
        return self.successes + self.failures

    @property
    def success_rate(self) -> float:
        if self.total_evaluations == 0:
            return 0.0
        return self.successes / self.total_evaluations

    def record_evaluation(self, passed: bool) -> None:
        """Record one evaluation outcome."""
        if passed:
            self.successes += 1
        else:
            self.failures += 1

    @classmethod
    def thompson_sample(cls, nodes: list["SkillArchiveNode"]) -> "SkillArchiveNode":
        """Select a node using Thompson sampling over Beta posterior.

        For each node, sample from ``Beta(1 + successes, 1 + failures)``
        and pick the node with the highest sample.  Nodes with few
        evaluations have broad posteriors and may be sampled instead of
        nodes with high success rates (exploration).
        """
        best_node = nodes[0]
        best_sample = -1.0

        for node in nodes:
            # Sample from Beta(1 + S, 1 + F)
            alpha = 1 + node.successes
            beta_param = 1 + node.failures
            sample = random.betavariate(alpha, beta_param)
            if sample > best_sample:
                best_sample = sample
                best_node = node

        return best_node

    @classmethod
    def should_expand(
        cls,
        evaluations_done: int,
        archive_size: int,
        alpha: float = 0.3,
    ) -> bool:
        """UCB-Air gate: should we expand (create a child) or evaluate?

        Expands if ``evaluations_done^alpha >= archive_size``, meaning
        the archive should grow sub-linearly with evaluations (O(N^alpha)).

        Args:
            evaluations_done: Total evaluations performed so far.
            archive_size: Current number of nodes in the archive.
            alpha: Growth exponent (default 0.3).  Lower = slower growth.

        Returns:
            True to expand (create a child), False to evaluate an existing node.
        """
        if evaluations_done <= 0:
            return True  # Always expand the first node
        return evaluations_done ** alpha >= archive_size


class SkillArchive(BaseModel):
    """The full archive tree — collection of SkillArchiveNodes.

    Provides tree-level operations: add child, compute CMP, select node.
    """

    nodes: dict[str, SkillArchiveNode] = Field(
        default_factory=dict,
        description="All nodes keyed by node_id",
    )
    root_id: Optional[str] = Field(default=None, description="Root node ID")
    total_evaluations: int = Field(default=0, ge=0, description="Cumulative evaluations")

    def add_node(self, node: SkillArchiveNode) -> None:
        """Add a node to the archive and link it to its parent."""
        self.nodes[node.node_id] = node
        if node.parent_id and node.parent_id in self.nodes:
            parent = self.nodes[node.parent_id]
            if node.node_id not in parent.children:
                parent.children.append(node.node_id)
        if self.root_id is None:
            self.root_id = node.node_id

    def get_node(self, node_id: str) -> Optional[SkillArchiveNode]:
        return self.nodes.get(node_id)

    def get_leaves(self) -> list[SkillArchiveNode]:
        """Return all nodes with no children (leaf nodes)."""
        return [n for n in self.nodes.values() if not n.children]

    def get_viable_nodes(self) -> list[SkillArchiveNode]:
        """Return all nodes that can be selected for evaluation.

        Excludes nodes that have reached their evaluation budget.
        Currently returns all nodes — extendable for budget caps.
        """
        return list(self.nodes.values())

    def compute_cmp(self, node_id: str) -> float:
        """Clade Metaproductivity — success rate pooled over a node's clade.

        The clade is the subtree rooted at *node_id*.  CMP is the total
        successes divided by total evaluations across all nodes in the clade.

        This is the RQGM search utility: selecting by CMP prefers nodes
        whose descendants have been productive, even if the node itself
        hasn't been evaluated much.
        """
        total_s, total_f = self._accumulate_clade(node_id)
        total = total_s + total_f
        if total == 0:
            return 0.0
        return total_s / total

    def _accumulate_clade(self, node_id: str) -> tuple[int, int]:
        """Recursively accumulate successes and failures in a clade."""
        node = self.nodes.get(node_id)
        if node is None:
            return (0, 0)
        total_s = node.successes
        total_f = node.failures
        for child_id in node.children:
            cs, cf = self._accumulate_clade(child_id)
            total_s += cs
            total_f += cf
        return total_s, total_f

    def select_node(self) -> SkillArchiveNode:
        """Select a node for expansion or evaluation using Thompson sampling.

        Filters to viable nodes, then uses Thompson sampling over CMP
        (actually over the individual Beta distributions, which naturally
        weights by CMP + uncertainty).
        """
        viable = self.get_viable_nodes()
        if not viable:
            raise ValueError("No viable nodes in archive")
        return SkillArchiveNode.thompson_sample(viable)

    def record_evaluation(self, node_id: str, passed: bool) -> None:
        """Record an evaluation outcome for a node and update totals."""
        node = self.nodes.get(node_id)
        if node:
            node.record_evaluation(passed)
            self.total_evaluations += 1
