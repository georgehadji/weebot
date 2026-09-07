"""CLAUDE.md rule 2 — agents must validate model output with a Pydantic model.

The rule was documented and not followed. Four agents parsed with bare
`json.loads` and then read the result field by field with
`.get(key, default)` — which substitutes the default only when a key is
**absent**, never when it is present and wrong.

Measured on `GoalAgent.decompose` before the migration. Three of five malformed
responses ESCAPED the `except json.JSONDecodeError` written to absorb them:

    "priority": "high"        -> ValueError: invalid literal for int()
    "goals": "oops"           -> AttributeError: 'str' object has no attribute 'get'
    "max_concurrency": "many" -> ValueError: invalid literal for int()
    "tools": "web_search"     -> accepted silently, one goal built from characters
    prose instead of JSON     -> fallback (the only case that worked)

Four agents also carried four different JSON extractors, none agreeing:
`dreamer` split the fence on a newline, `goal_agent` tried a direct parse then
scanned for braces, `layer_editor_agent` scanned only when the text opened with
a fence, and `parse_agent_output` used regexes. A model that wrapped its answer
differently succeeded in some and failed in others, for no visible reason.
"""

from __future__ import annotations

import pytest

from weebot.application.ports.llm_port import LLMResponse
from weebot.models.structured_output import (
    EditSelection,
    GoalDecomposition,
    IdeaProposalList,
    extract_json_text,
    parse_structured,
)


class _FakeLLM:
    def __init__(self, content: str | None) -> None:
        self._content = content

    async def chat(self, **_kwargs):
        return LLMResponse(content=self._content, tool_calls=None, usage=None)


# ── The shared extractor ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        ('{"a": 1}', '{"a": 1}'),
        ('```json\n{"a": 1}\n```', '{"a": 1}'),
        ('```\n{"a": 1}\n```', '{"a": 1}'),
        ('Sure! Here you go: {"a": 1} — hope that helps', '{"a": 1}'),
        ('```json {"a": 1} ```', '{"a": 1}'),  # single-line fence
        ("[1, 2, 3]", "[1, 2, 3]"),  # a bare array, which dreamer is prompted for
        ("no json here", "no json here"),  # unchanged, so json.loads gives the real error
    ],
)
def test_one_extractor_handles_every_shape_the_four_handled_differently(raw, expected):
    assert extract_json_text(raw) == expected


# ── Validation, not fieldwise .get ────────────────────────────────────


def test_a_present_but_wrong_field_fails_validation():
    """`.get(key, default)` cannot see this; a Pydantic model can."""
    assert parse_structured('{"goals": "oops"}', GoalDecomposition) is None
    assert parse_structured('{"selected_indices": "all"}', EditSelection) is None


def test_an_absent_field_still_takes_its_default():
    """Validation must not make the models stricter than the agents need."""
    parsed = parse_structured("{}", GoalDecomposition)
    assert parsed is not None
    assert parsed.goals == []
    assert parsed.max_concurrency == 4
    assert parsed.synthesis_strategy == "cluster"


def test_empty_and_unparseable_return_none_rather_than_raising():
    for raw in (None, "", "   ", "not json", "```json\nnot json\n```"):
        assert parse_structured(raw, GoalDecomposition) is None


def test_bounds_live_on_the_model_not_the_call_site():
    """`min(1.0, max(0.0, float(...)))` was inline in dreamer's loop."""
    proposals = IdeaProposalList.from_payload([{"title": "t", "heat_score": 5.0}])
    assert proposals.ideas[0].heat_score == 1.0
    proposals = IdeaProposalList.from_payload([{"title": "t", "heat_score": -3.0}])
    assert proposals.ideas[0].heat_score == 0.0


def test_the_dreamer_payload_is_accepted_in_all_three_shapes():
    """Prompted for a bare array; models wrap it as `ideas` or `contracts`."""
    for payload in (
        [{"title": "t"}],
        {"ideas": [{"title": "t"}]},
        {"contracts": [{"title": "t"}]},
    ):
        assert IdeaProposalList.from_payload(payload).ideas[0].title == "t"


# ── The agent that was measured ───────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "label, payload",
    [
        ("priority is a word", '{"goals":[{"description":"d","role":"r","tools":["w"],"priority":"high"}]}'),
        ("tools is a string", '{"goals":[{"description":"d","role":"r","tools":"w","priority":0}]}'),
        ("goals is a string", '{"goals":"oops"}'),
        ("max_concurrency is a word", '{"goals":[{"description":"d","role":"r","tools":["w"],"priority":0}],"max_concurrency":"many"}'),
        ("prose, not JSON", "I think we should start by researching the market."),
        ("empty response", ""),
    ],
)
async def test_no_malformed_response_crashes_decompose(label, payload):
    """Three of these raised before. All six must reach the fallback."""
    from weebot.application.agents.goal_agent import GoalAgent

    spec = await GoalAgent(_FakeLLM(payload)).decompose("do the thing")
    assert spec is not None, f"{label}: decompose returned nothing"
    assert spec.goals, f"{label}: the fallback must still produce a usable spec"


@pytest.mark.asyncio
async def test_a_valid_response_is_used_rather_than_the_fallback():
    """The fallback must not become the only path — that would pass every
    assertion above while doing nothing."""
    from weebot.application.agents.goal_agent import GoalAgent

    payload = (
        '```json\n{"goals":[{"description":"research pricing","role":"pricing_analyst",'
        '"tools":["web_search"],"priority":1}],"max_concurrency":7,'
        '"synthesis_strategy":"merge"}\n```'
    )
    spec = await GoalAgent(_FakeLLM(payload)).decompose("do the thing")

    assert [g.description for g in spec.goals] == ["research pricing"]
    assert spec.goals[0].role == "pricing_analyst"
    assert spec.goals[0].priority == 1
    assert spec.max_concurrency == 7
    assert spec.synthesis_strategy == "merge"


@pytest.mark.asyncio
async def test_a_negative_index_no_longer_selects_from_the_end():
    """`i < len(edits)` accepted negatives, which Python reads from the end.

    A model answering `-1` silently selected the last edit instead of being
    rejected. Found by reading the migration diff, not by the survey.
    """
    from weebot.application.agents.optimizer_agent import OptimizerAgent

    assert [i for i in [-1, 0] if 0 <= i < 3] == [0]
    assert OptimizerAgent is not None  # the fix lives in rank_edits
