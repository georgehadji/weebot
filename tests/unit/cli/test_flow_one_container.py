"""`flow run` builds one DI container per process, not two (W5.3).

The CLI built its own `Container()` and `interfaces.factories` built a shared
one for the flows and tools, so every `flow run` configured the whole object
graph twice (two "CatalogValidator" lines on the 2026-10-23 smoke run; the
W5.2 acceptance check is one per process).
"""

from __future__ import annotations

from cli.commands import flow as flow_cmd
from weebot.interfaces import factories


class _Container:
    def get(self, key):
        return ("resolved", key)


def test_the_cli_uses_the_shared_container(monkeypatch):
    shared = _Container()
    monkeypatch.setattr(factories, "_shared_container", shared)
    monkeypatch.setattr(flow_cmd, "_container", None)
    flow_cmd._get_state_repo()
    assert flow_cmd._container is shared


def test_shared_container_is_built_once(monkeypatch):
    built = []

    class _Fake:
        def configure_defaults(self):
            built.append(self)

    monkeypatch.setattr(factories, "_shared_container", None)
    monkeypatch.setattr("weebot.application.di.Container", _Fake)
    first = factories.shared_container()
    assert factories.shared_container() is first and len(built) == 1
