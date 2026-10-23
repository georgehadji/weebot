"""The planner's heuristic-split count reaches the flow (F70).

It was a private attribute set on the Plan; the planner yields
`plan.model_dump()` and PlanningState rebuilds with `model_validate`, which
reset it to 0, so the misalignment signal in PlanActFlow never fired.
"""

from __future__ import annotations

from weebot.domain.models.plan import Plan


def test_heuristic_splits_survive_a_dump_and_validate():
    plan = Plan(goal="g", heuristic_splits=2)
    assert Plan.model_validate(plan.model_dump(mode="json")).heuristic_splits == 2
