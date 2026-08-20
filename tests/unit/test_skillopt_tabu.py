"""Tabu memory over rejected skill edits.

Before this, the validation gate rejected an edit and nothing recorded the
rejection — the optimizer was structurally free to re-propose the identical
edit on every subsequent step of the run.
"""

from __future__ import annotations

from weebot.application.flows.skill_opt_flow import SkillOptFlow
from weebot.domain.models.skill_edit import SkillEdit


def _flow() -> SkillOptFlow:
    return SkillOptFlow(
        skill_name="demo",
        target_flow_factory=lambda session: None,
        optimizer=None,
        skill_store=None,
        trajectory_repo=None,
        event_bus=None,
        mediator=None,
    )


def test_rejected_edit_is_dropped_on_the_next_proposal() -> None:
    flow = _flow()
    edit = SkillEdit(op="append", content="always retry on 429")

    assert flow._drop_tabu([edit]) == [edit]
    flow._mark_tabu([edit])
    assert flow._drop_tabu([edit]) == []


def test_tabu_is_content_keyed_so_the_reverse_edit_stays_legal() -> None:
    """A target-level tabu would freeze the whole section — the paper's bug."""
    flow = _flow()
    flow._mark_tabu([SkillEdit(op="replace", target="## Retries", content="never retry")])

    reverse = SkillEdit(op="replace", target="## Retries", content="always retry")

    assert flow._drop_tabu([reverse]) == [reverse]
