"""Tests for Phase 5: TaskPreset and preset registry."""
import pytest

from weebot.domain.models.task_preset import TaskPreset
from weebot.config.task_preset_registry import (
    get_preset,
    register_preset,
    PRESET_SIMPLE,
    PRESET_STANDARD,
    PRESET_COMPLEX,
)


def test_simple_preset_values():
    """PRESET_SIMPLE has expected defaults."""
    assert PRESET_SIMPLE.name == "simple"
    assert PRESET_SIMPLE.enable_premortem is False
    assert PRESET_SIMPLE.enable_step_validation is False
    assert PRESET_SIMPLE.max_steps == 10


def test_standard_preset_values():
    """PRESET_STANDARD is the default."""
    assert PRESET_STANDARD.name == "standard"
    assert PRESET_STANDARD.enable_premortem is False
    assert PRESET_STANDARD.enable_step_validation is True
    assert PRESET_STANDARD.max_steps is None


def test_complex_preset_values():
    """PRESET_COMPLEX has pre-mortem enabled."""
    assert PRESET_COMPLEX.name == "complex"
    assert PRESET_COMPLEX.enable_premortem is True
    assert PRESET_COMPLEX.critique_warn_threshold == 0.85


def test_get_preset_by_name():
    """get_preset('complex') returns the complex preset."""
    preset = get_preset("complex")
    assert preset.name == "complex"
    assert preset.enable_premortem is True


def test_get_preset_falls_back_to_standard():
    """Unknown preset name returns PRESET_STANDARD."""
    preset = get_preset("nonexistent")
    assert preset.name == "standard"


def test_get_preset_empty_string():
    """Empty string returns PRESET_STANDARD."""
    preset = get_preset("")
    assert preset.name == "standard"


def test_register_custom_preset():
    """register_preset adds a custom preset."""
    custom = TaskPreset(
        name="custom",
        enable_premortem=True,
        max_steps=5,
    )
    register_preset(custom)
    retrieved = get_preset("custom")
    assert retrieved.name == "custom"
    assert retrieved.max_steps == 5


def test_preset_is_frozen():
    """TaskPreset is a frozen dataclass — can't modify fields."""
    with pytest.raises(Exception):
        PRESET_STANDARD.name = "changed"


def test_role_model_overrides_default():
    """role_model_overrides defaults to empty dict."""
    preset = TaskPreset(name="test")
    assert preset.role_model_overrides == {}


def test_preset_notes_default():
    """notes defaults to empty string."""
    preset = TaskPreset(name="test")
    assert preset.notes == ""
