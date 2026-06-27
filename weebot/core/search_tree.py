"""Search Tree — MCTS-style state exploration for LATS (Language Agent Tree Search).

Implements the core tree search logic for Enhancement 1 (Inference-Time Search).
The tree explores multiple execution paths, scoring each via LLM judge or
sandbox assertions, and backtracks when a path scores below threshold.

Structure:
    SearchNode — a single state in the tree
    LatsSearcher — MCTS loop controlling exploration vs exploitation
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class SearchNode:
    """A single node in the LATS search tree.

    Attributes:
        state: The current step description or intermediate result.
        parent: Parent node (None for root).
        children: Generated child nodes.
        visits: Number of times this node has been visited.
        value: Aggregate score (accumulated reward).
        depth: Depth from root.
        terminal: Whether this node represents a terminal state.
        tool_call: The tool + args that produced this node (for traceability).
    """
    state: str
    parent: Optional["SearchNode"] = None
    children: list["SearchNode"] = field(default_factory=list)
    visits: int = 0
    value: float = 0.0
    depth: int = 0
    terminal: bool = False
    tool_call: Optional[dict[str, Any]] = None

    def ucb1(self, exploration_constant: float = 1.41) -> float:
        """Upper Confidence Bound for Trees — balances explore vs exploit.

        Returns:
            UCB1 score.  Higher = more promising to explore.
        """
        if self.visits == 0:
            return float("inf")
        exploitation = self.value / self.visits
        if self.parent is None:
            return exploitation
        exploration = exploration_constant * math.sqrt(
            math.log(self.parent.visits + 1) / self.visits
        )
        return exploitation + exploration

    def best_child(self, exploration_constant: float = 1.41) -> Optional["SearchNode"]:
        """Select the child with the highest UCB1 score."""
        if not self.children:
            return None
        return max(self.children, key=lambda c: c.ucb1(exploration_constant))

    def add_child(self, state: str, **kwargs: Any) -> "SearchNode":
        child = SearchNode(
            state=state,
            parent=self,
            depth=self.depth + 1,
            **kwargs,
        )
        self.children.append(child)
        return child


class LatsSearcher:
    """MCTS-style tree search for action selection.

    The searcher runs *num_simulations* iterations of:
        1. SELECT — walk tree using UCB1
        2. EXPAND — generate candidate actions (via LLM or user-supplied fn)
        3. EVALUATE — score the new state
        4. BACKPROPAGATE — update scores up the tree

    After search completes, the best path is returned.
    """

    def __init__(
        self,
        evaluate_fn: Callable[[SearchNode], float],
        expand_fn: Callable[[SearchNode], list[str]],
        max_depth: int = 5,
        num_simulations: int = 10,
        exploration_constant: float = 1.41,
    ) -> None:
        self._evaluate_fn = evaluate_fn
        self._expand_fn = expand_fn
        self._max_depth = max_depth
        self._num_simulations = num_simulations
        self._exploration_constant = exploration_constant

    async def search(self, root_state: str) -> list[SearchNode]:
        """Run LATS from *root_state* and return the best path.

        Args:
            root_state: Initial task description or state.

        Returns:
            List of SearchNode from root to best terminal node (or deepest).
        """
        root = SearchNode(state=root_state)
        for i in range(self._num_simulations):
            node = root
            # SELECT
            while node.children and node.depth < self._max_depth:
                best = node.best_child(self._exploration_constant)
                if best is None:
                    break
                node = best
                if node.terminal:
                    break
            # EXPAND (if not terminal and not at max depth)
            if not node.terminal and node.depth < self._max_depth:
                candidates = self._expand_fn(node)
                for cs in candidates:
                    child = node.add_child(state=cs)
                    # EVALUATE
                    child.value = await asyncio.to_thread(self._evaluate_fn, child)
            # BACKPROPAGATE — climb tree, increment visits, propagate max child value
            while node is not None:
                node.visits += 1
                if node.children:
                    node.value = max(c.value for c in node.children)
                node = node.parent

        # Extract best path
        best_path = []
        node = root
        while node:
            best_path.append(node)
            if not node.children:
                break
            node = node.best_child(exploration_constant=0)  # pure exploitation
        return best_path
