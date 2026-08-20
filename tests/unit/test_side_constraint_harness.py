"""Offline side-constraint regression harness (Lost-in-Compaction Phase 6).

Drives the golden set in ``weebot/config/harness/side_constraints.yaml``
through the whole pipeline -- extract, classify, compile, render, compact,
deliver -- with no LLM and no network.

**What this measures, and what it does not.** The paper's four-group design
(K_lctx / K_lctx_sc / K_comp / K_ub, Eq. 9) exists to separate a model's
prior tendency toward the compliant answer from the effect of the constraint
itself. A scripted-policy stub has no prior: it complies exactly when the
constraint text is in the messages it received, so c_lctx == 0 and c_ub == 1
by construction and ``EffectRetention = (c_comp - c_lctx) / (c_ub - c_lctx)``
degenerates to c_comp. Computing it anyway would dress a plumbing check up as
a replication of the paper's numbers.

So this suite asserts the thing weebot is actually responsible for and can
actually control: **did the constraint reach the acting model's last message,
and did the right subset compile into a gate.** Model compliance given a
delivered constraint is the model's business and is not regression-testable
offline.

The negative cases are the half the paper never measured: it reports the
extractor's 93.7% recall on a planted string but no precision and no
false-positive rate. On a long session even a 1% FP rate injects spurious
PERMANENT constraints, each rendered last and framed as strict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from weebot.application.agents.executor import ExecutorAgent
from weebot.application.models.tool_collection import ToolCollection
from weebot.application.services.constraint_compilers import compile_enforceable
from weebot.application.services.memory_compactor import MemoryCompactor
from weebot.application.services.session_constraint_extractor import SessionConstraintExtractor
from weebot.domain.models.event import MessageEvent
from weebot.domain.models.plan import Plan, Step
from weebot.domain.models.session import Session
from weebot.domain.models.session_constraint import ConstraintKind, SessionConstraintRegistry

_GOLDEN = (
    Path(__file__).resolve().parents[2] / "weebot" / "config" / "harness" / "side_constraints.yaml"
)


def _load_cases() -> list[dict]:
    with _GOLDEN.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)["cases"]


CASES = _load_cases()
CONSTRAINT_CASES = [c for c in CASES if c["expect_extracted"]]
NEGATIVE_CASES = [c for c in CASES if not c["expect_extracted"]]


async def _extract(turn: str) -> SessionConstraintRegistry:
    """Run the free (heuristic) tier and return a registry of what it found."""
    result = await SessionConstraintExtractor().extract(turn, registry=SessionConstraintRegistry())
    return SessionConstraintRegistry(constraints=result.added)


class TestGoldenFile:
    """The committed golden file must parse and be internally consistent."""

    def test_file_parses(self):
        assert CASES, "golden file produced no cases"

    def test_every_case_has_required_fields(self):
        required = {"id", "turn", "expect_extracted", "expect_enforceable", "note"}
        for case in CASES:
            missing = required - case.keys()
            assert not missing, f"{case.get('id')} missing {missing}"

    def test_ids_are_unique(self):
        ids = [c["id"] for c in CASES]
        assert len(ids) == len(set(ids))

    def test_kinds_are_valid_enum_members(self):
        valid = {k.value for k in ConstraintKind}
        for case in CASES:
            if case.get("kind") is not None:
                assert case["kind"] in valid, f"{case['id']}: bad kind"

    def test_every_kind_is_represented(self):
        """A per-kind floor is meaningless if a kind has no cases."""
        covered = {c["kind"] for c in CONSTRAINT_CASES if c.get("kind")}
        assert covered == {k.value for k in ConstraintKind}

    def test_unenforceable_kinds_are_marked_unenforceable(self):
        """PROCESS/PREFERENCE/OUTPUT are prompt-delivered only, by design."""
        for case in CONSTRAINT_CASES:
            if case.get("kind") in {"process", "preference", "output"}:
                assert case["expect_enforceable"] is False, case["id"]


class TestExtractionCoverage:
    @pytest.mark.parametrize("case", CONSTRAINT_CASES, ids=lambda c: c["id"])
    async def test_constraint_is_extracted(self, case):
        registry = await _extract(case["turn"])
        assert registry.active(), f"{case['id']}: nothing extracted from {case['turn']!r}"

    @pytest.mark.parametrize("case", CONSTRAINT_CASES, ids=lambda c: c["id"])
    async def test_kind_is_correct(self, case):
        registry = await _extract(case["turn"])
        kinds = {c.kind.value for c in registry.active()}
        assert case["kind"] in kinds, f"{case['id']}: got {kinds}, want {case['kind']}"

    @pytest.mark.parametrize("case", CONSTRAINT_CASES, ids=lambda c: c["id"])
    async def test_direction_is_correct(self, case):
        registry = await _extract(case["turn"])
        directions = {c.direction.value for c in registry.active()}
        assert (
            case["direction"] in directions
        ), f"{case['id']}: got {directions}, want {case['direction']}"

    async def test_per_kind_floor(self):
        """Every category must extract, not just the easy ones.

        The paper's own numbers make an averaged score misleading: PROCESS is
        the worst-retained category by compactors, ACTION is the extractor's
        weakest, PREFERENCE is its strongest. A single overall percentage can
        be met entirely by the categories that carry no safety weight.
        """
        by_kind: dict[str, list[bool]] = {}
        for case in CONSTRAINT_CASES:
            registry = await _extract(case["turn"])
            by_kind.setdefault(case["kind"], []).append(bool(registry.active()))
        failed = {k: v for k, v in by_kind.items() if not all(v)}
        assert not failed, f"kinds with extraction misses: {failed}"


class TestExtractionPrecision:
    """The half the paper never measured."""

    @pytest.mark.parametrize("case", NEGATIVE_CASES, ids=lambda c: c["id"])
    async def test_non_constraint_extracts_nothing(self, case):
        registry = await _extract(case["turn"])
        assert not registry.active(), (
            f"{case['id']}: spurious constraint from {case['turn']!r} -> "
            f"{[c.text for c in registry.active()]}"
        )


class TestCompilation:
    @pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
    async def test_enforceability_matches_expectation(self, case):
        registry = await _extract(case["turn"])
        compiled = compile_enforceable(registry)
        assert (
            bool(compiled) is case["expect_enforceable"]
        ), f"{case['id']}: compiled={[c.text for c in compiled]}"

    async def test_loosen_constraint_never_compiles(self):
        """Paper SC#1. A gate enforcing it would pause to ask for confirmation."""
        case = next(c for c in CASES if c["id"] == "sc01")
        registry = await _extract(case["turn"])
        assert registry.active(), "sc01 must still be extracted and rendered"
        assert compile_enforceable(registry) == []


class TestRevocation:
    """The case the paper's set does not contain (plan D8)."""

    async def test_revoked_constraint_leaves_the_rendered_block(self):
        case = next(c for c in CASES if c.get("revoked_by"))
        registry = await _extract(case["turn"])
        text = registry.active()[0].text
        assert text in registry.render()

        revoked = registry.revoke(text)
        assert revoked.active() == []
        assert compile_enforceable(revoked) == []
        assert revoked.render() == "", (
            "a fully revoked registry must render empty, or the stale "
            "constraint outranks the live user turn"
        )


# ── End-to-end delivery: does the constraint reach messages[-1]? ────────


@dataclass
class _FakeCascadeResponse:
    content: str = "done"
    tool_calls: list = field(default_factory=list)


class TestDeliveryUnderCompaction:
    """The K_ub assertion: constraint present in the acting model's last message.

    This is the one property weebot fully controls, and the one the paper's
    K_ub condition shows is worth controlling -- >98% compliance for every
    downstream model tested, versus 31.8-58.5% for a constraint left to
    survive compaction on its own.
    """

    async def _last_message_for(self, block: str) -> dict:
        executor = ExecutorAgent(llm=MagicMock(), tools=ToolCollection(), session_constraints=block)
        captured: dict = {}

        async def _fake_call_with_cascade(messages, description):
            captured["messages"] = messages
            return _FakeCascadeResponse()

        executor._cascade.call_with_cascade = _fake_call_with_cascade

        step = Step(id="s1", description="do the thing")
        plan = Plan(title="t", message="m", steps=[step])
        [e async for e in executor.execute_step(plan, step)]
        return captured["messages"][-1]

    @pytest.mark.parametrize("case", CONSTRAINT_CASES, ids=lambda c: c["id"])
    async def test_rendered_constraint_is_the_last_message(self, case):
        registry = await _extract(case["turn"])
        block = registry.render()
        last = await self._last_message_for(block)
        assert last["content"] == block
        assert registry.active()[0].text in last["content"]

    async def test_constraint_survives_a_compaction_pass(self):
        """The registry lives outside the transcript, so compaction cannot
        evict it -- that is the whole architectural point (paper section 6).

        Compaction is applied to a session whose transcript held the turn,
        and the delivered block is still assembled from the registry.
        """
        case = next(c for c in CASES if c["id"] == "sc02")
        registry = await _extract(case["turn"])
        block = registry.render()

        session = Session(
            id="h1",
            events=[
                MessageEvent(role="user", message=case["turn"]),
                *[MessageEvent(role="assistant", message=f"filler {i}") for i in range(50)],
            ],
        )
        compacted = MemoryCompactor().compact_session(session)

        # Whatever compaction did to the transcript, delivery is unaffected.
        last = await self._last_message_for(block)
        assert registry.active()[0].text in last["content"]
        assert compacted.id == "h1"
