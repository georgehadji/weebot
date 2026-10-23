"""Every provider key name the adapters accept, settings accept (audit row 11).

`adapter_factory._SETTINGS_FIELD_MAP` maps env names to settings fields for the
direct-API key lookup; `settings._PROVIDER_KEYS` drives the start-up key check.
`MOONSHOT_API_KEY` was in the first only: with it as the only key, the Kimi
adapter worked and `validate_at_least_one_key` refused to start.
"""

from __future__ import annotations

import pytest

from weebot.config.settings import _PROVIDER_KEYS, WeebotSettings
from weebot.infrastructure.adapters.llm.adapter_factory import _SETTINGS_FIELD_MAP


@pytest.mark.parametrize(("env", "field"), sorted(_SETTINGS_FIELD_MAP.items()))
def test_each_adapter_key_name_reaches_its_settings_field(monkeypatch, env, field):
    for name in _SETTINGS_FIELD_MAP:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(env, "k-test")
    assert getattr(WeebotSettings(_env_file=None), field) == "k-test"


def test_both_tables_name_the_same_fields():
    assert set(_SETTINGS_FIELD_MAP.values()) == set(_PROVIDER_KEYS.values())
