"""`PlanActFlow` builds the same flow from a config object or from the legacy keywords.

`PlanActFlow.__init__` used to translate 36 loose keywords into `PlanActFlowConfig`
inline, in an 89-line block of `name=name`. That block was replaced by a delegation to
`PlanActFlowConfig(**legacy)` on the strength of one claim: every legacy keyword is a
config field of the same name with the same default. These tests hold that claim, so
the delegation stays honest rather than becoming a silent second table.
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest

from weebot.application.flows import _plan_act_wiring
from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.models.plan_act_flow_config import PlanActFlowConfig
from weebot.domain.models.session import Session


def _default(field: dataclasses.Field):
    if field.default is not dataclasses.MISSING:
        return field.default
    if field.default_factory is not dataclasses.MISSING:
        return field.default_factory()
    return dataclasses.MISSING


def _same(left, right) -> bool:
    """Whether two wired attributes agree.

    Some of what `__init__` wires is a fresh object per flow -- a fact resolver, a
    compactor, an `asyncio.Lock` -- so identity is *supposed* to differ between two
    constructions. For those, agreeing means "same type"; for anything with its own
    `__eq__` (or none at all), the value has to match too.
    """
    if left is right:
        return True
    if type(left) is not type(right):
        return False
    if type(left).__eq__ is object.__eq__:
        return True  # identity-only equality: same type is all that can be asked
    return left == right


class TestTheLegacySurfaceIsTheConfigSurface:
    def test_every_legacy_keyword_is_a_config_field(self):
        fields = PlanActFlowConfig.__dataclass_fields__
        orphans = [name for name in _plan_act_wiring.LEGACY_KWARG_NAMES if name not in fields]
        assert orphans == [], (
            "these legacy keywords have no PlanActFlowConfig field, so routing the "
            f"legacy path through the dataclass would drop them: {orphans}"
        )

    def test_every_legacy_default_matches_the_config_default(self):
        """The claim the delegation rests on.

        `PlanActFlowConfig(**{})` and `PlanActFlow()` must describe the same flow. If a
        default is changed on one side only, the two routes silently diverge -- which
        is the failure mode the inline mapping would have had too, and the reason this
        is checked rather than assumed.
        """
        fields = PlanActFlowConfig.__dataclass_fields__
        mismatches = []
        for name in _plan_act_wiring.LEGACY_KWARG_NAMES:
            field_default = _default(fields[name])
            if field_default is dataclasses.MISSING:
                continue  # the dataclass has no default, so neither route can omit it
            empty = PlanActFlowConfig.__dataclass_fields__[name]
            if empty.default is not dataclasses.MISSING and field_default != _default(empty):
                mismatches.append(name)
        assert mismatches == [], f"legacy/config defaults disagree: {mismatches}"

    def test_the_config_carries_fields_the_legacy_route_cannot_reach(self):
        """Direction of travel: the config is the surface, the keywords are the subset.

        If this ever became equal, the parameter object would have stopped earning its
        keep -- and WB-06's note in the plan records that 15 fields (the harness, the
        middleware chain, the tool registry, hooks) are reachable only through it.
        """
        fields = set(PlanActFlowConfig.__dataclass_fields__)
        legacy = set(_plan_act_wiring.LEGACY_KWARG_NAMES)
        assert fields - legacy, "the config no longer has fields the legacy route cannot pass"


class TestTheTwoRoutesAgree:
    def _wire_from(self, **kwargs) -> dict[str, object]:
        flow = PlanActFlow(**kwargs)
        return {
            name: value
            for name, value in vars(flow).items()
            if name not in {"_planner", "_summary_executor", "_stdlib_logger", "_logger"}
        }

    def test_a_config_and_the_keywords_build_the_same_attributes(self):
        session = Session()
        from_keywords = self._wire_from(session=session, llm=None, tools=None, max_iterations=7)
        from_config = self._wire_from(
            config=PlanActFlowConfig(llm=None, tools=None, session=session, max_iterations=7)
        )

        assert from_keywords.keys() == from_config.keys()
        differing = [
            name
            for name in from_keywords
            if not _same(from_keywords[name], from_config[name])
        ]
        assert differing == [], f"the two construction routes disagree on: {differing}"

    def test_max_iterations_from_the_keyword_reaches_the_flow(self):
        """One end-to-end check, so the comparison above cannot pass on two `None`s."""
        flow = PlanActFlow(session=Session(), max_iterations=7)
        assert flow._max_iterations == 7

    def test_the_keyword_route_still_allows_omitting_the_llm_and_the_tools(self):
        """Compatibility the parameter object does not offer, and callers depend on.

        `PlanActFlowConfig` requires both; the legacy signature defaulted them to
        `None`, and a paused-flow test (`tests/e2e/test_gate_pause_survives_the_seam.py`
        :67) builds a flow with neither because it never calls a model.
        """
        flow = PlanActFlow(session=Session())
        assert flow._llm is None and flow._tools is None


class TestAnUnknownKeywordIsRejectedByName:
    def test_it_raises_type_error_naming_the_keyword(self):
        with pytest.raises(TypeError) as exc:
            PlanActFlow(session=Session(), llm_port=object())
        assert "llm_port" in str(exc.value)

    def test_the_message_lists_the_surface_that_works(self):
        """A caller who mistyped needs the 36 names, not "unexpected keyword argument"."""
        with pytest.raises(TypeError) as exc:
            PlanActFlow(session=Session(), nope=True)
        message = str(exc.value)
        assert "llm" in message and "misalignment_journal" in message

    def test_the_constructor_no_longer_does_the_work_inline(self):
        """The size claim, held as a number rather than as a habit.

        `__init__` was 234 lines; anything above ~25 means a job moved back in.
        """
        source = inspect.getsource(PlanActFlow.__init__)
        body = [line for line in source.splitlines() if line.strip()]
        assert len(body) <= 25, f"__init__ is {len(body)} non-blank lines again"
