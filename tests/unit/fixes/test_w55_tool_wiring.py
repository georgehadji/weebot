"""W5.5 (F35): tools get their collaborators from the registry's wiring.

Six tools (audit, knowledge, persistent memory, video ingest, voice in/out)
built a whole `Container()` when the registry constructed them with no
arguments. And every caller that built a collection repeated the same
collaborator arguments -- `mcp_scope` passed only `llm_port`, so its rebuilt
collections lost the state repo, the reranker and the tool config.

Now the DI container gives its `tool_registry` one `wiring` callable, and every
collection built from that registry gets the same collaborators.
"""

from __future__ import annotations

import pytest

from weebot.tools.tool_registry import RoleBasedToolRegistry


@pytest.fixture
def no_container(monkeypatch):
    def _refuse(*a, **k):
        raise AssertionError("a tool built a Container")

    monkeypatch.setattr("weebot.application.di.Container", _refuse)


@pytest.mark.parametrize(
    ("module", "cls"),
    [
        ("weebot.tools.audit_tool", "AuditTool"),
        ("weebot.tools.knowledge_tool", "KnowledgeTool"),
        ("weebot.tools.persistent_memory", "PersistentMemoryTool"),
        ("weebot.tools.video_ingest_tool", "VideoIngestTool"),
        ("weebot.tools.voice_input_tool", "VoiceInputTool"),
        ("weebot.tools.voice_output_tool", "VoiceOutputTool"),
    ],
)
def test_a_bare_tool_refuses_instead_of_building_a_container(no_container, module, cls):
    import importlib

    tool_cls = getattr(importlib.import_module(module), cls)
    with pytest.raises(RuntimeError, match="collaborator"):
        tool_cls()


def test_the_registry_wiring_supplies_tool_collaborators(no_container):
    repo, speech = object(), object()
    wiring = {
        "collaborators": {"knowledge": {"repo": repo}, "voice_output": {"speech": speech}}
    }
    tools = RoleBasedToolRegistry(wiring=lambda: wiring).create_tool_collection_from_names(
        ["knowledge", "voice_output"]
    )
    assert tools.get_tool("knowledge")._repo is repo
    assert tools.get_tool("voice_output")._speech is speech


def test_the_registry_wiring_fills_what_the_caller_omits(no_container):
    rerank, repo = object(), object()
    registry = RoleBasedToolRegistry(wiring=lambda: {"rerank": rerank, "state_repo": repo})
    tools = registry.create_tool_collection_from_names(
        ["web_search", "dispatch_parallel_tasks"], flow_factory=lambda s: None
    )
    assert tools.get_tool("web_search")._rerank is rerank
    assert tools.get_tool("dispatch_parallel_tasks")._state_repo is repo


def test_a_tool_without_its_collaborator_is_skipped(no_container):
    tools = RoleBasedToolRegistry().create_tool_collection_from_names(["knowledge"])
    assert tools.get_tool("knowledge") is None


def test_the_container_registry_carries_the_container_wiring():
    from weebot.application.di import Container
    from weebot.application.ports.speech_port import SpeechPort

    c = Container()
    c.configure_defaults()
    tools = c.get("tool_registry").create_tool_collection_from_names(["voice_output"])
    assert tools.get_tool("voice_output")._speech is c.get(SpeechPort)
