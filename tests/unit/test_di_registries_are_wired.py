"""Every tool registry the container builds gets the container's wiring.

Found 2026-10-23: `build_mediator` and `_create_sub_agent_factory` built
`RoleBasedToolRegistry()` with no `wiring`, so every tool with constructor
collaborators (knowledge, audit_session, persistent_memory, voice_input,
voice_output, video_ingest, and ocr's vision fallback) was skipped from those
tool sets. The cached "tool_registry" had the wiring; these two did not.
"""

from __future__ import annotations

import weebot.application.services.tool_registry as tr
from weebot.application.di import Container


def test_the_container_never_builds_an_unwired_registry(monkeypatch):
    built: list[object] = []
    real = tr.RoleBasedToolRegistry

    class _Recording(real):
        def __init__(self, *a, **kw):
            built.append(kw.get("wiring"))
            super().__init__(*a, **kw)

    monkeypatch.setattr(tr, "RoleBasedToolRegistry", _Recording)
    container = Container()
    container.configure_defaults()
    container.build_mediator()
    container._create_sub_agent_factory()

    assert built, "no registry was built"
    assert all(w is not None for w in built), f"{built.count(None)} registry(ies) built unwired"
