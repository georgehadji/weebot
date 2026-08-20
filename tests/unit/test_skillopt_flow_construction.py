"""Regression tests for SkillOpt flow construction.

`Container.build_skill_opt_flow()` raised TypeError unconditionally for an
unknown period: the DI call site passed `optimizer_llm` / `scorer` /
`target_factory` while `SkillOptFlow.__init__` required `optimizer` /
`event_bus` / `target_flow_factory`.  Nothing constructed the flow in a test,
so the drift was invisible until runtime and both CLI entry points
(`run.py`, `cli/commands/flow.py`) were dead.

A second, distinct instance of the same drift class was found in the same
function: the call to ``register_skillopt_handlers(...)`` passed two
positional args plus a nonexistent ``evolution_tracker`` kwarg against a
keyword-only signature that requires ``state_repo`` / ``trajectory_repo`` /
``validation_runner`` / ``flow_factory``. The AST-based tests below only ever
inspected the ``SkillOptFlow(...)`` call, so they could not catch it — the
call site raised TypeError before ``SkillOptFlow(...)`` was ever reached.
A third instance was in ``_create_optimizer_agent``, which passed
``llm=...`` against ``OptimizerAgent.__init__``'s ``optimizer_llm`` param.

These tests exist so that class of drift fails in CI instead of in production.
"""

from __future__ import annotations

import inspect

import pytest

from weebot.application.di import Container
from weebot.application.ports.llm_port import LLMPort
from weebot.tools.tool_registry import RoleBasedToolRegistry


class _DummyLLMPort(LLMPort):
    """Minimal LLMPort stand-in — no network, matches test_mcp_di_factories.py."""

    async def chat(
        self,
        messages,
        tools=None,
        tool_choice="auto",
        response_format=None,
        model=None,
        temperature=None,
        max_tokens=None,
    ):
        from weebot.domain.models.llm_response import LLMResponse

        return LLMResponse(content="", model="dummy")


@pytest.fixture
def container(tmp_path, monkeypatch):
    """A Container configured for SkillOpt with real network calls stubbed out.

    configure_skillopt() resolves two independent LLM factories —
    FactoriesMixin._create_llm (via configure_defaults, for the target model)
    and SkillOptMixin._create_llm_by_id (for the optimizer model) — both must
    be stubbed or construction reaches out to whatever OPENROUTER_API_KEY the
    developer's real .env happens to hold.

    build_mediator() also unconditionally constructs a fresh
    RoleBasedToolRegistry() whenever an LLMPort is resolvable (which it is
    here, deliberately, so the mediator actually wires handlers). Real
    construction walks and imports every module under weebot/tools/ —
    including computer_use.py, which imports pyautogui -> pyscreeze -> cv2
    -> numpy — native-DLL loading slow enough in a monitored/sandboxed
    environment to blow well past a test timeout. This is pre-existing
    behavior at weebot/application/di/__init__.py's build_mediator(),
    unrelated to what this file tests, so the constructor is replaced
    outright rather than trying to dodge it via internal caching. tools=
    isn't a parameter build_skill_opt_flow's DI call touches, so an empty
    role_mappings has no effect on what these tests assert.
    """
    c = Container()
    monkeypatch.setattr(c, "_create_llm", lambda _model=None: _DummyLLMPort())
    monkeypatch.setattr(c, "_create_llm_by_id", lambda _model_id=None: _DummyLLMPort())
    monkeypatch.setattr(
        RoleBasedToolRegistry,
        "__init__",
        lambda self, role_mappings=None: setattr(self, "role_mappings", role_mappings or {}),
    )
    db_path = str(tmp_path / "sessions.db")
    c.configure_skillopt(db_path=db_path)
    return c


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
        n for n, p in sig.parameters.items() if n != "self" and p.default is inspect.Parameter.empty
    }
    missing = required - _di_call_kwargs()

    assert not missing, f"DI never passes required SkillOptFlow params: {sorted(missing)}."


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


# ── End-to-end: Container.build_skill_opt_flow() must not raise ─────────────
#
# Everything above only ever inspected the SkillOptFlow(...) call via AST or
# constructed SkillOptFlow directly, bypassing DI entirely. None of it could
# have caught the register_skillopt_handlers(...) TypeError, because that
# call happens before SkillOptFlow(...) is ever reached. These tests call
# the real DI path.


def test_build_skill_opt_flow_does_not_raise(container: Container) -> None:
    """The full DI path — register_skillopt_handlers + SkillOptFlow — must
    construct without TypeError. This is the call CLI entry points make."""
    flow = container.build_skill_opt_flow(
        skill_name="demo", train_tasks=["task-1"], epochs=1, steps_per_epoch=1, batch_size=1
    )

    from weebot.application.flows.skill_opt_flow import SkillOptFlow

    assert isinstance(flow, SkillOptFlow)
    assert flow.is_done() is False


def test_build_skill_opt_flow_registers_skillopt_handlers(container: Container) -> None:
    """The mediator built by build_skill_opt_flow carries the SkillOpt
    command handlers — not just the CreatePlan/ExecuteStep defaults."""
    from weebot.application.cqrs.commands.trajectory_commands import ScoreTrajectoryCommand
    from weebot.application.cqrs.commands.skill_edit_commands import ApplySkillEditsCommand
    from weebot.application.cqrs.commands.validation_commands import ValidateSkillCommand
    from weebot.application.cqrs.commands.transfer_commands import ValidateTransferCommand

    flow = container.build_skill_opt_flow(
        skill_name="demo", train_tasks=["task-1"], epochs=1, steps_per_epoch=1, batch_size=1
    )

    mediator = flow._mediator
    assert mediator.is_command_registered(ScoreTrajectoryCommand)
    assert mediator.is_command_registered(ApplySkillEditsCommand)
    assert mediator.is_command_registered(ValidateSkillCommand)
    assert mediator.is_command_registered(ValidateTransferCommand)


def test_build_skill_opt_flow_registers_harness_edit_handler(container: Container) -> None:
    """ApplyHarnessEditsCommand is registered once harness_optimization_target
    is resolvable — it was never registered with any mediator before."""
    from weebot.application.cqrs.commands.harness_edit_commands import ApplyHarnessEditsCommand

    flow = container.build_skill_opt_flow(
        skill_name="demo", train_tasks=["task-1"], epochs=1, steps_per_epoch=1, batch_size=1
    )

    assert flow._mediator.is_command_registered(ApplyHarnessEditsCommand)


def test_trajectory_builder_registered_as_instance_not_factory(container: Container) -> None:
    """trajectory_builder must be registered via register_instance(), not
    register(). register() treats the stored value as a zero-arg factory and
    calls it — a plain TrajectoryBuilder instance is not callable, so a
    register()-registered instance raises TypeError on the next .get()."""
    from weebot.application.services.trajectory_builder import TrajectoryBuilder

    container.build_skill_opt_flow(
        skill_name="demo", train_tasks=["task-1"], epochs=1, steps_per_epoch=1, batch_size=1
    )

    resolved = container.get("trajectory_builder")
    assert isinstance(resolved, TrajectoryBuilder)
