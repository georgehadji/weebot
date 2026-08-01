"""Compare an actual tool-call sequence against a reference trajectory.

Pure functions over ``list[str]`` (tool names) — no I/O, no port. Used to
give path-fidelity signal (did the agent take the right route, not just
land on the right answer) that TrajectoryMonitor's runtime degeneracy
checks don't provide.
"""
from __future__ import annotations


def exact_match(actual: list[str], reference: list[str]) -> bool:
    """True if the sequences are identical, including length."""
    return actual == reference


def in_order_match(actual: list[str], reference: list[str]) -> bool:
    """True if every reference action appears in *actual*, in order.

    Extra actions in *actual* are allowed (subsequence match).
    """
    it = iter(actual)
    return all(step in it for step in reference)


def any_order_match(actual: list[str], reference: list[str]) -> bool:
    """True if every reference action appears somewhere in *actual*.

    Order and extras don't matter; duplicates in *reference* each still
    require a corresponding occurrence in *actual*.
    """
    remaining = list(actual)
    for step in reference:
        if step not in remaining:
            return False
        remaining.remove(step)
    return True


def precision(actual: list[str], reference: list[str]) -> float:
    """Fraction of *actual* actions that were in *reference* (relevance)."""
    if not actual:
        return 0.0
    pool = list(reference)
    hits = 0
    for step in actual:
        if step in pool:
            pool.remove(step)
            hits += 1
    return hits / len(actual)


def recall(actual: list[str], reference: list[str]) -> float:
    """Fraction of *reference* actions that appeared in *actual* (coverage)."""
    if not reference:
        return 1.0
    pool = list(actual)
    hits = 0
    for step in reference:
        if step in pool:
            pool.remove(step)
            hits += 1
    return hits / len(reference)


if __name__ == "__main__":
    assert exact_match(["a", "b"], ["a", "b"]) is True
    assert exact_match(["a", "b", "c"], ["a", "b"]) is False
    assert in_order_match(["a", "x", "b"], ["a", "b"]) is True
    assert in_order_match(["b", "a"], ["a", "b"]) is False
    assert any_order_match(["b", "x", "a"], ["a", "b"]) is True
    assert any_order_match(["a"], ["a", "b"]) is False
    assert precision(["a", "b", "x"], ["a", "b"]) == 2 / 3
    assert precision([], ["a"]) == 0.0
    assert recall(["a", "x"], ["a", "b"]) == 0.5
    assert recall(["a"], []) == 1.0
    # exact implies in_order implies any_order
    assert exact_match(["a", "b"], ["a", "b"]) <= in_order_match(["a", "b"], ["a", "b"])
    assert in_order_match(["a", "b"], ["a", "b"]) <= any_order_match(["a", "b"], ["a", "b"])
    print("trajectory_comparator: OK")
