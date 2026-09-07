"""CLAUDE.md rule 2, applied to the agents that were still parsing by hand.

P5-1. The rule — "agents MUST return structured JSON validated via Pydantic
models in `weebot/models/structured_output.py`" — was declared and not
followed; the divergence had reached ten modules. The owner's decision was that
the rule is real and the agents get migrated. These are the measurements that
made each migration a repair rather than a tidy-up.

`.get(key, default)` substitutes the default only when a key is ABSENT, never
when it is present and wrong, and that is where every one of these came from.
"""

from __future__ import annotations

import types

import pytest

from weebot.models.structured_output import extract_json_text


class _LLM:
    def __init__(self, payload: str):
        self.payload = payload

    async def chat(self, **_):
        return types.SimpleNamespace(content=self.payload, model="x", usage=None)


class _BoomLLM:
    async def chat(self, **_):
        raise RuntimeError("provider down")


# ── ParallelPlanner ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "payload",
    [
        '{"steps": "just do it"}',
        '{"steps": {"1": "do"}}',
        '{"steps": [1, 2, 3]}',
    ],
)
@pytest.mark.asyncio
async def test_a_wrong_typed_steps_field_does_not_escape(payload):
    """Declared `list[dict[str, str]] | None`; measured returning str/dict/list[int]."""
    from weebot.application.agents.parallel_planner import ParallelPlanner

    planner = ParallelPlanner(llm=_LLM(payload))
    subtask = types.SimpleNamespace(title="t", description="d")
    out = await planner._plan_subtask(subtask, 0)

    assert out is None, (
        f"{payload} produced {type(out).__name__} where the signature promises "
        "list[dict[str, str]] | None; it reached _assemble_candidates"
    )


@pytest.mark.asyncio
async def test_a_well_formed_steps_field_still_works():
    from weebot.application.agents.parallel_planner import ParallelPlanner

    planner = ParallelPlanner(llm=_LLM('{"steps": [{"description": "do it"}]}'))
    subtask = types.SimpleNamespace(title="t", description="d")
    assert await planner._plan_subtask(subtask, 0) == [{"description": "do it"}]


@pytest.mark.asyncio
async def test_a_malformed_decomposition_is_reported_not_just_empty(caplog):
    import logging

    from weebot.application.agents.parallel_planner import ParallelPlanner

    planner = ParallelPlanner(llm=_LLM('{"subtasks": "a, b"}'))
    with caplog.at_level(logging.WARNING):
        assert await planner._decompose("task") == []
    assert any("SubtaskDecomposition" in r.getMessage() for r in caplog.records), (
        "an empty decomposition was returned with no record of why"
    )


# ── OptimizerAgent ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "payload",
    [
        '{"edits": "append everything"}',
        '{"edits": [{"op": "frobnicate", "content": "x"}]}',
        '{"edits": [{"op": "append", "support_count": "many"}]}',
    ],
)
def test_malformed_edits_name_the_model_they_failed(payload, caplog):
    """All three collapsed to [] from one bare except, with one generic warning."""
    import logging

    from weebot.application.agents.optimizer_agent import OptimizerAgent

    with caplog.at_level(logging.WARNING):
        assert OptimizerAgent._parse_edits(payload) == []
    assert any("SkillEditList" in r.getMessage() for r in caplog.records)


def test_well_formed_edits_still_parse():
    from weebot.application.agents.optimizer_agent import OptimizerAgent

    edits = OptimizerAgent._parse_edits(
        '{"edits": [{"op": "append", "content": "x", "support_count": 3}]}'
    )
    assert len(edits) == 1
    assert (edits[0].op, edits[0].content, edits[0].support_count) == ("append", "x", 3)


# ── SynthesizerAgent ───────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "payload",
    [
        '{"clusters": "none found", "synthesis": "s"}',
        '{"clusters": [], "synthesis": {"text": "s"}}',
        "not json at all",
    ],
)
@pytest.mark.asyncio
async def test_a_bad_synthesis_payload_degrades_instead_of_raising(payload):
    """SwarmResult was built OUTSIDE the try, so a bad field lost the whole swarm."""
    from weebot.application.agents.synthesizer_agent import SynthesizerAgent

    results = [{"role": "researcher", "summary": "found A"}]
    out = await SynthesizerAgent(llm=_LLM(payload)).synthesize("q", results)

    assert out.clusters == []
    assert "found A" in out.synthesis, "the fallback lost the agents' work"


@pytest.mark.asyncio
async def test_the_two_synthesis_fallbacks_stay_distinct():
    """A failed call falls back to the raw merge; a bad payload does not."""
    from weebot.application.agents.synthesizer_agent import SynthesizerAgent

    results = [{"role": "researcher", "summary": "found A"}]
    on_llm_failure = await SynthesizerAgent(llm=_BoomLLM()).synthesize("q", results)
    on_bad_payload = await SynthesizerAgent(llm=_LLM("prose")).synthesize("q", results)

    assert on_llm_failure.synthesis.startswith("**researcher**")
    assert on_bad_payload.synthesis.startswith("### researcher")


@pytest.mark.asyncio
async def test_a_well_formed_synthesis_is_used():
    from weebot.application.agents.synthesizer_agent import SynthesizerAgent

    out = await SynthesizerAgent(
        llm=_LLM('{"clusters": [{"label": "a"}], "synthesis": "the report"}')
    ).synthesize("q", [{"role": "r", "summary": "s"}])
    assert out.synthesis == "the report"
    assert out.clusters == [{"label": "a"}]


# ── The shared extractor ───────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('Here is the plan: {"a": 1}', {"a": 1}),
        ('{"a": 1}\nThat is the plan.', {"a": 1}),
        # The two the shared extractor could NOT do before PlannerAgent's
        # four-strategy version was folded into it.
        ('{"a": 1} and also {"b": 2}', {"a": 1}),
        ('{"a": {"b": 1}} trailing }', {"a": {"b": 1}}),
        ('[{"a": 1}]', [{"a": 1}]),
        ('```\n{"a": 1}\n```\nnotes', {"a": 1}),
        ('{"a": "}"}', {"a": "}"}),
    ],
)
def test_the_one_extractor_handles_every_shape_the_five_did(text, expected):
    import json

    assert json.loads(extract_json_text(text)) == expected


def test_the_planner_no_longer_carries_its_own_extractor():
    """Checked against the AST, so the docstring naming the old steps is not a hit."""
    import ast
    import inspect
    import textwrap

    from weebot.application.agents import planner

    fn = ast.parse(
        textwrap.dedent(inspect.getsource(planner.PlannerAgent._parse_json_content))
    ).body[0]
    ast.get_docstring(fn)  # present by design; the assertions below ignore it
    called = {
        node.func.attr
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    } | {
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "extract_json_text" in called
    assert "raw_decode" not in called, "the planner still has a second extractor"
    assert not hasattr(planner.PlannerAgent, "_strip_code_fences")


def test_the_planner_still_insists_on_an_object():
    from weebot.application.agents.planner import PlannerAgent

    assert PlannerAgent._parse_json_content('{"title": "t"}') == {"title": "t"}
    with pytest.raises(ValueError):
        PlannerAgent._parse_json_content('[1, 2, 3]')
    with pytest.raises(ValueError):
        PlannerAgent._parse_json_content("no json here")
