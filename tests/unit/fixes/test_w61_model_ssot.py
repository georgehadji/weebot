"""W6.1 (F18-F20): one home per model fact.

Prices, context windows and capabilities belong to the generated catalog
(`weebot/config/model_catalog.py`); which model serves which role or task
belongs to `weebot/config/model_refs.py`, as ids only. Before this, the same
facts lived in four places that had drifted apart:

* two role tables in model_refs (`_ROLE_MODEL_CASCADE` and `ROLE_MODEL_CONFIG`)
  both defined `planner`, `executor` and `reviewer`, with different models;
* `core/model_cascade_config.py` kept a second `ModelConfig` dataclass with
  hand-copied prices per task, which `estimate_cost` fell back to;
* model_refs docstrings quoted per-token prices that no longer matched the
  catalog (GLM 5.2 "$1.20/$4.10" against $0.034/$7.00 live).
"""

from __future__ import annotations

import pathlib
import re

import pytest

from weebot.config import model_refs
from weebot.config.model_catalog import MODELS

ROOT = pathlib.Path(__file__).resolve().parents[3]


def test_there_is_one_role_table():
    assert not hasattr(model_refs, "_ROLE_MODEL_CASCADE")
    roles = model_refs.ROLE_MODEL_CONFIG
    # The union of what both tables used to serve.
    for role in (
        "researcher", "analyst", "coder", "executor", "reviewer", "admin",
        "automation", "documentation", "product_manager", "planner", "planner_sub",
        "designer", "vision", "critic", "verifier", "summarizer", "subagent", "dreamer",
    ):
        assert roles[role], role
    assert model_refs.get_model_cascade_for_role("planner") == roles["planner"]


def test_the_task_table_holds_ids_only():
    from weebot.core import model_cascade_config as mcc

    assert not hasattr(mcc, "ModelConfig")
    assert not hasattr(mcc, "MODEL_CASCADE")
    tasks = model_refs.TASK_MODEL_CASCADE
    assert tasks and all(
        isinstance(m, str) for models in tasks.values() for m in models
    )


def test_select_model_by_tokens_returns_an_id():
    from weebot.core.model_cascade_config import select_model_by_tokens

    assert select_model_by_tokens("coding", 100) == model_refs.TASK_MODEL_CASCADE["coding"][0]
    assert (
        select_model_by_tokens("coding", 60_000)
        == model_refs.TASK_MODEL_CASCADE["long_context"][0]
    )


def test_estimate_cost_reads_the_catalog_through_a_routing_suffix():
    from weebot.core.model_cascade_config import estimate_cost

    cfg = MODELS["z-ai/glm-5.2"]
    assert estimate_cost("z-ai/glm-5.2:thinking", 1000, 1000) == pytest.approx(
        cfg.estimate_cost(1000, 1000)
    )
    assert estimate_cost("nobody/unknown-model", 1000, 1000) == 0.0


def test_the_domain_names_no_models():
    """`AGENT_CAPABILITIES.preferred_models` was a fifth routing table, in the
    domain layer, still routing to models the role table had dropped."""
    from weebot.domain.models.agent_capability import AgentCapability

    assert "preferred_models" not in AgentCapability.model_fields


def _hyper(cost_tracker):
    from weebot.application.agents.hyper_agent import HyperAgent

    return HyperAgent(
        llm=None, event_bus=None, swarm_bus=None, sub_agent_factory=None,
        cost_tracker=cost_tracker,
    )


class _Afford:
    def __init__(self, *tiers):
        self._tiers = tiers

    def can_afford(self, tier, est):
        return tier in self._tiers


def test_hyper_agent_specs_use_the_role_table():
    from weebot.domain.models.sub_agent import AgentTier, DispatchStrategy
    from weebot.domain.models.swarm import SubGoal, SwarmSpec

    swarm = SwarmSpec(goals=[SubGoal(description="d", role="coder")])
    specs = _hyper(_Afford())._specs_from_swarm(swarm, DispatchStrategy.PARALLEL)
    assert specs[0].model == model_refs.ROLE_MODEL_CONFIG["coder"][0]

    downgraded = _hyper(_Afford(AgentTier.BUDGET))._apply_cost_gating(specs)
    assert downgraded[0].model == model_refs.SUBAGENT_TIER_MODEL["budget"]


def test_the_step_router_reads_the_role_table():
    """The per-step static router (the live path; ACR is off by default) kept
    its own category -> model table, still on the pre-refresh models."""
    from weebot.application.services.task_model_router import (
        CATEGORY_MODEL,
        CATEGORY_ROLE,
    )

    assert CATEGORY_MODEL == {
        cat: model_refs.ROLE_MODEL_CONFIG[role][0] for cat, role in CATEGORY_ROLE.items()
    }


def test_the_acr_pool_holds_only_catalog_models():
    """ACR's default pool is the hand-scored quality profiles, which still list
    retired models (kwaipilot/kat-coder-pro-v2.5)."""
    from weebot.application.services.routing.adaptive_capability_router import (
        default_candidate_pool,
    )
    from weebot.config.model_registry import get_model_config

    pool = default_candidate_pool()
    assert pool and all(get_model_config(m) is not None for m in pool)
    assert "kwaipilot/kat-coder-pro-v2.5" not in pool


def test_no_model_id_literal_lives_outside_model_refs():
    """A catalog model id written as a string in code is a routing decision made
    outside the routing table. Docstrings and comments may still name models."""
    import ast

    from weebot.config.model_registry import strip_routing_suffix

    owners = {
        "weebot/config/model_refs.py",
        "weebot/config/model_catalog.py",
        "weebot/config/model_catalog_overrides.py",
    }
    hits = []
    for top in ("weebot", "cli"):
        for path in (ROOT / top).rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if rel in owners:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docstrings = {
                id(node.body[0].value)
                for node in ast.walk(tree)
                if isinstance(
                    node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                )
                and node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
            }
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in docstrings
                    and "/" in node.value
                    and (node.value in MODELS or strip_routing_suffix(node.value) in MODELS)
                ):
                    hits.append(f"{rel}:{node.lineno} {node.value}")
    assert hits == []


@pytest.mark.parametrize(
    "path", ["weebot/config/model_refs.py", "weebot/core/model_cascade_config.py"]
)
def test_routing_files_quote_no_token_prices(path):
    """A token price written next to a model id is a second copy of a catalog
    fact. Per-image, per-video and per-search prices stay: the catalog covers
    text models only, so those comments are the one record."""
    text = (ROOT / path).read_text(encoding="utf-8")
    assert re.findall(r"\$[\d.]+/\$|\$[\d.]+(?:/1M| per 1M)|per 1M tokens", text) == []
