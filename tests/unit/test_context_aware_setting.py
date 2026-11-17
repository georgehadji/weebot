"""WEEBOT_CONTEXT_AWARE_MODEL_SELECTION is the default of PlanActFlowConfig's switch."""

from types import SimpleNamespace

import pytest

from weebot.application.models.plan_act_flow_config import PlanActFlowConfig
from weebot.config.settings import WeebotSettings


def _config(**kw) -> PlanActFlowConfig:
    return PlanActFlowConfig(llm=None, tools=None, session=None, **kw)  # type: ignore[arg-type]


def test_setting_defaults_on():
    assert WeebotSettings().context_aware_model_selection is True


@pytest.mark.parametrize("value", [True, False])
def test_flow_config_takes_its_default_from_the_setting(monkeypatch, value):
    monkeypatch.setattr(
        "weebot.config.settings.get_settings",
        lambda: SimpleNamespace(context_aware_model_selection=value),
    )
    assert _config().context_aware_model_selection is value


def test_explicit_value_beats_the_setting(monkeypatch):
    monkeypatch.setattr(
        "weebot.config.settings.get_settings",
        lambda: SimpleNamespace(context_aware_model_selection=False),
    )
    assert _config(context_aware_model_selection=True).context_aware_model_selection is True


def test_env_var_turns_it_off(monkeypatch):
    monkeypatch.setenv("WEEBOT_CONTEXT_AWARE_MODEL_SELECTION", "false")
    assert WeebotSettings().context_aware_model_selection is False
