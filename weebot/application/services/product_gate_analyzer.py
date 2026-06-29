"""ProductGateAnalyzer — pre-flight product thinking before plan creation.

Fills in the product-mode pre-flight checklist from a user prompt before
any plan is created.  Uses a cheap/fast model (budget tier) and fails open
on timeout or parse failure — the flow is never blocked.

Closely follows the pattern of PremortmAnalyzer:
    weebot/application/services/premortem_analyzer.py

product-mode reference:
    https://github.com/sohaibt/product-mode
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.ports.llm_port import LLMPort

from weebot.config.constants import TEMPERATURE_PRECISE
from weebot.domain.models.product_context import ProductContext, ProductAssumption

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a product thinking validator. Before any code is written,
fill in this pre-flight checklist from the user's request. Be concise — one sentence
per field.

If the request is too vague to answer a field, say "UNKNOWN" and note what clarification
is needed. If the field is not applicable to this task, say "N/A".

Return ONLY valid JSON (no markdown, no fences):
{
  "problem": "string — whose pain, in one sentence",
  "why_now": "string — what changed, evidence, trigger",
  "scope": "string — smallest change that tests the hypothesis",
  "success_metric": "string — the one observable we expect to change",
  "reversibility": "one-way | two-way",
  "assumptions": [
    {"text": "string", "status": "validated | assumed | unknown"}
  ],
  "overall_confidence": 0.0-1.0
}

Maximum 5 assumptions.  Be honest about confidence — it's better to flag
ambiguity than to pretend certainty."""

# Model used for product-gate analysis.  Uses the budget tier via the
# cascading LLM adapter.  When OpenRouter is rate-limited, the cascade
# falls back to X.AI direct — but this adds latency.  The timeout below
# must accommodate both the cascade fallback path and OpenRouter's
# 429 retry-with-backoff cycle.
_PRODUCT_GATE_MODEL: str = "x-ai/grok-build-0.1"

# Must cover cascade fallback (OpenRouter → X.AI direct) which can take
# 60+ seconds when OpenRouter is rate-limiting.
_TIMEOUT_SECONDS = 120.0
_LOW_CONFIDENCE_THRESHOLD = 0.5
_MAX_CLARIFICATION_QUESTIONS = 3


class ProductGateAnalyzer:
    """Fills the product-mode pre-flight checklist from a user prompt.

    Returns a ProductContext.  On timeout or parse failure, returns a default
    ProductContext with confidence=0.0 and UNKNOWN fields so the flow never
    blocks but still surfaces the gap.

    Uses a direct model call (via the ``model`` parameter on ``chat()``)
    to bypass the multi-provider cascade and keep latency low.
    """

    def __init__(
        self,
        llm: "LLMPort",
        timeout_seconds: float = _TIMEOUT_SECONDS,
        low_confidence_threshold: float = _LOW_CONFIDENCE_THRESHOLD,
        model: str = _PRODUCT_GATE_MODEL,
    ) -> None:
        self._llm = llm
        self._timeout = timeout_seconds
        self._low_confidence_threshold = low_confidence_threshold
        self._model = model

    async def analyze(self, prompt: str, model_id: str = "") -> ProductContext:
        """Fill the pre-flight checklist from *prompt*.

        Args:
            prompt: The user's task description.
            model_id: The model used for this analysis (for audit in the
                      returned ProductContext).

        Returns:
            ProductContext with fields filled (or defaults on failure).
        """
        try:
            response = await asyncio.wait_for(
                self._llm.chat(
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    model=self._model,
                    temperature=TEMPERATURE_PRECISE,
                    max_tokens=500,  # full JSON with 5 assumptions ~400 chars/100 tokens
                ),
                timeout=self._timeout,
            )
            raw = (response.content or "").strip()
            if not raw:
                logger.warning("ProductGateAnalyzer: LLM returned empty content")
                return ProductContext(
                    overall_confidence=0.0,
                    generated_at=datetime.now(timezone.utc).isoformat(),
                    model_used=model_id,
                )
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("\n```", 1)[0]
            data = json.loads(raw)

            assumptions = [
                ProductAssumption(text=str(a.get("text", "")), status=str(a.get("status", "unknown")))
                for a in data.get("assumptions", [])
                if isinstance(a, dict) and a.get("text")
            ]

            return ProductContext(
                problem=str(data.get("problem", "")),
                why_now=str(data.get("why_now", "")),
                scope=str(data.get("scope", "")),
                success_metric=str(data.get("success_metric", "")),
                reversibility=str(data.get("reversibility", "two-way")),
                assumptions=assumptions,
                overall_confidence=float(data.get("overall_confidence", 0.5)),
                generated_at=datetime.now(timezone.utc).isoformat(),
                model_used=model_id,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "ProductGateAnalyzer: timed out after %.1fs", self._timeout,
            )
            return ProductContext(
                overall_confidence=0.0,
                generated_at=datetime.now(timezone.utc).isoformat(),
                model_used=model_id,
            )
        except json.JSONDecodeError:
            logger.warning(
                "ProductGateAnalyzer: LLM returned non-JSON response (len=%d): %.200r",
                len(raw) if 'raw' in dir() else 0,
                raw[:200] if 'raw' in dir() else "[no raw]",
            )
            # Best-effort partial parse — the JSON may be truncated at
            # max_tokens.  Extract whatever key:value pairs we can find.
            partial = ProductContext(
                overall_confidence=0.0,
                generated_at=datetime.now(timezone.utc).isoformat(),
                model_used=model_id,
            )
            raw_val = raw if 'raw' in dir() else ""
            for key in ("problem", "why_now", "scope", "success_metric", "reversibility"):
                import re as _re
                m = _re.search(rf'"{key}"\s*:\s*"([^"]*)"', raw_val)
                if m:
                    setattr(partial, key, m.group(1))
            # Try to extract overall_confidence
            m_conf = _re.search(r'"overall_confidence"\s*:\s*([\d.]+)', raw_val)
            if m_conf:
                try:
                    partial.overall_confidence = float(m_conf.group(1))
                except ValueError:
                    pass
            return partial
        except Exception as exc:
            logger.warning(
                "ProductGateAnalyzer non-blocking failure: %s", exc,
            )
            return ProductContext(
                overall_confidence=0.0,
                generated_at=datetime.now(timezone.utc).isoformat(),
                model_used=model_id,
            )

    def is_confident(self, ctx: ProductContext) -> bool:
        """Return True if the product context meets the confidence threshold."""
        return ctx.overall_confidence >= self._low_confidence_threshold

    def get_low_confidence_fields(self, ctx: ProductContext) -> list[str]:
        """Identify which fields drove low confidence.

        Returns field names where the LLM returned UNKNOWN or empty values.
        """
        low: list[str] = []
        if not ctx.problem or "unknown" in ctx.problem.lower():
            low.append("problem")
        if not ctx.why_now or "unknown" in ctx.why_now.lower():
            low.append("why_now")
        if not ctx.scope or "unknown" in ctx.scope.lower():
            low.append("scope")
        if not ctx.success_metric or "unknown" in ctx.success_metric.lower():
            low.append("success_metric")
        if ctx.overall_confidence < self._low_confidence_threshold:
            low.append("overall_confidence")
        return low

    def generate_clarification_questions(
        self, ctx: ProductContext
    ) -> list[str]:
        """Generate up to 3 clarification questions from low-confidence fields.

        These are static template questions keyed to the missing fields,
        sent to the user for input before re-running the gate.
        """
        low = self.get_low_confidence_fields(ctx)
        questions: list[str] = []
        field_map = {
            "problem": [
                "Who is the user and what problem are they trying to solve?",
            ],
            "why_now": [
                "Why is this needed now — what changed or what happens if we wait?",
            ],
            "scope": [
                "What's the smallest version of this that would be useful?",
            ],
            "success_metric": [
                "How will we know this worked — what metric or observable tells us?",
            ],
            "overall_confidence": [
                "Can you clarify the goal? The description was too vague to confidently frame the problem.",
            ],
        }
        seen = set()
        for field in low:
            for q in field_map.get(field, []):
                if q not in seen and len(questions) < _MAX_CLARIFICATION_QUESTIONS:
                    questions.append(q)
                    seen.add(q)
        return questions
