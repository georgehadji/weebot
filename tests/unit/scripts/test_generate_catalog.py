"""Proof tests for scripts/generate_catalog.py — the OpenRouter catalog generator.

The generator had no tests. That mattered more than it usually would, because a
run of it *replaces* ``_catalog.py`` wholesale: every way it can be wrong is a
way to lose the catalog. These tests pin the interlocks that stand in the way,
and one property of the shipped catalog itself.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load_generator():
    """Import the generator by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location(
        "generate_catalog", PROJECT_ROOT / "scripts" / "generate_catalog.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gc = _load_generator()


def _model(model_id: str, prompt: str = "0.000001", completion: str = "0.000002") -> dict:
    return {
        "id": model_id,
        "name": model_id,
        "context_length": 128000,
        "pricing": {"prompt": prompt, "completion": completion},
        "architecture": {"modality": "text->text"},
    }


def _payload(n: int = 60) -> list[dict]:
    """A plausible payload, comfortably above MIN_PLAUSIBLE_MODELS."""
    return [_model(f"vendor/model-{i}") for i in range(n)]


# ── Interlock 1: the payload must be plausible ───────────────────────────────


def test_empty_payload_is_refused():
    """The fail-open that mattered: a 200 with no models rendered an empty
    catalog, and --write installed it over the real one."""
    with pytest.raises(gc.PayloadError, match="empty"):
        gc.generate_catalog([])


def test_implausibly_small_payload_is_refused():
    with pytest.raises(gc.PayloadError, match="plausibility floor"):
        gc.generate_catalog([_model(f"vendor/m-{i}") for i in range(3)])


def test_entries_without_an_id_are_refused():
    payload = _payload()
    payload[7] = {"name": "nameless", "pricing": {}}
    with pytest.raises(gc.PayloadError, match="no 'id'"):
        gc.generate_catalog(payload)


def test_a_bare_list_payload_is_accepted(tmp_path: Path):
    """--from-file should take either the API envelope or a bare list, so a
    payload saved by hand works without reshaping."""
    f = tmp_path / "models.json"
    f.write_text(json.dumps(_payload()), encoding="utf-8")
    assert len(gc.fetch_models(f)) == 60

    f.write_text(json.dumps({"data": _payload()}), encoding="utf-8")
    assert len(gc.fetch_models(f)) == 60


# ── Interlock 2: variable pricing never becomes a negative rate ──────────────


def test_openrouter_variable_pricing_is_detected():
    """OpenRouter marks routing-time pricing as -1."""
    assert gc.is_variable_pricing({"prompt": "-1", "completion": "-1"}) is True
    assert gc.is_variable_pricing({"prompt": "0", "completion": "0"}) is False
    assert gc.is_variable_pricing({"prompt": "0.000003", "completion": "0.000015"}) is False


def test_variable_priced_models_are_left_out_rather_than_mispriced():
    """The concrete defect: -1 * 1000 = -1000.0 was stored as a real rate, and
    because _strategies.py *subtracts* cost, a negative one adds score."""
    payload = _payload()
    payload.append(_model("openrouter/auto", prompt="-1", completion="-1"))
    out = gc.generate_catalog(payload)
    assert "openrouter/auto" not in out
    assert "cost_per_1k_tokens=-" not in out


def test_no_generated_entry_can_carry_a_negative_cost():
    payload = _payload()
    payload.append(_model("vendor/weird", prompt="-0.5", completion="-0.5"))
    out = gc.generate_catalog(payload)
    assert "cost_per_1k_tokens=-" not in out


# ── Interlock 3: the rendered file must import ───────────────────────────────


def test_rendered_catalog_imports_and_counts(monkeypatch):
    monkeypatch.setattr(gc, "load_overrides", lambda: ({}, {}, set()))
    out = gc.generate_catalog(_payload())
    assert gc.verify_rendered(out) == 60


def test_rendered_catalog_includes_the_real_overrides():
    """generate_catalog always merges _catalog_overrides.py -- that is the
    whole point of it, so the count is payload + hand-maintained extras."""
    extra, _, suppressed = gc.load_overrides()
    payload = _payload()
    expected = 60 + len([m for m in extra if m not in suppressed])
    assert gc.verify_rendered(gc.generate_catalog(payload)) == expected


def test_unimportable_output_is_refused():
    with pytest.raises(gc.PayloadError, match="does not import"):
        gc.verify_rendered("this is not python(")


def _full_override(**overrides) -> dict:
    base = {
        "name": "X",
        "provider": "openrouter",
        "cost_per_1k_tokens": 0.001,
        "context_window": 1000,
        "strengths": ["CHAT"],
        "tier": "STANDARD",
        "api_key_env": "OPENROUTER_API_KEY",
        "tool_use_score": 5,
    }
    base.update(overrides)
    return base


def test_unknown_task_type_in_an_override_fails_loudly(monkeypatch):
    monkeypatch.setattr(
        gc,
        "load_overrides",
        lambda: ({"vendor/x": _full_override(strengths=["NOT_A_TASK_TYPE"])}, {}, set()),
    )
    with pytest.raises(gc.PayloadError, match="unknown TaskType"):
        gc.generate_catalog(_payload())


def test_unknown_tier_in_an_override_fails_loudly(monkeypatch):
    monkeypatch.setattr(
        gc, "load_overrides", lambda: ({"vendor/x": _full_override(tier="GOLD")}, {}, set())
    )
    with pytest.raises(gc.PayloadError, match="unknown ModelTier"):
        gc.generate_catalog(_payload())


def test_an_override_missing_a_required_field_names_the_field(monkeypatch):
    """A partial override used to reach the renderer and die on a KeyError."""
    partial = _full_override()
    del partial["context_window"]
    monkeypatch.setattr(gc, "load_overrides", lambda: ({"vendor/x": partial}, {}, set()))
    with pytest.raises(gc.PayloadError, match="missing.*context_window"):
        gc.generate_catalog(_payload())


# ── Overrides: hand-maintained knowledge survives a regeneration ─────────────


def test_extra_models_are_added_to_the_output(monkeypatch):
    extra = {"vendor/hand-added": _full_override(name="Hand Added")}
    monkeypatch.setattr(gc, "load_overrides", lambda: (extra, {}, set()))
    out = gc.generate_catalog(_payload())
    assert '"vendor/hand-added"' in out


def test_suppressed_models_stay_out_even_when_the_api_lists_them(monkeypatch):
    """A deliberate removal is a decision; without this the next regeneration
    silently undoes it."""
    monkeypatch.setattr(gc, "load_overrides", lambda: ({}, {}, {"vendor/model-0"}))
    out = gc.generate_catalog(_payload())
    assert '"vendor/model-0"' not in out
    assert '"vendor/model-1"' in out


def test_suppression_beats_an_extra_entry_for_the_same_id(monkeypatch):
    extra = {"vendor/model-0": _full_override()}
    monkeypatch.setattr(gc, "load_overrides", lambda: (extra, {}, {"vendor/model-0"}))
    assert '"vendor/model-0"' not in gc.generate_catalog(_payload())


def test_pinned_fields_override_the_derived_values(monkeypatch):
    monkeypatch.setattr(
        gc,
        "load_overrides",
        lambda: ({}, {"vendor/model-0": {"tier": "PREMIUM", "tool_use_score": 9}}, set()),
    )
    out = gc.generate_catalog(_payload())
    block = out[out.index('"vendor/model-0"') : out.index('"vendor/model-1"')]
    assert "ModelTier.PREMIUM" in block
    assert "tool_use_score=9" in block


def test_the_shipped_overrides_file_loads_and_is_well_formed():
    extra, pinned, suppressed = gc.load_overrides()
    assert isinstance(extra, dict) and isinstance(pinned, dict) and isinstance(suppressed, set)
    # openrouter/auto is declared FORBIDDEN in model_refs.py's docstring.
    assert "openrouter/auto" in suppressed


# ── Cost model: the choice is explicit, and recorded ─────────────────────────


def test_cost_model_max_is_the_default_and_never_underestimates():
    pricing = {"prompt": "0.000003", "completion": "0.000015"}
    assert gc.pricing_to_cost(pricing) == pytest.approx(0.015)
    assert gc.pricing_to_cost(pricing, "max") == pytest.approx(0.015)


def test_cost_model_mean_matches_the_hand_maintained_convention():
    """_catalog_overrides.py records $0.03/1M in + $0.13/1M out as 0.00008 --
    the mean of the two per-1k rates, not the max."""
    assert gc.pricing_to_cost({"prompt": "0.00000003", "completion": "0.00000013"}, "mean") == (
        pytest.approx(0.00008)
    )


def test_the_chosen_cost_model_is_recorded_in_the_generated_header():
    assert "Cost model: mean(prompt, completion)" in gc.generate_catalog(_payload(), "mean")
    assert "Cost model: max(prompt, completion)" in gc.generate_catalog(_payload(), "max")


def test_malformed_pricing_degrades_to_zero_rather_than_raising():
    assert gc.pricing_to_cost({"prompt": "not-a-number"}) == 0.0
    assert gc.pricing_to_cost({}) == 0.0


# ── Derived fields ───────────────────────────────────────────────────────────


def test_strengths_have_no_duplicates():
    """Both branches of determine_strengths could append REASONING."""
    s = gc.determine_strengths("text->text", "deepseek/deep-reasoner")
    assert len(s) == len(set(s))


def test_provider_and_key_mapping_follows_the_prefix_table():
    assert gc.model_id_to_provider("moonshotai/kimi-k3") == "moonshot"
    assert gc.model_id_to_provider("anthropic/claude-sonnet-5") == "openrouter"
    assert gc.model_id_to_provider("unknown-vendor/whatever") == "openrouter"


# ── A property of the catalog that actually ships ────────────────────────────


def test_shipped_catalog_has_no_negative_costs():
    """Regression guard for the four meta-routers priced at -1000.0, which won
    every cost-based selection in _strategies.py, past any budget filter."""
    from weebot.application.services.model_registry._catalog import MODELS

    negative = {k: v.cost_per_1k_tokens for k, v in MODELS.items() if v.cost_per_1k_tokens < 0}
    assert negative == {}


def test_shipped_catalog_header_count_matches_its_contents():
    """The header claimed 343 while the file defined 351."""
    import re

    text = (
        PROJECT_ROOT / "weebot/application/services/model_registry/_catalog.py"
    ).read_text(encoding="utf-8")
    declared = int(re.search(r"Total models: (\d+)", text).group(1))
    actual = len(re.findall(r'^    "[^"]+": ModelConfig\(', text, re.M))
    assert declared == actual


def test_cost_based_selection_does_not_return_a_forbidden_meta_router():
    """model_refs.py's docstring: ``openrouter/auto`` is FORBIDDEN."""
    from weebot.application.services.model_registry._catalog import MODELS
    from weebot.application.services.model_registry._strategies import CostOptimized, Fastest
    from weebot.domain.models.task_type import TaskType

    candidates = list(MODELS.items())
    for strategy in (CostOptimized(), Fastest()):
        for task in (TaskType.CHAT, TaskType.REASONING, TaskType.CODE_GENERATION):
            assert strategy.select(candidates, task) != "openrouter/auto"


def test_a_zero_budget_cannot_select_a_paid_model():
    """A negative cost passed `cost <= budget` for every budget, including 0."""
    from weebot.application.services.model_registry._catalog import MODELS
    from weebot.application.services.model_registry._strategies import CostOptimized
    from weebot.domain.models.task_type import TaskType

    picked = CostOptimized().select(list(MODELS.items()), TaskType.CHAT, budget=0.0)
    assert MODELS[picked].cost_per_1k_tokens == 0.0
