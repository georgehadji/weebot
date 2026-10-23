"""Every text model weebot can route to must exist in the model catalog.

The catalog is generated from OpenRouter's live list, so "not in the catalog"
means "OpenRouter will 404 it". On 2026-09-26 that was true of the cascade's
last-resort tier (`qwen/qwen3.8-max`, kept alive only by a hand-written catalog
override), a budget model (`nex-agi/nex-n2-pro`), and eight of the eighteen
models in core/model_cascade_config.py -- whose `get_cascade_for_task` sorts the
free tier first, so every cascade built from it opened with dead models.

Image, video and rerank models are out of scope: the generated catalog covers
OpenRouter's default text listing only.
"""

from __future__ import annotations

import pytest

from weebot.config import model_refs
from weebot.config.model_catalog import MODELS
from weebot.config.model_registry import strip_routing_suffix


def _routed() -> dict[str, set[str]]:
    sources: dict[str, set[str]] = {
        "model_refs.MODEL_CASCADE_TIER1-4": {
            model_refs.MODEL_CASCADE_TIER1,
            model_refs.MODEL_CASCADE_TIER2,
            model_refs.MODEL_CASCADE_TIER3,
            model_refs.MODEL_CASCADE_TIER4,
        },
        "model_refs.ROLE_MODEL_CONFIG": {
            m for ms in model_refs.ROLE_MODEL_CONFIG.values() for m in ms
        },
        "model_refs.TASK_MODEL_CASCADE": {
            m for ms in model_refs.TASK_MODEL_CASCADE.values() for m in ms
        },
        "model_refs.SUBAGENT_TIER_MODEL": set(model_refs.SUBAGENT_TIER_MODEL.values()),
        # The named constants (planner, reviewer, role defaults, budget, price
        # keys). Image and video constants are out of scope, as above; an id
        # without a slash is a provider-native name for a direct adapter.
        "model_refs.MODEL_* constants": {
            value
            for name, values in vars(model_refs).items()
            if name.startswith("MODEL_")
            and not name.startswith(("MODEL_IMAGE_", "MODEL_VIDEO_"))
            and isinstance(values, (str, list))
            for value in ([values] if isinstance(values, str) else values)
            if isinstance(value, str) and "/" in value
        },
    }
    return sources


@pytest.mark.parametrize("source", sorted(_routed()))
def test_every_routed_model_is_in_the_catalog(source: str) -> None:
    missing = sorted(
        m for m in _routed()[source] if m not in MODELS and strip_routing_suffix(m) not in MODELS
    )
    assert missing == [], (
        f"{source} routes to models OpenRouter does not list (per the generated "
        f"catalog). Replace or remove them, or regenerate the catalog if they are "
        f"new: {missing}"
    )
