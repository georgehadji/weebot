"""Regression tests for SkillOpt flow construction.

`Container.build_skill_opt_flow()` raised TypeError unconditionally for an
unknown period: the DI call site passed `optimizer_llm` / `scorer` /
`target_factory` while `SkillOptFlow.__init__` required `optimizer` /
`event_bus` / `target_flow_factory`.  Nothing constructed the flow in a test,
so the drift was invisible until runtime and both CLI entry points
(`run.py`, `cli/commands/flow.py`) were dead.

These tests exist so that class of drift fails in CI instead of in production.
"""
from __future__ import annotations

import inspect

import pytest


def _di_call_kwargs() -> set[str]:
    """Keyword names the DI layer passes to ``SkillOptFlow``.

    Read from the source of ``build_skill_opt_flow`` rather than hard-coded, so
    the test tracks the call site instead of a stale copy of it.
    """
    import ast
    import textwrap

    from weebot.application.di._skillopt import SkillOptMixin

    # getsource on a method returns it at class-body indentation — dedent first.
    source = textwrap.dedent(inspect.getsource(SkillOptMixin.build_skill_opt_flow))
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "SkillOptFlow"
        ):
            return {kw.arg for kw in node.keywords if kw.arg is not None}
    raise AssertionError("No SkillOptFlow(...) call found in build_skill_opt_flow")


def test_di_call_site_matches_flow_signature() -> None:
    """Every kwarg the DI layer passes must be a real SkillOptFlow parameter."""
    from weebot.application.flows.skill_opt_flow import SkillOptFlow

    params = {n for n in inspect.signature(SkillOptFlow.__init__).parameters if n != "self"}
    unexpected = _di_call_kwargs() - params

    assert not unexpected, (
        f"DI passes kwargs SkillOptFlow does not accept: {sorted(unexpected)}. "
        "This raises TypeError at runtime and makes the whole SkillOpt "
        "subsystem unreachable."
    )


def test_di_call_site_supplies_every_required_param() -> None:
    """Every required SkillOptFlow parameter must be supplied by the DI layer.

    ``**evaluator_kwargs`` / ``**archive_kwargs`` only ever carry optional
    parameters, so an omission here is a genuine TypeError.
    """
    from weebot.application.flows.skill_opt_flow import SkillOptFlow

    sig = inspect.signature(SkillOptFlow.__init__)
    required = {
        n
        for n, p in sig.parameters.items()
        if n != "self" and p.default is inspect.Parameter.empty
    }
    missing = required - _di_call_kwargs()

    assert not missing, (
        f"DI never passes required SkillOptFlow params: {sorted(missing)}."
    )


def test_flow_constructs_with_di_kwargs() -> None:
    """Construct the flow with exactly the DI kwarg names — no TypeError."""
    from weebot.application.flows.skill_opt_flow import SkillOptFlow

    kwargs = {name: None for name in _di_call_kwargs()}
    kwargs.update(
        skill_name="demo",
        train_tasks=["task-1"],
        epochs=1,
        steps_per_epoch=1,
        batch_size=1,
        use_planning=False,
        target_flow_factory=lambda session: None,
    )

    flow = SkillOptFlow(**kwargs)

    assert isinstance(flow, SkillOptFlow)
    assert flow.is_done() is False


@pytest.mark.parametrize("removed_param", ["self_improver", "self_improve_contracts"])
def test_dead_self_improvement_path_is_gone(removed_param: str) -> None:
    """The guaranteed-no-op contract/rule patching path must stay deleted.

    It passed ``new_content == current_content`` to ``SelfImprover.propose_patch``,
    which short-circuits on equality, so it never produced a patch while logging
    at INFO as though it were healthy.
    """
    from weebot.application.flows.skill_opt_flow import SkillOptFlow

    assert not hasattr(SkillOptFlow, "_run_self_improvement")
    assert removed_param not in inspect.signature(SkillOptFlow.__init__).parameters
