#!/usr/bin/env python3
"""generate_catalog.py — regenerate _catalog.py from OpenRouter's model list.

Usage:
    python scripts/generate_catalog.py                      # dry-run: stats + planned delta
    python scripts/generate_catalog.py --write              # verify, then replace the catalog
    python scripts/generate_catalog.py --write --diff       # ... and print the diff
    python scripts/generate_catalog.py --from-file m.json   # use a saved API payload
    python scripts/generate_catalog.py --save-payload m.json # keep the fetched payload

Safety
------
A regeneration *replaces* the catalog, so every failure mode of this script is a
data-loss failure mode. Five interlocks stand between a bad run and the file:

1. **The payload must be plausible.** An empty or malformed ``data`` array is
   rejected rather than rendered. Before this existed, a 200 response carrying
   no models produced a valid, empty catalog and ``--write`` installed it. The
   floor is applied to what will actually be *rendered*, not to the raw list:
   filtering happens after the payload is read, so counting the input would let
   60 models become 5 entries without tripping anything.
2. **Hand-maintained knowledge survives.** ``_catalog_overrides.py`` carries the
   models the API does not list, the fields it gets wrong, and the models
   deliberately dropped. Without it a regeneration silently deleted every
   hand-added entry and resurrected every hand-removed one.
3. **The output must import.** The rendered file is checked by importing it in a
   subprocess before it is allowed to replace the real one -- and again after
   the write, against the file that actually landed on disk.
4. **A large shrink must be asked for.** Losing more than ``--max-shrink`` of the
   current entries fails unless the caller says so explicitly. When the current
   catalog cannot be read at all the guard has no baseline, so it refuses rather
   than waving the write through; ``--bootstrap`` is the way to say that writing
   without a baseline is what you meant.
5. **Nothing from the payload becomes code.** Every interpolated value is
   rendered with ``json.dumps``, and model ids are checked against a
   conservative pattern. This matters more than it looks: interlock 3 *executes*
   the rendered text, so an unescaped model name is not a syntax error but an
   execution sink.

Pricing
-------
A price that cannot be read as a per-token number is not a price of zero.
OpenRouter marks routing-time pricing with ``-1``, prices some models per
second or per image, and can return ``null``. Any of those collapsed to ``0.0``
lands the model in the catalog as *free* -- and ``tier`` is derived from cost,
so it lands as ``FAST`` too, which is the top of both ``CostOptimized`` and
``Fastest`` and passes a ``budget=0`` filter. Such models are therefore left
out of the catalog rather than mispriced into it, and reported when skipped.

Cost model
----------
``ModelConfig`` carries a single ``cost_per_1k_tokens`` while OpenRouter prices
prompt and completion separately, so any single number is wrong for every token
mix but one. Two conventions are already in use in this repo and they disagree:

* this script has always used ``max(prompt, completion)`` -- never
  underestimates, but overstates input-heavy work (a 1M-in/100k-out call on
  $3/$15-per-M pricing is costed at $16.50 against a true $4.50, 3.67x);
* the hand-maintained entries in ``_catalog_overrides.py`` use the *mean* of the
  two rates, which is exact when input and output are balanced.

``--cost-model`` selects one and records the choice in the generated header.
The default stays ``max`` so that regenerating does not silently change routing
or budget behaviour. The real fix is for ``ModelConfig`` to carry both rates;
until then, this flag at least makes the choice visible.

Requires: requests, and only when fetching live -- --from-file needs nothing.
"""
from __future__ import annotations

import argparse
import contextlib
import difflib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import MISSING, fields
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# No load_dotenv here on purpose: this script reads no environment variable --
# PROVIDER_API_KEY maps to variable *names* that get written into the catalog,
# never to their values -- and importing it under pytest would otherwise
# override the test process's environment from whatever .env is on disk.

OPENROUTER_API = "https://openrouter.ai/api/v1/models"

CATALOG_PATH = PROJECT_ROOT / "weebot/application/services/model_registry/_catalog.py"
OVERRIDES_PATH = PROJECT_ROOT / "weebot/application/services/model_registry/_catalog_overrides.py"
MODELS_PATH = PROJECT_ROOT / "weebot/application/services/model_registry/_models.py"
TASK_TYPE_PATH = PROJECT_ROOT / "weebot/domain/models/task_type.py"

# A catalog with fewer models than this is treated as a broken payload rather
# than as OpenRouter having retired 90% of its catalogue overnight. The real
# list has been in the hundreds for the life of this script.
MIN_PLAUSIBLE_MODELS = 50

# The shape of one rendered entry, and the single place that knows it. Both the
# delta report and the post-render id scan use this, so a change to the emitted
# format cannot leave one of them silently matching nothing.
MODEL_ENTRY_RE = re.compile(r'^    "([^"]+)": ModelConfig\(', re.M)

# Model ids are interpolated into a double-quoted literal *and* matched by
# MODEL_ENTRY_RE, so anything outside this set would either break the render or
# make the id unfindable afterwards. OpenRouter ids are `vendor/name` with the
# occasional `:free`, `.`, `-`, `_`, `@` or leading `~`.
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9._~:@+/-]+$")

# ── OpenRouter prefix → weebot provider mapping ──────────────────
# Matches the mapping in adapter_factory.py and _catalog_validator.py
PREFIX_PROVIDER = {
    "x-ai": "xai",
    "deepseek": "deepseek",
    "moonshotai": "moonshot",
    "google": "openrouter",
    "meta-llama": "openrouter",
    "mistralai": "openrouter",
    "openai": "openrouter",
    "anthropic": "openrouter",
    "cohere": "openrouter",
    "z-ai": "openrouter",
    "qwen": "openrouter",
    "minimax": "openrouter",
    "nvidia": "openrouter",
    "nousresearch": "openrouter",
    "poolside": "openrouter",
    "nex-agi": "openrouter",
    "sourceful": "openrouter",
    "black-forest-labs": "openrouter",
    "ideogram": "openrouter",
    "recraft": "openrouter",
    "essentialai": "openrouter",
    "switchpoint": "openrouter",
    "neets": "openrouter",
    "inflection": "openrouter",
}

# ── Provider → api_key_env mapping ───────────────────────────────
PROVIDER_API_KEY = {
    "xai": "OPENROUTER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "moonshot": "KIMI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}

# ── Known tool-use scores (manually maintained) ──────────────────
TOOL_USE_SCORES: dict[str, int] = {
    "x-ai/grok-4.3": 8,
    "deepseek/deepseek-v4-flash": 7,
    "moonshotai/kimi-k2.6": 6,
}


class PayloadError(RuntimeError):
    """The fetched model list is not something we are willing to render."""


def load_overrides() -> tuple[dict, dict, set]:
    """Load _catalog_overrides.py without importing the weebot package."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_catalog_overrides", OVERRIDES_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - unreachable in practice
        raise PayloadError(f"cannot load overrides from {OVERRIDES_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return (
        dict(getattr(mod, "EXTRA_MODELS", {})),
        dict(getattr(mod, "PINNED_FIELDS", {})),
        set(getattr(mod, "SUPPRESSED_MODELS", set())),
    )


def model_id_to_provider(model_id: str) -> str:
    """Map an OpenRouter model ID to a weebot provider name."""
    prefix = model_id.split("/")[0] if "/" in model_id else model_id
    return PREFIX_PROVIDER.get(prefix, "openrouter")


def parse_rates(pricing: dict) -> tuple[float, float] | None:
    """Return (prompt, completion) per-token rates, or None if not token-priced.

    One parse rule for both callers. ``None`` means OpenRouter did not give a
    number we can treat as a per-token price: the key is missing, the value is
    null or non-numeric, or it is not finite. Every such model is excluded --
    see the Pricing note in the module docstring for why zero is the one wrong
    answer here.
    """
    if not isinstance(pricing, dict):
        return None
    rates: list[float] = []
    for key in ("prompt", "completion"):
        if key not in pricing:
            return None
        try:
            value = float(pricing[key])
        except (ValueError, TypeError):
            return None
        if not math.isfinite(value):
            return None
        rates.append(value)
    return rates[0], rates[1]


def is_variable_pricing(pricing: dict) -> bool:
    """True when OpenRouter reports a price it will only resolve at routing time.

    OpenRouter marks its meta-routers -- ``openrouter/auto`` and friends, which
    pick a real model per request -- with a price of ``-1``. Fed through
    ``pricing_to_cost`` that became ``-1000.0`` and was stored as if it were a
    real rate, which is worse than useless: every cost comparison in
    ``_strategies.py`` subtracts the cost, so a negative one *adds* score. Four
    such entries made ``CostOptimized`` and ``Fastest`` return a meta-router for
    any task, past any budget filter, including ``budget=0``.

    A single float cannot express "priced at routing time", so these models are
    left out of the catalog rather than mispriced into it.
    """
    rates = parse_rates(pricing)
    if rates is None:
        return False
    return min(rates) < 0


def is_unpriced(pricing: dict) -> bool:
    """True when the price cannot be read as a per-token rate at all.

    Distinct from ``is_variable_pricing`` only in the reason; both end in the
    model being skipped. Kept separate so the skip report can say which.
    """
    return parse_rates(pricing) is None


def pricing_to_cost(pricing: dict, cost_model: str = "max") -> float:
    """Collapse OpenRouter's per-token prompt/completion prices to one per-1k rate.

    See the cost-model note in the module docstring: this number is a
    compromise, and ``cost_model`` says which one. Callers must have excluded
    unpriced models first -- this raises rather than inventing a zero.
    """
    rates = parse_rates(pricing)
    if rates is None:
        raise PayloadError(f"pricing is not a per-token rate: {pricing!r}")
    prompt_cost, completion_cost = rates

    if cost_model == "mean":
        cost = (prompt_cost + completion_cost) / 2
    else:
        cost = max(prompt_cost, completion_cost)
    # OpenRouter returns per-token prices. We store per-1K-tokens.
    return cost * 1000


def determine_strengths(modality: str, model_id: str) -> list[str]:
    """Derive TaskType strengths, as enum member names, from modality and id.

    Coarse by construction: the API says nothing about task suitability, so this
    is pattern-matching on the model id. Where it is wrong for a model somebody
    has actually measured, correct that model in ``PINNED_FIELDS`` rather than
    adding another rule here. Note that this cannot produce ``AGENTIC`` at all;
    every agentic model in the catalog is there because a human said so.
    """
    strengths = ["CHAT"]

    if "image" in modality or "vision" in modality or "multimodal" in modality:
        strengths.append("CREATIVE")

    if "code" in model_id.lower() or "coder" in model_id.lower():
        strengths.append("CODE_GENERATION")
        strengths.append("DEBUGGING")
    else:
        strengths.append("CODE_REVIEW")
        strengths.append("REASONING")

    if any(kw in model_id.lower() for kw in ("reason", "think", "deep")):
        strengths.append("REASONING")

    strengths.append("DOCUMENTATION")
    strengths.append("ARCHITECTURE")

    # Preserve first-seen order while dropping the duplicate REASONING the two
    # branches above can both append.
    return list(dict.fromkeys(strengths))


def fetch_models(from_file: Path | None = None) -> list[dict]:
    """Return the model list, from a saved payload or from the live API."""
    if from_file is not None:
        raw = json.loads(from_file.read_text(encoding="utf-8"))
    else:
        import requests

        resp = requests.get(OPENROUTER_API, timeout=30)
        resp.raise_for_status()
        raw = resp.json()

    # Accept either the full envelope or a bare list, so a payload saved by
    # hand from the docs or a browser works without reshaping.
    data = raw.get("data", []) if isinstance(raw, dict) else raw
    if not isinstance(data, list):
        raise PayloadError(f"expected a list of models, got {type(data).__name__}")
    return data


def validate_payload(models: list[dict]) -> None:
    """Refuse a payload that is not shaped like a model list."""
    if not models:
        raise PayloadError(
            "the model list is empty. A 200 response carrying no models would "
            "otherwise render an empty catalog and replace the real one."
        )
    missing = [m for m in models if not isinstance(m, dict) or not m.get("id")]
    if missing:
        raise PayloadError(f"{len(missing)} entries have no 'id' field")
    bad_ids = sorted({m["id"] for m in models if not MODEL_ID_RE.match(str(m["id"]))})
    if bad_ids:
        raise PayloadError(
            f"{len(bad_ids)} model id(s) contain characters this generator will not render: "
            f"{bad_ids[:5]}. Ids are written into a quoted literal and matched by "
            f"MODEL_ENTRY_RE afterwards."
        )
    counts = Counter(m["id"] for m in models)
    duplicates = sorted(i for i, n in counts.items() if n > 1)
    if duplicates:
        raise PayloadError(
            f"{len(duplicates)} duplicate model id(s) in the payload: {duplicates[:5]}. "
            f"They would collapse last-wins and the reported count would overstate "
            f"what is rendered."
        )


def build_entries(models: list[dict], cost_model: str) -> dict[str, dict]:
    """Render every model to ModelConfig kwargs, then apply the overrides."""
    extra, pinned, suppressed = load_overrides()
    entries: dict[str, dict] = {}

    variable_priced: list[str] = []
    unpriced: list[str] = []

    for m in models:
        model_id = m.get("id", "")
        if model_id in suppressed:
            continue
        pricing = m.get("pricing") or {}
        if is_variable_pricing(pricing):
            variable_priced.append(model_id)
            continue
        if is_unpriced(pricing):
            unpriced.append(model_id)
            continue
        provider = model_id_to_provider(model_id)
        cost = pricing_to_cost(pricing, cost_model)
        architecture = m.get("architecture") or {}
        context = m.get("context_length")
        entries[model_id] = {
            "name": m.get("name") or model_id,
            "provider": provider,
            "cost_per_1k_tokens": cost,
            "context_window": 4096 if context is None else context,
            "strengths": determine_strengths(
                architecture.get("modality") or "text->text", model_id
            ),
            "tier": "FAST" if cost == 0 else "STANDARD",
            "api_key_env": PROVIDER_API_KEY.get(provider, "OPENROUTER_API_KEY"),
            "tool_use_score": TOOL_USE_SCORES.get(model_id, 5),
        }

    # Extras first, then pins. The other order -- which this had -- made a pin
    # naming a hand-added model a silent no-op, because the pin loop skips ids
    # that are not in `entries` yet and the extras had not been merged.
    for model_id, fields_ in extra.items():
        if model_id in suppressed:
            continue
        # deepcopy-by-hand: the values are plain primitives, but `strengths` is a
        # list and setdefault would otherwise alias the module-level object.
        entries.setdefault(model_id, {k: list(v) if isinstance(v, list) else v
                                      for k, v in fields_.items()})

    unmatched = sorted(set(pinned) - set(entries))
    for model_id, fields_ in pinned.items():
        if model_id in entries:
            entries[model_id].update(fields_)
    if unmatched:
        # Not fatal: a pin for a model OpenRouter has temporarily dropped is a
        # legitimate state. Silent, though, it is a correction that looks applied
        # and is not.
        print(
            f"WARNING: {len(unmatched)} pinned model(s) matched nothing and were "
            f"not applied: {', '.join(unmatched)}",
            file=sys.stderr,
        )

    for label, ids in (("priced at routing time", variable_priced), ("not token-priced", unpriced)):
        if ids:
            shown = ", ".join(sorted(ids)[:10])
            more = f" (+{len(ids) - 10} more)" if len(ids) > 10 else ""
            print(f"Skipped {len(ids)} model(s) {label}: {shown}{more}")

    return entries


def load_registry_types() -> tuple[type, type, type]:
    """Return (ModelConfig, ModelTier, TaskType) without running the package __init__.

    The ordinary import executes ``model_registry/__init__`` -> ``_service`` ->
    the *currently installed* ``_catalog``, so validating a new catalog would
    require the old one to import and the tool could not repair the file it had
    itself half-written. Loading by path avoids that. The stubs are torn down
    again so an in-process caller (pytest) keeps the real package it had.

    Only member names and dataclass fields are read from these, so it does not
    matter that they are not the same class objects the application uses.
    """
    import importlib.util
    import types

    live = sys.modules.get("weebot.application.services.model_registry._models")
    task_mod = sys.modules.get("weebot.domain.models.task_type")
    if live is not None and task_mod is not None:
        return live.ModelConfig, live.ModelTier, task_mod.TaskType

    def _weebot_keys() -> list[str]:
        return [k for k in sys.modules if k == "weebot" or k.startswith("weebot.")]

    saved = {k: sys.modules[k] for k in _weebot_keys()}
    try:
        for pkg in (
            "weebot",
            "weebot.application",
            "weebot.application.services",
            "weebot.application.services.model_registry",
            "weebot.domain",
            "weebot.domain.models",
        ):
            stub = types.ModuleType(pkg)
            stub.__path__ = []  # type: ignore[attr-defined]
            sys.modules[pkg] = stub

        def _by_path(name: str, path: Path):
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:  # pragma: no cover - unreachable
                raise PayloadError(f"cannot load {name} from {path}")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            parent, _, leaf = name.rpartition(".")
            setattr(sys.modules[parent], leaf, mod)
            return mod

        task_type = _by_path("weebot.domain.models.task_type", TASK_TYPE_PATH)
        models = _by_path("weebot.application.services.model_registry._models", MODELS_PATH)
        return models.ModelConfig, models.ModelTier, task_type.TaskType
    finally:
        for key in _weebot_keys():
            del sys.modules[key]
        sys.modules.update(saved)


def _required_fields(model_config: type) -> tuple[str, ...]:
    """ModelConfig's mandatory keyword names, taken from the dataclass itself.

    Hand-copying this list got ``tool_use_score`` wrong (it has a default) and
    would have gone stale the moment ModelConfig gained a field.
    """
    return tuple(
        f.name
        for f in fields(model_config)
        if f.default is MISSING and f.default_factory is MISSING
    )


def fill_defaults(entries: dict[str, dict]) -> None:
    """Supply ModelConfig's own defaults for fields an override left out.

    ``validate_entries`` only requires the fields the dataclass has no default
    for, so an override may legitimately omit ``tool_use_score`` -- but the
    renderer indexes every field by name and would KeyError on it.
    """
    model_config, _, _ = load_registry_types()
    defaults = {
        f.name: f.default for f in fields(model_config) if f.default is not MISSING
    }
    for cfg in entries.values():
        for name, default in defaults.items():
            cfg.setdefault(name, default)


def validate_entries(entries: dict[str, dict]) -> None:
    """Check every rendered entry before any of it reaches the file."""
    ModelConfig, ModelTier, TaskType = load_registry_types()

    required = _required_fields(ModelConfig)
    known = {f.name for f in fields(ModelConfig)}
    valid_tasks = {t.name for t in TaskType}
    valid_tiers = {t.name for t in ModelTier}

    for model_id, cfg in sorted(entries.items()):
        missing = [f for f in required if f not in cfg]
        if missing:
            raise PayloadError(f"{model_id}: override is missing {missing}")
        # A misspelled key (`teir`, `tool_score`) is silently dropped by the
        # renderer, so the correction someone measured by hand just vanishes.
        unknown = sorted(set(cfg) - known)
        if unknown:
            raise PayloadError(
                f"{model_id}: unknown field(s) {unknown}. ModelConfig accepts "
                f"{sorted(known)}."
            )

        if not isinstance(cfg["name"], str) or not cfg["name"]:
            raise PayloadError(f"{model_id}: name must be a non-empty string")
        if not isinstance(cfg["strengths"], list):
            raise PayloadError(f"{model_id}: strengths must be a list")
        bad = [s for s in cfg["strengths"] if s not in valid_tasks]
        if bad:
            raise PayloadError(f"{model_id}: unknown TaskType(s) {bad}")
        if cfg["tier"] not in valid_tiers:
            raise PayloadError(f"{model_id}: unknown ModelTier {cfg['tier']!r}")

        # Types are checked rather than assumed: `context_window=None` renders
        # as a valid literal, imports cleanly, and then raises TypeError inside
        # QualityOptimized on every selection.
        cost = cfg["cost_per_1k_tokens"]
        if isinstance(cost, bool) or not isinstance(cost, (int, float)):
            raise PayloadError(
                f"{model_id}: cost_per_1k_tokens must be a number, got {type(cost).__name__}"
            )
        if not math.isfinite(cost):
            raise PayloadError(f"{model_id}: cost_per_1k_tokens is not finite ({cost!r})")
        if cost < 0:
            raise PayloadError(
                f"{model_id}: negative cost_per_1k_tokens ({cost!r}). A negative cost "
                f"inverts every comparison in _strategies.py, so such a model wins "
                f"cost-based selection unconditionally."
            )
        for field_name in ("context_window", "tool_use_score"):
            value = cfg[field_name]
            if isinstance(value, bool) or not isinstance(value, int):
                raise PayloadError(
                    f"{model_id}: {field_name} must be an int, got {type(value).__name__}"
                )
            if value <= 0:
                raise PayloadError(f"{model_id}: {field_name} must be positive, got {value!r}")

    if len(entries) < MIN_PLAUSIBLE_MODELS:
        raise PayloadError(
            f"only {len(entries)} models would be rendered, below the plausibility "
            f"floor of {MIN_PLAUSIBLE_MODELS}. Re-run when the API is healthy, or "
            f"pass --from-file with a payload you trust."
        )


def generate_catalog(models: list[dict], cost_model: str = "max") -> str:
    """Generate the full _catalog.py file content."""
    validate_payload(models)
    entries = build_entries(models, cost_model)
    fill_defaults(entries)
    validate_entries(entries)
    return render_catalog(entries, cost_model)


def render_catalog(entries: dict[str, dict], cost_model: str = "max") -> str:
    """Render validated entries to the text of _catalog.py.

    Split out from ``generate_catalog`` so the shipped catalog can be checked
    against it without a payload: a test that re-renders the installed entries
    and compares byte-for-byte is what makes the file's "DO NOT EDIT MANUALLY"
    banner enforceable rather than advisory.
    """
    lines = [
        '"""Auto-generated model catalog. DO NOT EDIT MANUALLY.',
        "",
        f"Generated from {OPENROUTER_API}",
        f"Total models: {len(entries)}",
        f"Cost model: {cost_model}(prompt, completion)",
        "Generated: See git history for timestamp.",
        "",
        "Corrections belong in _catalog_overrides.py, which survives regeneration.",
        "Editing this file directly does not: the next --write discards it.",
        '"""',
        "",
        "# mypy: ignore-errors",
        "# ruff: noqa",
        "",
        "from __future__ import annotations",
        "",
        "from weebot.application.services.model_registry._models import ModelConfig, ModelTier",
        "from weebot.domain.models.task_type import TaskType",
        "",
        "MODELS: dict[str, ModelConfig] = {",
    ]

    for model_id in sorted(entries):
        cfg = entries[model_id]
        strength_str = ", ".join(f"TaskType.{s}" for s in cfg["strengths"])
        # json.dumps, not a bare f-string: these values come from the API, and
        # verify_rendered *executes* what we produce here.
        lines.append(
            f'''    {json.dumps(model_id)}: ModelConfig(
        name={json.dumps(cfg["name"])},
        provider={json.dumps(cfg["provider"])},
        cost_per_1k_tokens={cfg["cost_per_1k_tokens"]!r},
        context_window={cfg["context_window"]!r},
        strengths=[{strength_str}],
        tier=ModelTier.{cfg["tier"]},
        api_key_env={json.dumps(cfg["api_key_env"])},
        tool_use_score={cfg["tool_use_score"]!r},
    ),'''
        )

    lines.extend(["}", ""])
    return "\n".join(lines)


# Loads the rendered catalog with the *package chain stubbed out*. Importing
# `weebot.application.services.model_registry._models` the ordinary way runs the
# package __init__, which imports _service, which imports the currently
# installed _catalog -- so verifying a new catalog would require the old one to
# import, and a half-written file could not be repaired by the tool that wrote it.
_PROBE_SOURCE = """
import importlib.util, sys, types

root, target = sys.argv[1], sys.argv[2]

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    parent, _, leaf = name.rpartition(".")
    if parent:
        setattr(sys.modules[parent], leaf, mod)
    return mod

for pkg in (
    "weebot", "weebot.application", "weebot.application.services",
    "weebot.application.services.model_registry", "weebot.domain", "weebot.domain.models",
):
    stub = types.ModuleType(pkg)
    stub.__path__ = []
    sys.modules[pkg] = stub
    parent, _, leaf = pkg.rpartition(".")
    if parent:
        setattr(sys.modules[parent], leaf, stub)

_load("weebot.domain.models.task_type", root + "/weebot/domain/models/task_type.py")
_load("weebot.application.services.model_registry._models",
      root + "/weebot/application/services/model_registry/_models.py")
print(len(_load("_catalog_probe", target).MODELS))
"""


def verify_rendered(content: str) -> int:
    """Import the rendered catalog in a subprocess; return its model count.

    Interlock 3. A rendered file that does not import -- a TaskType that no
    longer exists, a truncated write -- would otherwise be installed and break
    the package on the next import, at which point the original is already gone.
    """
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "_catalog_probe.py"
        probe.write_text(content, encoding="utf-8")
        try:
            result = subprocess.run(
                [sys.executable, "-c", _PROBE_SOURCE, str(PROJECT_ROOT), str(probe)],
                capture_output=True,
                text=True,
                cwd=str(PROJECT_ROOT),
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:  # pragma: no cover - timing dependent
            raise PayloadError("verifying the rendered catalog timed out after 120s") from exc
    if result.returncode != 0:
        raise PayloadError(f"rendered catalog does not import:\n{result.stderr.strip()}")
    # Anything on the import path that prints would otherwise make int() raise a
    # ValueError that main()'s PayloadError handler does not catch.
    tail = result.stdout.strip().splitlines()
    try:
        return int(tail[-1])
    except (IndexError, ValueError) as exc:
        raise PayloadError(
            f"could not read the model count from the probe; its output was "
            f"{result.stdout.strip()!r}"
        ) from exc


def model_ids(text: str) -> set[str]:
    """Every model id in a rendered catalog."""
    return set(MODEL_ENTRY_RE.findall(text))


def current_model_ids() -> set[str] | None:
    """Model ids in the catalog as it stands, or None if there is no baseline.

    ``None`` and ``set()`` mean different things: no readable catalog at all
    versus a readable catalog with no entries. The shrink guard treats the first
    as "refuse", not as "nothing to lose".
    """
    if not CATALOG_PATH.exists():
        return None
    try:
        text = CATALOG_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    ids = model_ids(text)
    # A readable file that yields no ids means the format drifted from
    # MODEL_ENTRY_RE, not that the catalog is empty; either way there is no
    # baseline to measure a shrink against.
    return ids or None


def report_delta(new_ids: set[str], old: set[str] | None, limit: int = 20) -> set[str]:
    """Print what this run would change; return the ids it would remove."""
    if old is None:
        print(f"\nCurrent catalog: unreadable (no baseline)    Generated: {len(new_ids)} models")
        return set()
    added, removed = new_ids - old, old - new_ids
    print(f"\nCurrent catalog: {len(old)} models    Generated: {len(new_ids)} models")
    for label, ids in (("+ added", added), ("- removed", removed)):
        if ids:
            print(f"\n{label} ({len(ids)}):")
            for i in sorted(ids)[:limit]:
                print(f"    {i}")
            if len(ids) > limit:
                print(f"    ... and {len(ids) - limit} more")
    if not added and not removed:
        print("\nNo membership change.")
    return removed


def install(content: str, diff: bool) -> None:
    """Replace the catalog atomically, then verify what actually landed.

    ``write_text`` truncates first, so an interrupted write leaves a syntactically
    broken catalog and the package stops importing. Writing a sibling temp file
    and renaming makes the replacement a single atomic step.
    """
    old_text = ""
    if diff and CATALOG_PATH.exists():
        # Only --diff needs it. An unreadable current file is not a reason to
        # refuse the write that would replace it.
        with contextlib.suppress(OSError, UnicodeDecodeError):
            old_text = CATALOG_PATH.read_text(encoding="utf-8")

    tmp_path = CATALOG_PATH.with_suffix(".py.tmp")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, CATALOG_PATH)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        raise
    print(f"Written to {CATALOG_PATH}")

    # Interlock 3, second half: everything above verified a string and a copy in
    # a temp directory. This verifies the artifact that ships.
    installed = verify_rendered(CATALOG_PATH.read_text(encoding="utf-8"))
    print(f"Installed catalog imports cleanly: {installed} models")

    if diff:
        lines = list(
            difflib.unified_diff(
                old_text.splitlines(),
                content.splitlines(),
                fromfile="_catalog.py (before)",
                tofile="_catalog.py (after)",
                lineterm="",
                n=1,
            )
        )
        print("\n=== Diff ===")
        if not lines:
            print("No changes (identical)")
        else:
            for line in lines[:200]:
                print(line)
            if len(lines) > 200:
                print(f"... and {len(lines) - 200} more diff lines")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate _catalog.py from OpenRouter API")
    parser.add_argument(
        "--write", action="store_true", help="Replace _catalog.py (default: dry-run)"
    )
    parser.add_argument("--diff", action="store_true", help="Show diff against the current catalog")
    parser.add_argument("--from-file", type=Path, help="Read the models payload from a JSON file")
    parser.add_argument("--save-payload", type=Path, help="Write the fetched payload to a file")
    parser.add_argument(
        "--cost-model",
        choices=("max", "mean"),
        default="max",
        help="How to collapse prompt/completion pricing into one rate (default: max)",
    )
    parser.add_argument(
        "--max-shrink",
        type=float,
        default=0.25,
        help="Fail if more than this fraction of current models would be dropped (default: 0.25)",
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Allow --write when the current catalog cannot be read (no shrink baseline)",
    )
    args = parser.parse_args()

    source = str(args.from_file) if args.from_file else OPENROUTER_API
    print(f"Reading models from {source} ...")
    try:
        models = fetch_models(args.from_file)
    except Exception as e:
        print(f"ERROR: could not read the model list: {e}", file=sys.stderr)
        return 1
    print(f"Read {len(models)} models")

    # Saved before anything can fail: on the live path this is the only copy of
    # a payload that may not be fetchable again from this machine.
    if args.save_payload:
        try:
            args.save_payload.write_text(json.dumps({"data": models}, indent=2), encoding="utf-8")
        except OSError as e:
            print(f"ERROR: could not save the payload to {args.save_payload}: {e}", file=sys.stderr)
            return 1
        print(f"Payload saved to {args.save_payload}")

    try:
        content = generate_catalog(models, args.cost_model)
    except PayloadError as e:
        print(f"REFUSING TO GENERATE: {e}", file=sys.stderr)
        return 2

    old = current_model_ids()
    removed = report_delta(model_ids(content), old)

    shrink_refusal = ""
    if old is None:
        if not args.bootstrap:
            shrink_refusal = (
                "the current catalog could not be read, so --max-shrink has no "
                "baseline. Re-run with --bootstrap if writing without one is intended."
            )
    elif len(removed) / len(old) > args.max_shrink:
        shrink_refusal = (
            f"would drop {len(removed)} of {len(old)} models "
            f"({len(removed) / len(old):.0%} > --max-shrink {args.max_shrink:.0%}). "
            f"Re-run with a higher --max-shrink if this is intended."
        )

    # A dry run writes nothing, so a shrink that *would* be refused is
    # information, not a failure. Exiting non-zero here broke the documented way
    # of previewing a large delta.
    if shrink_refusal:
        if not args.write:
            print(f"\nNOTE: --write would be refused: {shrink_refusal}")
            print("\nDry run. Re-run with --write to install this catalog.")
            return 0
        print(f"\nREFUSING TO WRITE: {shrink_refusal}", file=sys.stderr)
        return 3

    # Verified on both paths: telling a dry run whether the output actually
    # imports is most of what a dry run is for. It sits below the shrink check
    # so a run that is going to be refused does not pay for a subprocess first.
    try:
        rendered_count = verify_rendered(content)
        print(f"Rendered and imported cleanly: {rendered_count} models")
        if not args.write:
            print("\nDry run. Re-run with --write to install this catalog.")
            return 0
        install(content, args.diff)
    except PayloadError as e:
        print(f"REFUSING TO GENERATE: {e}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
