"""Proof tests for scripts/generate_catalog.py — the OpenRouter catalog generator.

The generator had no tests. That mattered more than it usually would, because a
run of it *replaces* ``_catalog.py`` wholesale: every way it can be wrong is a
way to lose the catalog. These tests pin the interlocks that stand in the way,
the install path that the interlocks protect, and the properties of the shipped
catalog they are supposed to guarantee.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load_generator():
    """Import the generator by path (scripts/ is not a package).

    The generator inserts PROJECT_ROOT at the head of ``sys.path`` when it is
    executed. Left in place that would be a collection-time side effect of this
    file on every other test module in the session, so it is undone here.
    """
    before = list(sys.path)
    spec = importlib.util.spec_from_file_location(
        "generate_catalog", PROJECT_ROOT / "scripts" / "generate_catalog.py"
    )
    module = importlib.util.module_from_spec(spec)
    # Registered under its spec name so anything inside it that resolves
    # ``sys.modules[__name__]`` finds a module the interpreter knows about.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = before
    return module


catgen = _load_generator()


def _model(model_id: str, prompt: str = "0.000001", completion: str = "0.000002", **extra) -> dict:
    model = {
        "id": model_id,
        "name": model_id,
        "context_length": 128000,
        "pricing": {"prompt": prompt, "completion": completion},
        "architecture": {"modality": "text->text"},
    }
    model.update(extra)
    return model


def _payload(n: int = 60) -> list[dict]:
    """A plausible payload, comfortably above MIN_PLAUSIBLE_MODELS."""
    return [_model(f"vendor/model-{i}") for i in range(n)]


@pytest.fixture
def no_overrides(monkeypatch):
    """Run the generator with the overrides file out of the picture.

    Without this a test that appends a model the *real* SUPPRESSED_MODELS
    already contains proves nothing: suppression is checked before pricing, so
    the entry never reaches the guard under test.
    """
    monkeypatch.setattr(catgen, "load_overrides", lambda: ({}, {}, set()))


# ── Interlock 1: the payload must be plausible ───────────────────────────────


def test_empty_payload_is_refused():
    """The fail-open that mattered: a 200 with no models rendered an empty
    catalog, and --write installed it over the real one."""
    with pytest.raises(catgen.PayloadError, match="empty"):
        catgen.generate_catalog([])


def test_implausibly_small_payload_is_refused():
    with pytest.raises(catgen.PayloadError, match="plausibility floor"):
        catgen.generate_catalog([_model(f"vendor/m-{i}") for i in range(3)])


def test_the_floor_counts_what_would_be_rendered_not_what_was_received(no_overrides):
    """A payload can pass a raw-count floor and still render almost nothing.

    Filtering happens after the payload is read, so 60 models of which 56 are
    unpriced is a 4-entry catalog. Counting the input would have waved it through.
    """
    payload = _payload(4) + [
        _model(f"vendor/unpriced-{i}", prompt="-1", completion="-1") for i in range(56)
    ]
    with pytest.raises(catgen.PayloadError, match="plausibility floor"):
        catgen.generate_catalog(payload)


def test_entries_without_an_id_are_refused():
    payload = _payload()
    payload[7] = {"name": "nameless", "pricing": {}}
    with pytest.raises(catgen.PayloadError, match="no 'id'"):
        catgen.generate_catalog(payload)


def test_duplicate_ids_are_refused():
    """They collapse last-wins, so the reported count overstates the render."""
    payload = _payload()
    payload.append(_model("vendor/model-0"))
    with pytest.raises(catgen.PayloadError, match="duplicate model id"):
        catgen.generate_catalog(payload)


def test_a_bare_list_payload_is_accepted(tmp_path: Path):
    """--from-file should take either the API envelope or a bare list, so a
    payload saved by hand works without reshaping."""
    f = tmp_path / "models.json"
    f.write_text(json.dumps(_payload()), encoding="utf-8")
    assert len(catgen.fetch_models(f)) == 60

    f.write_text(json.dumps({"data": _payload()}), encoding="utf-8")
    assert len(catgen.fetch_models(f)) == 60


# ── Pricing: an unreadable price is not a price of zero ──────────────────────


def test_openrouter_variable_pricing_is_detected():
    """OpenRouter marks routing-time pricing as -1."""
    assert catgen.is_variable_pricing({"prompt": "-1", "completion": "-1"}) is True
    assert catgen.is_variable_pricing({"prompt": "0", "completion": "0"}) is False
    assert catgen.is_variable_pricing({"prompt": "0.000003", "completion": "0.000015"}) is False


def test_a_negative_price_is_still_found_when_the_other_key_is_unreadable():
    """The guard used to `return False` on the first unparseable key, so a null
    prompt price hid a -1 completion price and the meta-router was admitted --
    at cost 0.0 and tier FAST, which is the top of every cost-based selection."""
    for pricing in (
        {"prompt": None, "completion": "-1"},
        {"prompt": "n/a", "completion": "-1"},
        {"prompt": "", "completion": "-1"},
    ):
        assert catgen.is_unpriced(pricing) is True, pricing
        assert catgen.parse_rates(pricing) is None, pricing


def test_a_model_hiding_a_negative_price_never_reaches_the_catalog(no_overrides):
    payload = _payload()
    payload.append(_model("vendor/sneaky", prompt=None, completion="-1"))
    out = catgen.generate_catalog(payload)
    assert "vendor/sneaky" not in catgen.model_ids(out)


def test_an_unpriced_model_is_excluded_rather_than_recorded_as_free(no_overrides):
    """Models priced per second or per image (OpenRouter returns null, or a
    non-numeric value) collapsed to 0.0 -- and `tier` is derived from cost, so
    they landed as FAST, the top of both CostOptimized and Fastest, and passed a
    budget=0 filter. Zero is the one wrong answer here."""
    payload = _payload()
    payload.append(_model("vendor/per-second", prompt="0.000003", completion=None))
    payload.append(_model("vendor/nonsense", prompt="n/a", completion="n/a"))
    out = catgen.generate_catalog(payload)
    rendered = catgen.model_ids(out)
    assert "vendor/per-second" not in rendered
    assert "vendor/nonsense" not in rendered


def test_pricing_to_cost_refuses_rather_than_inventing_a_zero():
    with pytest.raises(catgen.PayloadError, match="not a per-token rate"):
        catgen.pricing_to_cost({"prompt": "not-a-number", "completion": "0"})
    with pytest.raises(catgen.PayloadError, match="not a per-token rate"):
        catgen.pricing_to_cost({})


def test_a_genuinely_free_model_is_kept(no_overrides):
    """Zero is a real price; only an *unreadable* one is excluded."""
    payload = _payload()
    payload.append(_model("vendor/free", prompt="0", completion="0"))
    out = catgen.generate_catalog(payload)
    assert "vendor/free" in catgen.model_ids(out)


def test_variable_priced_models_are_left_out_rather_than_mispriced(no_overrides):
    """The concrete defect: -1 * 1000 = -1000.0 was stored as a real rate, and
    because _strategies.py *subtracts* cost, a negative one adds score.

    Uses an id the real SUPPRESSED_MODELS does not contain: the earlier version
    of this test used openrouter/auto, which suppression removed before the
    pricing guard ever ran, so it passed with the guard deleted."""
    payload = _payload()
    payload.append(_model("vendor/router", prompt="-1", completion="-1"))
    out = catgen.generate_catalog(payload)
    assert "vendor/router" not in catgen.model_ids(out)
    assert "cost_per_1k_tokens=-" not in out


def test_no_generated_entry_can_carry_a_negative_cost(no_overrides):
    payload = _payload()
    payload.append(_model("vendor/weird", prompt="-0.5", completion="-0.5"))
    assert "cost_per_1k_tokens=-" not in catgen.generate_catalog(payload)


def test_non_finite_prices_are_excluded(no_overrides):
    """inf and nan both pass a `< 0` check; nan renders as a bare NameError."""
    payload = _payload()
    payload.append(_model("vendor/inf", prompt="inf", completion="inf"))
    payload.append(_model("vendor/nan", prompt="nan", completion="nan"))
    rendered = catgen.model_ids(catgen.generate_catalog(payload))
    assert "vendor/inf" not in rendered and "vendor/nan" not in rendered


# ── Interlock 5: nothing from the payload becomes code ───────────────────────


def test_a_crafted_model_name_cannot_execute_code(tmp_path, no_overrides):
    """This is the sharp one. verify_rendered *executes* the rendered text, so
    an unescaped name is not a syntax error -- it is an execution sink, and it
    fires on a plain dry run, before --write is even consulted."""
    marker = tmp_path / "PWNED"
    payload = _payload()
    hostile = 'X" if __import__("pathlib").Path({!r}).write_text("o") else "Y'
    payload[0]["name"] = hostile.format(str(marker))
    catgen.verify_rendered(catgen.generate_catalog(payload))
    assert not marker.exists(), "payload-controlled name executed during verification"


def test_a_quote_in_a_model_name_does_not_break_the_render(no_overrides):
    """One badly-named upstream model used to block the entire refresh."""
    payload = _payload()
    payload[0]["name"] = 'Nous "Hermes" 3 \\ v2'
    out = catgen.generate_catalog(payload)
    assert catgen.verify_rendered(out) == 60


def test_a_model_id_that_would_not_survive_the_round_trip_is_refused():
    """Ids are written into a quoted literal and matched by MODEL_ENTRY_RE
    afterwards; one containing a quote would be rendered but never found again."""
    payload = _payload()
    payload.append(_model('vendor/we"ird'))
    with pytest.raises(catgen.PayloadError, match="will not render"):
        catgen.generate_catalog(payload)


# ── Null-valued fields: present-but-null is not absent ───────────────────────


@pytest.mark.parametrize("field", ["pricing", "architecture", "context_length"])
def test_a_null_field_does_not_crash_the_run(field, no_overrides):
    """`m.get("pricing", {})` returns None when the key is present with a JSON
    null, and the following .get raised an AttributeError that escaped main()'s
    PayloadError handler as a bare traceback."""
    payload = _payload()
    payload[0][field] = None
    out = catgen.generate_catalog(payload)  # must not raise
    assert catgen.verify_rendered(out) >= 59


def test_a_null_context_length_falls_back_rather_than_rendering_none(no_overrides):
    """`context_window=None` imports cleanly and then raises TypeError inside
    QualityOptimized on every selection -- the import probe cannot catch it."""
    payload = _payload()
    payload[0]["context_length"] = None
    out = catgen.generate_catalog(payload)
    assert "context_window=None" not in out


# ── Interlock 3: the rendered file must import ───────────────────────────────


def test_rendered_catalog_imports_and_counts(no_overrides):
    assert catgen.verify_rendered(catgen.generate_catalog(_payload())) == 60


def test_rendered_catalog_includes_the_real_overrides():
    """generate_catalog always merges _catalog_overrides.py -- that is the
    whole point of it, so the count is payload + hand-maintained extras."""
    extra, _, suppressed = catgen.load_overrides()
    expected = 60 + len([m for m in extra if m not in suppressed])
    assert catgen.verify_rendered(catgen.generate_catalog(_payload())) == expected


def test_unimportable_output_is_refused():
    with pytest.raises(catgen.PayloadError, match="does not import"):
        catgen.verify_rendered("this is not python(")


def test_verification_does_not_depend_on_the_installed_catalog(monkeypatch, tmp_path):
    """The probe used to import the package __init__, which imports the *current*
    _catalog -- so a half-written catalog could not be repaired by the tool that
    wrote it, and the error blamed the new content."""
    broken = tmp_path / "_catalog.py"
    broken.write_text("this is not valid python(", encoding="utf-8")
    monkeypatch.setattr(catgen, "CATALOG_PATH", broken)
    monkeypatch.setattr(catgen, "load_overrides", lambda: ({}, {}, set()))
    assert catgen.verify_rendered(catgen.generate_catalog(_payload())) == 60


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
        catgen,
        "load_overrides",
        lambda: ({"vendor/x": _full_override(strengths=["NOT_A_TASK_TYPE"])}, {}, set()),
    )
    with pytest.raises(catgen.PayloadError, match="unknown TaskType"):
        catgen.generate_catalog(_payload())


def test_unknown_tier_in_an_override_fails_loudly(monkeypatch):
    monkeypatch.setattr(
        catgen, "load_overrides", lambda: ({"vendor/x": _full_override(tier="GOLD")}, {}, set())
    )
    with pytest.raises(catgen.PayloadError, match="unknown ModelTier"):
        catgen.generate_catalog(_payload())


def test_an_override_missing_a_required_field_names_the_field(monkeypatch):
    """A partial override used to reach the renderer and die on a KeyError."""
    partial = _full_override()
    del partial["context_window"]
    monkeypatch.setattr(catgen, "load_overrides", lambda: ({"vendor/x": partial}, {}, set()))
    with pytest.raises(catgen.PayloadError, match="missing.*context_window"):
        catgen.generate_catalog(_payload())


def test_a_misspelled_override_key_is_refused_rather_than_dropped(monkeypatch):
    """PINNED_FIELDS is where a hand-measured value lives. Silently discarding a
    typo'd key loses exactly the knowledge the file exists to keep."""
    monkeypatch.setattr(
        catgen, "load_overrides", lambda: ({}, {"vendor/model-0": {"teir": "PREMIUM"}}, set())
    )
    with pytest.raises(catgen.PayloadError, match="unknown field"):
        catgen.generate_catalog(_payload())


def test_optional_fields_may_be_omitted_from_an_override(monkeypatch):
    """tool_use_score has a dataclass default, so requiring it rejected a
    perfectly valid minimal override."""
    minimal = _full_override()
    del minimal["tool_use_score"]
    monkeypatch.setattr(catgen, "load_overrides", lambda: ({"vendor/x": minimal}, {}, set()))
    assert '"vendor/x"' in catgen.generate_catalog(_payload())


@pytest.mark.parametrize(
    "bad,match",
    [
        ({"cost_per_1k_tokens": "0.001"}, "must be a number"),
        ({"context_window": None}, "must be an int"),
        ({"context_window": 0}, "must be positive"),
        ({"name": ""}, "non-empty string"),
    ],
)
def test_override_field_types_are_checked(bad, match, monkeypatch):
    monkeypatch.setattr(
        catgen, "load_overrides", lambda: ({"vendor/x": _full_override(**bad)}, {}, set())
    )
    with pytest.raises(catgen.PayloadError, match=match):
        catgen.generate_catalog(_payload())


# ── Overrides: hand-maintained knowledge survives a regeneration ─────────────


def test_extra_models_are_added_to_the_output(monkeypatch):
    extra = {"vendor/hand-added": _full_override(name="Hand Added")}
    monkeypatch.setattr(catgen, "load_overrides", lambda: (extra, {}, set()))
    assert '"vendor/hand-added"' in catgen.generate_catalog(_payload())


def test_suppressed_models_stay_out_even_when_the_api_lists_them(monkeypatch):
    """A deliberate removal is a decision; without this the next regeneration
    silently undoes it."""
    monkeypatch.setattr(catgen, "load_overrides", lambda: ({}, {}, {"vendor/model-0"}))
    out = catgen.generate_catalog(_payload())
    assert '"vendor/model-0"' not in out
    assert '"vendor/model-1"' in out


def test_suppression_beats_an_extra_entry_for_the_same_id(monkeypatch):
    extra = {"vendor/model-0": _full_override()}
    monkeypatch.setattr(catgen, "load_overrides", lambda: (extra, {}, {"vendor/model-0"}))
    assert '"vendor/model-0"' not in catgen.generate_catalog(_payload())


def test_pinned_fields_override_the_derived_values(monkeypatch):
    monkeypatch.setattr(
        catgen,
        "load_overrides",
        lambda: ({}, {"vendor/model-0": {"tier": "PREMIUM", "tool_use_score": 9}}, set()),
    )
    out = catgen.generate_catalog(_payload())
    block = out[out.index('"vendor/model-0"') : out.index('"vendor/model-1"')]
    assert "ModelTier.PREMIUM" in block
    assert "tool_use_score=9" in block


def test_a_pin_applies_to_a_hand_added_model_too(monkeypatch):
    """Pins ran before extras were merged, and skipped ids not yet in `entries`,
    so a correction to a hand-added model was a silent no-op -- the reverse of
    the order _catalog_overrides.py documents."""
    extra = {"vendor/hand-added": _full_override(tier="STANDARD", tool_use_score=5)}
    pinned = {"vendor/hand-added": {"tier": "PREMIUM", "tool_use_score": 9}}
    monkeypatch.setattr(catgen, "load_overrides", lambda: (extra, pinned, set()))
    out = catgen.generate_catalog(_payload())
    block = out[out.index('"vendor/hand-added"') :]
    block = block[: block.index("),")]
    assert "ModelTier.PREMIUM" in block
    assert "tool_use_score=9" in block


def test_a_pin_that_matches_nothing_is_reported(monkeypatch, capsys):
    """Not fatal -- OpenRouter may have dropped the model temporarily -- but a
    correction that looks applied and is not must not be silent."""
    monkeypatch.setattr(
        catgen, "load_overrides", lambda: ({}, {"vendor/typo": {"tier": "PREMIUM"}}, set())
    )
    catgen.generate_catalog(_payload())
    assert "matched nothing" in capsys.readouterr().err


def test_extra_models_do_not_alias_the_module_level_lists(monkeypatch):
    """setdefault stored the override dict's own `strengths` list object."""
    extra = {"vendor/hand-added": _full_override()}
    monkeypatch.setattr(catgen, "load_overrides", lambda: (extra, {}, set()))
    entries = catgen.build_entries(_payload(), "max")
    assert entries["vendor/hand-added"]["strengths"] is not extra["vendor/hand-added"]["strengths"]


# ── The shipped overrides file, not a synthetic stand-in ─────────────────────


def test_the_shipped_overrides_file_loads_and_is_well_formed():
    extra, pinned, suppressed = catgen.load_overrides()
    assert isinstance(extra, dict) and isinstance(pinned, dict) and isinstance(suppressed, set)
    # openrouter/auto is declared FORBIDDEN in model_refs.py's docstring.
    assert "openrouter/auto" in suppressed


def test_the_shipped_overrides_pass_the_real_validator():
    """Only isinstance() was checked before, so a bad tier or TaskType in the
    shipped file stayed green until someone ran --write."""
    extra, _, _ = catgen.load_overrides()
    catgen.validate_entries({**{f"filler/{i}": _full_override() for i in range(60)}, **extra})


def _live(model_id: str, key: str):
    from weebot.application.services.model_registry._catalog import MODELS

    value = getattr(MODELS[model_id], key)
    if key == "strengths":
        return [t.name for t in value]
    if key == "tier":
        return value.name
    return value


def test_every_pinned_field_survives_into_the_shipped_catalog():
    """PINNED_FIELDS is the mechanism that keeps hand-measured values alive once
    OpenRouter starts listing a model -- ``EXTRA_MODELS`` merges with
    ``setdefault``, so without a pin the payload silently wins.

    This is the invariant that matters now that the API supplies 18 of the 19
    hand-maintained entries: the fields nobody can derive (AGENTIC strengths, a
    PREMIUM tier, a measured tool_use_score) must be what the file says.
    """
    from weebot.application.services.model_registry._catalog import MODELS

    _, pinned, _ = catgen.load_overrides()
    assert pinned, "no pins to check -- has the overrides file been emptied?"
    mismatched = {
        f"{model_id}.{key}": (expected, _live(model_id, key))
        for model_id, fields in pinned.items()
        if model_id in MODELS
        for key, expected in fields.items()
        if _live(model_id, key) != expected
    }
    assert mismatched == {}


# ── Cost model: the choice is explicit, and recorded ─────────────────────────


def test_cost_model_max_is_the_default_and_never_underestimates():
    pricing = {"prompt": "0.000003", "completion": "0.000015"}
    assert catgen.pricing_to_cost(pricing) == pytest.approx(0.015)
    assert catgen.pricing_to_cost(pricing, "max") == pytest.approx(0.015)


def test_cost_model_mean_matches_the_hand_maintained_convention():
    """_catalog_overrides.py records $0.03/1M in + $0.13/1M out as 0.00008 --
    the mean of the two per-1k rates, not the max."""
    assert catgen.pricing_to_cost({"prompt": "0.00000003", "completion": "0.00000013"}, "mean") == (
        pytest.approx(0.00008)
    )


def test_the_chosen_cost_model_is_recorded_in_the_generated_header():
    assert "Cost model: mean(prompt, completion)" in catgen.generate_catalog(_payload(), "mean")
    assert "Cost model: max(prompt, completion)" in catgen.generate_catalog(_payload(), "max")


# ── Derived fields ───────────────────────────────────────────────────────────


def test_strengths_have_no_duplicates():
    """Both branches of determine_strengths could append REASONING."""
    s = catgen.determine_strengths("text->text", "deepseek/deep-reasoner")
    assert len(s) == len(set(s))


def test_provider_and_key_mapping_follows_the_prefix_table():
    assert catgen.model_id_to_provider("moonshotai/kimi-k3") == "moonshot"
    assert catgen.model_id_to_provider("anthropic/claude-sonnet-5") == "openrouter"
    assert catgen.model_id_to_provider("unknown-vendor/whatever") == "openrouter"


# ── Interlock 4 and the install path (main()) ────────────────────────────────


@pytest.fixture
def catalog_at(tmp_path, monkeypatch):
    """Point the generator at a throwaway catalog and return its path."""
    path = tmp_path / "_catalog.py"
    monkeypatch.setattr(catgen, "CATALOG_PATH", path)
    return path


def _run(monkeypatch, tmp_path, argv: list[str], payload=None) -> int:
    src = tmp_path / "payload.json"
    src.write_text(json.dumps({"data": payload or _payload()}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["generate_catalog.py", "--from-file", str(src), *argv])
    return catgen.main()


def test_a_write_installs_a_catalog_that_imports(monkeypatch, tmp_path, catalog_at, no_overrides):
    assert _run(monkeypatch, tmp_path, ["--write", "--bootstrap"]) == 0
    assert catgen.verify_rendered(catalog_at.read_text(encoding="utf-8")) == 60


def test_a_dry_run_writes_nothing(monkeypatch, tmp_path, catalog_at, no_overrides):
    assert _run(monkeypatch, tmp_path, []) == 0
    assert not catalog_at.exists()


def test_a_large_shrink_is_refused_on_write(monkeypatch, tmp_path, catalog_at, no_overrides):
    assert _run(monkeypatch, tmp_path, ["--write", "--bootstrap"], payload=_payload(300)) == 0
    before = catalog_at.read_text(encoding="utf-8")
    assert _run(monkeypatch, tmp_path, ["--write"], payload=_payload(60)) == 3
    assert catalog_at.read_text(encoding="utf-8") == before, "refused write still replaced the file"


def test_a_shrink_that_would_be_refused_does_not_fail_a_dry_run(
    monkeypatch, tmp_path, catalog_at, no_overrides, capsys
):
    """The guard ran before the --write check, so previewing a large delta --
    the documented reason to do a dry run -- exited 3."""
    _run(monkeypatch, tmp_path, ["--write", "--bootstrap"], payload=_payload(300))
    assert _run(monkeypatch, tmp_path, [], payload=_payload(60)) == 0
    assert "would be refused" in capsys.readouterr().out


def test_an_explicit_max_shrink_allows_it(monkeypatch, tmp_path, catalog_at, no_overrides):
    _run(monkeypatch, tmp_path, ["--write", "--bootstrap"], payload=_payload(300))
    assert _run(monkeypatch, tmp_path, ["--write", "--max-shrink", "0.9"], _payload(60)) == 0


def test_no_baseline_refuses_the_write_rather_than_waving_it_through(
    monkeypatch, tmp_path, catalog_at, no_overrides
):
    """`if old_count and ...` failed open: with no readable catalog the shrink
    guard was skipped entirely, silently, exactly when there is most to lose."""
    assert not catalog_at.exists()
    assert _run(monkeypatch, tmp_path, ["--write"]) == 3
    assert not catalog_at.exists()


def test_bootstrap_is_how_you_say_you_meant_it(monkeypatch, tmp_path, catalog_at, no_overrides):
    assert _run(monkeypatch, tmp_path, ["--write", "--bootstrap"]) == 0
    assert catalog_at.exists()


def test_an_unreadable_catalog_is_not_treated_as_an_empty_one(
    monkeypatch, tmp_path, catalog_at, no_overrides
):
    """A format drift that stops MODEL_ENTRY_RE matching must not read as
    'zero models, nothing to lose'."""
    catalog_at.write_text("MODELS = {}  # nothing MODEL_ENTRY_RE can find\n", encoding="utf-8")
    assert catgen.current_model_ids() is None
    assert _run(monkeypatch, tmp_path, ["--write"]) == 3


def test_save_payload_failure_is_reported_not_raised(monkeypatch, tmp_path, catalog_at):
    """On the live path the fetched payload exists only in memory, and may not be
    fetchable again from this machine."""
    dest = tmp_path / "no" / "such" / "p.json"
    assert _run(monkeypatch, tmp_path, ["--save-payload", str(dest)]) == 1


def test_the_diff_needs_no_external_binary(monkeypatch, tmp_path, catalog_at, no_overrides, capsys):
    _run(monkeypatch, tmp_path, ["--write", "--bootstrap"])
    _run(monkeypatch, tmp_path, ["--write", "--diff"], payload=_payload(61))
    assert "=== Diff ===" in capsys.readouterr().out


# ── Properties of the catalog that actually ships ────────────────────────────


def _catalog_text() -> str:
    return (PROJECT_ROOT / "weebot/application/services/model_registry/_catalog.py").read_text(
        encoding="utf-8"
    )


def test_shipped_catalog_has_no_negative_costs():
    """Regression guard for the four meta-routers priced at -1000.0, which won
    every cost-based selection in _strategies.py, past any budget filter."""
    from weebot.application.services.model_registry._catalog import MODELS

    assert {k: v.cost_per_1k_tokens for k, v in MODELS.items() if v.cost_per_1k_tokens < 0} == {}


def test_shipped_catalog_header_count_matches_its_contents():
    """The header claimed 343 while the file defined 351."""
    text = _catalog_text()
    declared = int(re.search(r"Total models: (\d+)", text).group(1))
    assert declared == len(catgen.model_ids(text))


def test_shipped_catalog_header_has_the_shape_the_generator_emits():
    """The count test alone cannot see a header the generator would not produce
    -- which is how a hand-edited file kept passing as generated output."""
    assert re.search(r"Cost model: (max|mean)\(prompt, completion\)", _catalog_text())


def test_shipped_catalog_has_no_duplicate_strengths():
    """The dedup fix landed in determine_strengths; 28 shipped entries predated
    it, so the property the generator test asserts was untrue of the artifact."""
    from weebot.application.services.model_registry._catalog import MODELS

    assert [k for k, v in MODELS.items() if len(v.strengths) != len(set(v.strengths))] == []


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


FIXTURE = PROJECT_ROOT / "tests/fixtures/openrouter_models.json"


def test_the_shipped_catalog_is_exactly_what_the_recorded_payload_renders():
    """The banner says DO NOT EDIT MANUALLY. This is what makes that true.

    Every earlier guard was advisory: the file carried the banner through five
    commits of hand-editing while its header count sat frozen at 343 and the
    real count ran 343 -> 349 -> 343 -> 345 -> 351.

    Rendering the recorded OpenRouter payload and comparing the whole file is a
    *provenance* check, not merely a format one: every value in the catalog must
    be derivable from that payload plus _catalog_overrides.py. A cost edited by
    hand fails here even though it is perfectly well-formed, which reconstructing
    the entries from the file itself could never catch.

    When the catalog is refreshed, the fixture is refreshed in the same commit --
    that is the point. A diff to one without the other fails.
    """
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]
    assert catgen.generate_catalog(payload, "max") == _catalog_text()


def test_the_fixture_carries_only_the_fields_the_generator_reads():
    """It is a test fixture, not an API archive: everything else is weight.

    ``pricing`` is kept whole so the caching and web-search rates ride along for
    whenever they are wired up.
    """
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]
    allowed = {"id", "name", "context_length", "pricing", "architecture"}
    assert {k for m in payload for k in m} <= allowed


def test_a_dry_run_still_verifies_that_the_output_imports(
    monkeypatch, tmp_path, catalog_at, no_overrides, capsys
):
    """Telling you whether the render actually imports is most of what a dry run
    is for. The check sits below the shrink gate so a run that is going to be
    refused does not pay for a subprocess first."""
    catalog_at.write_text(catgen.render_catalog({}, "max"), encoding="utf-8")
    assert _run(monkeypatch, tmp_path, ["--bootstrap"]) == 0
    assert "Rendered and imported cleanly: 60 models" in capsys.readouterr().out
