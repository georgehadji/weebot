"""A step that restates a prohibition is not a violation of it.

Found on the 2026-10-23 smoke run: the user wrote "Do not create or modify any
files", the planner carried it into the step ("... output only the number.
Do not create or modify any files."), and the constraint gate paused the run
because the step's tokens matched the prohibited phrase. Negated clauses in
the step now drop out before the token vote; a real violation still fires.
"""

from __future__ import annotations

from weebot.application.services.constraint_extractor import ConstraintExtractor


def _check(step: str, user_text: str):
    ex = ConstraintExtractor()
    return ex.check_step(step, ex.extract(user_text))


USER = "Compute 17 times 23. Do not create or modify any files."


def test_restating_the_prohibition_is_not_a_violation():
    step = "Compute 17 * 23 in PowerShell and output the number. Do not create or modify any files."
    assert _check(step, USER) == []


def test_doing_the_prohibited_thing_still_fires():
    step = "Create a file result.txt and modify the files in the workspace."
    assert _check(step, USER)


def test_without_clause_is_also_a_restatement():
    step = "Print the product without creating or modifying any files."
    assert _check(step, USER) == []
