"""``scripts/auto_execute.py`` can build the flow it runs.

Found by the dead-code audit: the script asked the container for ``"llm"``,
``"event_bus"`` and ``"state_repo"``, keys the container does not have (they are
keyed by port type), so it raised KeyError before doing anything. It also built
``PlanActFlow`` by hand without a mediator, which PlanningState requires, and
called ``Session.create_new()``, which does not exist.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from weebot.application.di import Container
from weebot.application.models.tool_collection import ToolCollection
from weebot.domain.models.session import Session


def _script():
    spec = importlib.util.spec_from_file_location("auto_execute", Path("scripts/auto_execute.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_script_builds_a_flow_with_a_mediator():
    container = Container()
    container.configure_defaults()
    flow = _script().build_flow(container, Session(id="s-auto"), ToolCollection())
    assert flow._mediator is not None
    assert flow._state_repo is not None
