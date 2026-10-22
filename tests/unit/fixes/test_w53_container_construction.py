"""W5.3 (F28): a ratchet on hand-built `Container()` sites outside application/di.

Each `Container()` + `configure_defaults()` builds a second object graph: its
own event bus, state repo and LLM adapters, which is how a flow built from one
container published to a bus nobody subscribed to. scripts/lint_container_
construction.py counts the sites so the number can only go down, and
interfaces/factories.py now resolves everything through its one cached
container.
"""

from __future__ import annotations

import importlib.util
import pathlib
import textwrap

_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _lint():
    spec = importlib.util.spec_from_file_location(
        "lint_container_construction", _ROOT / "scripts" / "lint_container_construction.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_spelling_of_a_container_call_counts(tmp_path):
    src = tmp_path / "mod.py"
    src.write_text(
        textwrap.dedent(
            """
            import importlib
            from weebot.application import di
            from weebot.application.di import Container

            a = Container()
            b = di.Container()
            c = importlib.import_module("weebot.application.di").Container()
            # Container() in a comment, and in a string: "Container()"
            d = ContainerFactory()
            """
        ),
        encoding="utf-8",
    )
    hits = _lint().find_violations((str(src),))
    assert [h.rsplit(":", 1)[1] for h in hits] == ["6", "7", "8"]


def test_the_di_package_is_exempt():
    hits = _lint().find_violations(("weebot/application/di",))
    assert hits == []


def test_factories_builds_one_shared_container():
    hits = _lint().find_violations(("weebot/interfaces/factories.py",))
    assert len(hits) == 1, hits
