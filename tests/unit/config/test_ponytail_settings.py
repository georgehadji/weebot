"""Unit tests for Ponytail-related WeebotSettings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from weebot.config.settings import WeebotSettings


def test_ponytail_mode_defaults_to_off() -> None:
    """Ponytail mode defaults to 'off'."""
    settings = WeebotSettings()
    assert settings.ponytail_mode == "off"


@pytest.mark.parametrize("mode", ["off", "lite", "full", "ultra"])
def test_ponytail_mode_valid_values(mode: str) -> None:
    """All valid Ponytail modes are accepted and normalized."""
    settings = WeebotSettings(ponytail_mode=mode)
    assert settings.ponytail_mode == mode

    settings_upper = WeebotSettings(ponytail_mode=mode.upper())
    assert settings_upper.ponytail_mode == mode


@pytest.mark.parametrize("mode", ["", "medium", "ON", "yes", "true"])
def test_ponytail_mode_invalid_values(mode: str) -> None:
    """Invalid Ponytail modes raise ValidationError."""
    with pytest.raises(ValidationError):
        WeebotSettings(ponytail_mode=mode)
