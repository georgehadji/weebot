"""The reviewer routes to the value-for-money winner of the billed eval.

On the 2026-10-23 hard-task eval (tasks/remaining_fix_plan.md, "Per-role VFM,
hard tasks, billed") Haiku 5.5 and GPT-6.1 Sol both went 6/6 on subtle-bug
review, Haiku at about a twelfth of the cost. Sol stays as fallback 1.
"""

from weebot.config import model_refs


def test_reviewer_runs_haiku_first_with_sol_behind_it():
    chain = model_refs.ROLE_MODEL_CONFIG["reviewer"]
    assert chain[0] == "anthropic/claude-haiku-5.5"
    assert chain[1] == model_refs.MODEL_CASCADE_TIER4
