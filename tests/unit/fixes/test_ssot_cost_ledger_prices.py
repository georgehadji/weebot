"""CostLedger prices come from the model catalog (SSOT audit row 7).

It kept its own per-token table, which had drifted: Opus 4.6 at 15/75 against
the catalog's 5/25 per million, deepseek-chat at 2/8 against 0.26/1.03, and any
other model at a guessed 3/15.
"""

from __future__ import annotations

import pytest

from weebot.config.model_catalog import MODELS
from weebot.utils.cost_ledger import CostLedger, StepCost


def test_the_ledger_keeps_no_price_table():
    assert not hasattr(CostLedger, "PRICING")


def test_a_catalog_model_is_costed_at_catalog_rates():
    model = "anthropic/claude-opus-4.6"
    step = StepCost(step="s", model=model, input_tokens=1000, output_tokens=500)
    assert step.cost_usd == pytest.approx(MODELS[model].estimate_cost(1000, 500))


def test_an_unknown_model_costs_nothing_rather_than_a_guess():
    step = StepCost(step="s", model="nobody/unknown", input_tokens=1000, output_tokens=500)
    assert step.cost_usd == 0.0
