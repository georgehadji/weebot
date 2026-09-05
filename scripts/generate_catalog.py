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
data-loss failure mode. Four interlocks stand between a bad run and the file:

1. **The payload must be plausible.** An empty or malformed ``data`` array is
   rejected rather than rendered. Before this existed, a 200 response carrying
   no models produced a valid, empty catalog and ``--write`` installed it.
2. **Hand-maintained knowledge survives.** ``_catalog_overrides.py`` carries the
   models the API does not list, the fields it gets wrong, and the models
   deliberately dropped. Without it a regeneration silently deleted every
   hand-added entry and resurrected every hand-removed one.
3. **The output must import.** The rendered file is byte-checked by importing it
   in a subprocess before it is allowed to replace the real one.
4. **A large shrink must be asked for.** Losing more than ``--max-shrink`` of the
   current entries fails unless the caller says so explicitly.

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
import json
import subprocess
import sys
import tempfile
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

# A response with fewer models than this is treated as a broken payload rather
# than as OpenRouter having retired 90% of its catalogue overnight. The real
# list has been in the hundreds for the life of this script.
MIN_PLAUSIBLE_MODELS = 50

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
    for key in ("prompt", "completion"):
        try:
            if float(pricing.get(key, 0)) < 0:
                return True
        except (ValueError, TypeError):
            return False
    return False


def pricing_to_cost(pricing: dict, cost_model: str = "max") -> float:
    """Collapse OpenRouter's per-token prompt/completion prices to one per-1k rate.

    See the cost-model note in the module docstring: this number is a
    compromise, and ``cost_model`` says which one.
    """
    try:
        prompt_cost = float(pricing.get("prompt", 0))
        completion_cost = float(pricing.get("completion", 0))
    except (ValueError, TypeError):
        return 0.0

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
    adding another rule here.
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
    """Refuse a payload that would render a catalog we do not want to install."""
    if not models:
        raise PayloadError(
            "the model list is empty. A 200 response carrying no models would "
            "otherwise render an empty catalog and replace the real one."
        )
    if len(models) < MIN_PLAUSIBLE_MODELS:
        raise PayloadError(
            f"only {len(models)} models returned, below the plausibility floor of "
            f"{MIN_PLAUSIBLE_MODELS}. Re-run when the API is healthy, or pass "
            f"--from-file with a payload you trust."
        )
    missing = [m for m in models if not isinstance(m, dict) or not m.get("id")]
    if missing:
        raise PayloadError(f"{len(missing)} entries have no 'id' field")


def build_entries(models: list[dict], cost_model: str) -> dict[str, dict]:
    """Render every model to ModelConfig kwargs, then apply the overrides."""
    extra, pinned, suppressed = load_overrides()
    entries: dict[str, dict] = {}

    variable_priced: list[str] = []

    for m in models:
        model_id = m.get("id", "")
        if model_id in suppressed:
            continue
        if is_variable_pricing(m.get("pricing", {})):
            variable_priced.append(model_id)
            continue
        provider = model_id_to_provider(model_id)
        cost = pricing_to_cost(m.get("pricing", {}), cost_model)
        entries[model_id] = {
            "name": m.get("name", model_id),
            "provider": provider,
            "cost_per_1k_tokens": cost,
            "context_window": m.get("context_length", 4096),
            "strengths": determine_strengths(
                m.get("architecture", {}).get("modality", "text->text"), model_id
            ),
            "tier": "FAST" if cost == 0 else "STANDARD",
            "api_key_env": PROVIDER_API_KEY.get(provider, "OPENROUTER_API_KEY"),
            "tool_use_score": TOOL_USE_SCORES.get(model_id, 5),
        }

    for model_id, fields in pinned.items():
        if model_id in entries:
            entries[model_id].update(fields)

    for model_id, fields in extra.items():
        if model_id in suppressed:
            continue
        entries.setdefault(model_id, dict(fields))

    if variable_priced:
        print(
            f"Skipped {len(variable_priced)} model(s) priced at routing time: "
            + ", ".join(sorted(variable_priced))
        )

    return entries


# Every keyword ModelConfig requires. An override missing one of these would
# render a call that cannot be constructed, so it is caught here rather than by
# the import probe, where the message would be far less useful.
_REQUIRED_FIELDS = (
    "name",
    "provider",
    "cost_per_1k_tokens",
    "context_window",
    "strengths",
    "tier",
    "api_key_env",
    "tool_use_score",
)


def validate_entries(entries: dict[str, dict]) -> None:
    """Check every rendered entry before any of it reaches the file."""
    from weebot.application.services.model_registry._models import ModelTier
    from weebot.domain.models.task_type import TaskType

    for model_id, cfg in sorted(entries.items()):
        missing = [f for f in _REQUIRED_FIELDS if f not in cfg]
        if missing:
            raise PayloadError(f"{model_id}: override is missing {missing}")

    valid_tasks = {t.name for t in TaskType}
    valid_tiers = {t.name for t in ModelTier}
    for model_id, cfg in sorted(entries.items()):
        bad = [s for s in cfg["strengths"] if s not in valid_tasks]
        if bad:
            raise PayloadError(f"{model_id}: unknown TaskType(s) {bad}")
        if cfg["tier"] not in valid_tiers:
            raise PayloadError(f"{model_id}: unknown ModelTier {cfg['tier']!r}")

    negative = sorted(k for k, v in entries.items() if v["cost_per_1k_tokens"] < 0)
    if negative:
        raise PayloadError(
            f"negative cost_per_1k_tokens for {negative}. A negative cost inverts "
            f"every comparison in _strategies.py, so such a model wins cost-based "
            f"selection unconditionally."
        )


def generate_catalog(models: list[dict], cost_model: str = "max") -> str:
    """Generate the full _catalog.py file content."""
    validate_payload(models)
    entries = build_entries(models, cost_model)
    validate_entries(entries)

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
        "",
        "MODELS: dict[str, ModelConfig] = {",
    ]

    for model_id in sorted(entries):
        cfg = entries[model_id]
        strength_str = ", ".join(f"TaskType.{s}" for s in cfg["strengths"])
        lines.append(
            f'''
    "{model_id}": ModelConfig(
        name="{cfg["name"]}",
        provider="{cfg["provider"]}",
        cost_per_1k_tokens={cfg["cost_per_1k_tokens"]},
        context_window={cfg["context_window"]},
        strengths=[{strength_str}],
        tier=ModelTier.{cfg["tier"]},
        api_key_env="{cfg["api_key_env"]}",
        tool_use_score={cfg["tool_use_score"]},
    ),'''
        )

    lines.extend(["", "}", ""])
    return "\n".join(lines)


def verify_rendered(content: str) -> int:
    """Import the rendered catalog in a subprocess; return its model count.

    Interlock 3. A rendered file that does not import -- an unescaped quote in a
    model name, a TaskType that no longer exists -- would otherwise be installed
    and break the package on the next import, at which point the original is
    already gone.
    """
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "_catalog_probe.py"
        probe.write_text(content, encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import importlib.util,sys;"
                f"spec=importlib.util.spec_from_file_location('probe',{str(probe)!r});"
                "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);"
                "print(len(m.MODELS))",
            ],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=120,
        )
    if result.returncode != 0:
        raise PayloadError(f"rendered catalog does not import:\n{result.stderr.strip()}")
    return int(result.stdout.strip())


def current_model_ids() -> set[str]:
    """Model ids in the catalog as it stands, for the delta report."""
    if not CATALOG_PATH.exists():
        return set()
    import re

    return set(re.findall(r'^    "([^"]+)": ModelConfig\(', CATALOG_PATH.read_text(), re.M))


def report_delta(new_ids: set[str]) -> tuple[set[str], set[str]]:
    """Print, and return, what this run would add and remove."""
    old = current_model_ids()
    added, removed = new_ids - old, old - new_ids
    print(f"\nCurrent catalog: {len(old)} models    Generated: {len(new_ids)} models")
    for label, ids in (("+ added", added), ("- removed", removed)):
        if ids:
            print(f"\n{label} ({len(ids)}):")
            for i in sorted(ids):
                print(f"    {i}")
    if not added and not removed:
        print("\nNo membership change.")
    return added, removed


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
    args = parser.parse_args()

    source = str(args.from_file) if args.from_file else OPENROUTER_API
    print(f"Reading models from {source} ...")
    try:
        models = fetch_models(args.from_file)
    except Exception as e:
        print(f"ERROR: could not read the model list: {e}", file=sys.stderr)
        return 1
    print(f"Read {len(models)} models")

    if args.save_payload:
        args.save_payload.write_text(json.dumps({"data": models}, indent=2), encoding="utf-8")
        print(f"Payload saved to {args.save_payload}")

    try:
        content = generate_catalog(models, args.cost_model)
        rendered_count = verify_rendered(content)
    except PayloadError as e:
        print(f"REFUSING TO GENERATE: {e}", file=sys.stderr)
        return 2

    print(f"Rendered and imported cleanly: {rendered_count} models")

    import re

    new_ids = set(re.findall(r'^    "([^"]+)": ModelConfig\(', content, re.M))
    _, removed = report_delta(new_ids)

    old_count = len(current_model_ids())
    if old_count and len(removed) / old_count > args.max_shrink:
        print(
            f"\nREFUSING TO WRITE: would drop {len(removed)} of {old_count} models "
            f"({len(removed) / old_count:.0%} > --max-shrink {args.max_shrink:.0%}). "
            f"Re-run with a higher --max-shrink if this is intended.",
            file=sys.stderr,
        )
        return 3

    if not args.write:
        print("\nDry run. Re-run with --write to install this catalog.")
        return 0

    backup = CATALOG_PATH.with_suffix(".py.bak")
    if CATALOG_PATH.exists():
        import shutil

        shutil.copy2(CATALOG_PATH, backup)
        print(f"Backed up to {backup}")

    CATALOG_PATH.write_text(content, encoding="utf-8")
    print(f"Written to {CATALOG_PATH}")

    if args.diff and backup.exists():
        result = subprocess.run(
            ["diff", "-u", str(backup), str(CATALOG_PATH)], capture_output=True, text=True
        )
        print("\n=== Diff ===")
        print(result.stdout[:2000] if result.stdout else "No changes (identical)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
