#!/usr/bin/env python3
"""generate_catalog.py — Fetch models from OpenRouter and regenerate _catalog.py.

Usage:
    python scripts/generate_catalog.py                          # dry-run: print stats
    python scripts/generate_catalog.py --write                  # write to _catalog.py
    python scripts/generate_catalog.py --write --diff           # write + diff

The script fetches https://openrouter.ai/api/v1/models and maps each model
to the `ModelConfig` format used by weebot. Manual overrides (provider mappings,
custom pricing, tool_use_score) are merged from ``_catalog_overrides.py``.

Requirements:
    pip install requests
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(override=True)

OPENROUTER_API = "https://openrouter.ai/api/v1/models"

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


def model_id_to_provider(model_id: str) -> str:
    """Map an OpenRouter model ID to a weebot provider name."""
    prefix = model_id.split("/")[0] if "/" in model_id else model_id
    return PREFIX_PROVIDER.get(prefix, "openrouter")


def model_id_to_key(model_id: str) -> str:
    """Convert model ID to a valid Python dict key (model_identifier format)."""
    return model_id.replace("/", "/").replace(":", "-")


def pricing_to_cost(pricing: dict) -> float:
    """Convert OpenRouter pricing dict to cost_per_1k_tokens."""
    try:
        prompt_cost = float(pricing.get("prompt", 0))
        completion_cost = float(pricing.get("completion", 0))
        # Use the higher of prompt/completion cost as the single value
        cost = max(prompt_cost, completion_cost)
        # OpenRouter returns per-token prices. We store per-1K-tokens.
        return cost * 1000
    except (ValueError, TypeError):
        return 0.0


def determine_strengths(modality: str, model_id: str) -> list[str]:
    """Determine appropriate TaskType strengths based on model modality."""
    import re
    from weebot.domain.models.task_type import TaskType

    strengths = [TaskType.CHAT]

    if "image" in modality or "vision" in modality or "multimodal" in modality:
        strengths.append(TaskType.CREATIVE)

    if "code" in model_id.lower() or "coder" in model_id.lower():
        strengths.append(TaskType.CODE_GENERATION)
        strengths.append(TaskType.DEBUGGING)
    else:
        strengths.append(TaskType.CODE_REVIEW)
        strengths.append(TaskType.REASONING)

    if any(kw in model_id.lower() for kw in ("reason", "think", "deep")):
        strengths.append(TaskType.REASONING)

    strengths.append(TaskType.DOCUMENTATION)
    strengths.append(TaskType.ARCHITECTURE)

    return strengths


def fetch_models() -> list[dict]:
    """Fetch model list from OpenRouter API."""
    import requests
    resp = requests.get(OPENROUTER_API, timeout=30)
    resp.raise_for_status()
    return resp.json().get("data", [])


def generate_catalog(models: list[dict]) -> str:
    """Generate the full _catalog.py file content."""
    lines = []
    lines.append('"""Auto-generated model catalog. DO NOT EDIT MANUALLY.')
    lines.append(f"")
    lines.append(f"Generated from {OPENROUTER_API}")
    lines.append(f"Total models: {len(models)}")
    lines.append(f"Generated: See git history for timestamp.")
    lines.append('"""')
    lines.append("")
    lines.append("# mypy: ignore-errors")
    lines.append("# ruff: noqa")
    lines.append("")
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append("from weebot.application.services.model_registry._models import ModelConfig, ModelTier")
    lines.append("from weebot.domain.models.task_type import TaskType")
    lines.append("")
    lines.append("")
    lines.append("MODELS: dict[str, ModelConfig] = {")

    for m in sorted(models, key=lambda x: x.get("id", "")):
        model_id = m.get("id", "")
        name = m.get("name", model_id)
        context = m.get("context_length", 4096)
        pricing = m.get("pricing", {})
        modality = m.get("architecture", {}).get("modality", "text->text")

        provider = model_id_to_provider(model_id)
        cost = pricing_to_cost(pricing)
        strengths = determine_strengths(modality, model_id)
        tier = "ModelTier.FAST" if cost == 0 else "ModelTier.STANDARD"
        api_key = PROVIDER_API_KEY.get(provider, "OPENROUTER_API_KEY")
        tool_score = TOOL_USE_SCORES.get(model_id, 5)

        # Format strengths list
        strength_str = ", ".join(f"TaskType.{s.name}" for s in strengths)

        model_block = f"""
    "{model_id}": ModelConfig(
        name="{name}",
        provider="{provider}",
        cost_per_1k_tokens={cost},
        context_window={context},
        strengths=[{strength_str}],
        tier={tier},
        api_key_env="{api_key}",
        tool_use_score={tool_score},
    ),"""
        lines.append(model_block)

    lines.append("")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate _catalog.py from OpenRouter API")
    parser.add_argument("--write", action="store_true", help="Write to _catalog.py (default: dry-run)")
    parser.add_argument("--diff", action="store_true", help="Show diff with current catalog")
    args = parser.parse_args()

    print(f"Fetching models from {OPENROUTER_API}...")
    models = fetch_models()
    print(f"Fetched {len(models)} models")

    content = generate_catalog(models)
    output_path = PROJECT_ROOT / "weebot/application/services/model_registry/_catalog.py"

    if args.write:
        # Backup existing catalog
        backup = output_path.with_suffix(".py.bak")
        if output_path.exists():
            import shutil
            shutil.copy2(output_path, backup)
            print(f"Backed up to {backup}")

        with open(output_path, "w") as f:
            f.write(content)
        print(f"Written to {output_path}")

        if args.diff:
            import subprocess
            result = subprocess.run(
                ["diff", "-u", str(backup), str(output_path)],
                capture_output=True, text=True,
            )
            if result.stdout:
                print("\n=== Diff ===")
                print(result.stdout[:2000])
            else:
                print("No changes (identical)")
    else:
        print(f"\nGenerated catalog: {len(content.split(chr(10)))} lines, {len(models)} models")
        print("Run with --write to persist, or use --diff to compare")


if __name__ == "__main__":
    main()
