"""``scripts/auto_execute.py`` keeps the run limits it had, and lets the container
supply what the container already supplies.

Found by review of the auto_execute fix: building the flow through ``create_flow``
dropped the script's ``max_iterations=80`` and ``max_step_repetitions=5``, so long runs
stopped at the default 50 iterations. The script also passed ``state_repo``, which
``create_flow`` resolves on its own.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from weebot.application.di import Container
from weebot.application.models.tool_collection import ToolCollection
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.session import Session


def _script():
    spec = importlib.util.spec_from_file_location("auto_execute", Path("scripts/auto_execute.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _container():
    container = Container()
    container.configure_defaults()
    return container


def test_the_flow_keeps_the_scripts_limits():
    flow = _script().build_flow(_container(), Session(id="s-auto"), ToolCollection())
    assert flow._max_iterations == 80
    assert flow._max_step_repetitions == 5


def test_the_script_leaves_the_state_repo_to_the_container(monkeypatch):
    container = _container()
    real_get = container.get
    create = real_get("create_flow")
    passed = {}

    def spy(**kwargs):
        passed.update(kwargs)
        return create(**kwargs)

    monkeypatch.setattr(
        container, "get", lambda key: spy if key == "create_flow" else real_get(key)
    )
    flow = _script().build_flow(container, Session(id="s-auto"), ToolCollection())
    assert "state_repo" not in passed
    assert flow._state_repo is real_get(StateRepositoryPort)
