"""CostLedger -- real token-usage tracking and EUR cost display.

Captures response.usage from OpenAI-compatible LLM calls and converts
prompt/completion token counts into USD and EUR costs.

Author: Georgios-Chrysovalantis Chatzivantsidis
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class StepCost:
    """Token usage and cost for a single LLM call."""

    step: str
    model: str
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cost_usd(self) -> float:
        in_rate, out_rate = CostLedger.PRICING.get(
            self.model, CostLedger.PRICING["default"]
        )
        return (
            self.input_tokens * in_rate / 1_000_000
            + self.output_tokens * out_rate / 1_000_000
        )

    @property
    def cost_eur(self) -> float:
        return self.cost_usd * CostLedger.EUR_RATE


class CostLedger:
    """Track real token usage from LLM API responses and display EUR costs.

    Usage::

        ledger = CostLedger()
        response = await client.chat.completions.create(...)
        cost = ledger.record("step-1", response.usage, model="gpt-4o-mini")
        ledger.print_step(cost)   # inline after each call
        ...
        ledger.print_report()     # summary table at the end
    """

    # (input $/1M tokens, output $/1M tokens)
    PRICING: dict[str, tuple[float, float]] = {
        "claude-sonnet-4-6":  (3.00,  15.00),
        "claude-opus-4-6":    (15.00, 75.00),
        "claude-haiku-4-5":   (0.80,   4.00),
        "gpt-4o":             (5.00,  15.00),
        "gpt-4o-mini":        (0.15,   0.60),
        "deepseek-chat":      (2.00,   8.00),
        "default":            (3.00,  15.00),
    }

    EUR_RATE: float = 0.92

    def __init__(self) -> None:
        self._steps: list[StepCost] = []

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    @staticmethod
    def _to_int(val: Any) -> int:
        """Safely convert a token count to int; returns 0 on failure."""
        try:
            return int(val)
        except (TypeError, ValueError):
            return 0

    def record(self, step: str, usage: Any, model: str) -> StepCost:
        """Record token counts from an API response.usage object.

        Handles both OpenAI-style (prompt_tokens / completion_tokens)
        and any object that exposes those attributes.
        """
        cost = StepCost(
            step=step,
            model=model,
            input_tokens=self._to_int(getattr(usage, "prompt_tokens", 0)),
            output_tokens=self._to_int(getattr(usage, "completion_tokens", 0)),
        )
        self._steps.append(cost)
        return cost

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def print_step(self, cost: StepCost) -> None:
        """Print a one-line summary immediately after a single LLM call."""
        print(
            f"  [tokens] in={cost.input_tokens:,}  "
            f"out={cost.output_tokens:,}  "
            f"total={cost.total_tokens:,}  "
            f"cost=${cost.cost_usd:.6f}  "
            f"EUR={cost.cost_eur:.6f}"
        )

    def print_report(self) -> None:
        """Print an aligned cost table summarising all recorded steps."""
        if not self._steps:
            return

        total_in  = sum(s.input_tokens  for s in self._steps)
        total_out = sum(s.output_tokens for s in self._steps)
        total_tok = total_in + total_out
        total_usd = sum(s.cost_usd for s in self._steps)
        total_eur = sum(s.cost_eur for s in self._steps)

        print()
        print("=" * 62)
        print(f"  COST REPORT -- {len(self._steps)} step(s)")
        print(
            f"  {'STEP':<12} {'IN tok':>8} {'OUT tok':>8} "
            f"{'TOTAL':>8} {'USD':>10} {'EUR':>10}"
        )
        print("  " + "-" * 60)
        for s in self._steps:
            print(
                f"  {s.step:<12} {s.input_tokens:>8,} {s.output_tokens:>8,} "
                f"{s.total_tokens:>8,} ${s.cost_usd:>9.6f} {s.cost_eur:>9.6f}"
            )
        print("  " + "-" * 60)
        print(
            f"  {'TOTAL':<12} {total_in:>8,} {total_out:>8,} "
            f"{total_tok:>8,} ${total_usd:>9.6f} {total_eur:>9.6f}"
        )
        model_label = self._steps[-1].model if self._steps else "unknown"
        print(f"  Model: {model_label}  |  1 USD = {self.EUR_RATE} EUR")
        print("=" * 62)
        print()

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def steps(self) -> list[StepCost]:
        """All recorded StepCost entries (copy)."""
        return list(self._steps)

    @property
    def total_cost_usd(self) -> float:
        return sum(s.cost_usd for s in self._steps)

    @property
    def total_cost_eur(self) -> float:
        return sum(s.cost_eur for s in self._steps)
