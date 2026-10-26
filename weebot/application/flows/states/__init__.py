"""Package marker: without it this directory is a namespace package, which
import-linter cannot see -- see tests/unit/test_architecture_fitness.py
(test_no_namespace_packages_hide_modules_from_import_linter).

Importing the states here populates the state registry (``base.register_state``), so
importing any one state module is enough for ``new_state(StateId.X)`` to resolve.
States never import each other (plan 3.6).
"""

from weebot.application.flows.states import (  # noqa: F401
    critiquing,
    executing,
    plan_review,
    planning,
    premortem,
    reviewing,
    summarizing,
    updating,
    verifying,
)
