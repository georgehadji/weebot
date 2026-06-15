"""VerbalizedSampler — reusable VS primitive for diverse candidate generation.

Phase 0 of the Verbalized Sampling implementation.  One shared service
that every consumer (ToT, Planner, Dreamer, Optimizer, Content) reuses.

Fail-open: on any parse/LLM error, returns a single-item distribution
with the fallback text so the agentic loop never regresses.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal, Optional

from weebot.config.constants import (
    VS_DEFAULT_K,
    VS_TAIL_THRESHOLD,
    MAX_TOKENS_STANDARD,
    TEMPERATURE_CREATIVE,
)
from weebot.config.model_refs import get_vs_model
from weebot.models.structured_output import (
    SampledDistribution,
    SampledResponse,
    VS_FALLBACK_PROMPT,
    VS_PROMPT_FILENAME,
    parse_sampled_distribution,
)
from weebot.utils.prompt_loader import load_prompt_with_fallback

logger = logging.getLogger(__name__)


class VerbalizedSampler:
    """Generates diverse candidate distributions via Verbalized Sampling.

    Builds the VS prompt, calls ``llm.chat(response_format=json_object)``,
    and parses the result into a ``SampledDistribution``.  Fail-open: any
    exception produces a single-item distribution so the caller never sees
    an empty candidate list.

    Usage::

        sampler = VerbalizedSampler(llm)
        dist = await sampler.sample(
            instruction="Propose 3 ways to fix the login bug",
            k=3,
            variant="cot",
        )
        for candidate in dist.texts():
            print(candidate)
    """

    def __init__(
        self,
        llm: Any,
        model: Optional[str] = None,
        default_k: int = VS_DEFAULT_K,
        default_threshold: float = VS_TAIL_THRESHOLD,
    ):
        self._llm = llm
        self._model = model or get_vs_model()
        self._default_k = default_k
        self._default_threshold = default_threshold

        # Load prompt template (with file fallback)
        self._prompt_template = load_prompt_with_fallback(
            VS_PROMPT_FILENAME, VS_FALLBACK_PROMPT,
        )

    async def sample(
        self,
        instruction: str,
        *,
        k: Optional[int] = None,
        threshold: Optional[float] = None,
        variant: Literal["standard", "cot"] = "standard",
        context: str = "",
        temperature: float = TEMPERATURE_CREATIVE,
        max_tokens: int = MAX_TOKENS_STANDARD,
        timeout: float = 20.0,
    ) -> SampledDistribution:
        """Generate a verbalized distribution over candidate responses.

        Args:
            instruction: The task instruction for candidate generation.
            k: Number of candidates (default ``VS_DEFAULT_K`` = 5).
            threshold: Tail threshold (None = full distribution).
            variant: ``"standard"`` (direct) or ``"cot"`` (reason-first,
                best on capable models — paper's VS-CoT).
            context: Optional context string prepended to the instruction.
            temperature: Generation temperature (default CREATIVE 0.7).
            max_tokens: Max tokens for the response.
            timeout: Per-call timeout in seconds.

        Returns:
            SampledDistribution — never raises, single-item fallback on error.
        """
        k = k or self._default_k
        threshold_clause = ""
        if threshold is not None:
            threshold_clause = (
                f"- Favor the TAILS: only include candidates whose "
                f"probability is below {threshold}."
            )
        elif threshold is None and variant == "tail":
            threshold_clause = (
                f"- Favor the TAILS: only include candidates whose "
                f"probability is below {self._default_threshold}."
            )

        # Build the prompt
        prompt_body = self._prompt_template.format(
            k=k,
            threshold_clause=threshold_clause,
        )

        if context:
            full_instruction = f"{context}\n\n{instruction}"
        else:
            full_instruction = instruction

        if variant == "cot":
            messages = [
                {
                    "role": "system",
                    "content": (
                        "First reason step-by-step about the possible approaches, "
                        "then output the distribution as JSON.\\n\\n"
                        f"{prompt_body}"
                    ),
                },
                {"role": "user", "content": full_instruction},
            ]
        else:
            messages = [
                {"role": "system", "content": prompt_body},
                {"role": "user", "content": full_instruction},
            ]

        # Call LLM with timeout
        try:
            response = await asyncio.wait_for(
                self._llm.chat(
                    messages=messages,
                    model=self._model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                ),
                timeout=timeout,
            )
            raw_text = response.content if hasattr(response, "content") else str(response)
            dist = parse_sampled_distribution(raw_text)
            if dist:
                logger.debug(
                    "VS sample: k=%d variant=%s returned %d responses, "
                    "mode_prob=%.3f",
                    k, variant, len(dist.responses),
                    dist.mode().probability if dist.mode() else 0.0,
                )
                return dist
            # Empty parse — fall through to single-item fallback
            logger.warning("VS: empty parse — falling back to single-item distribution")

        except asyncio.TimeoutError:
            logger.warning("VS: timeout after %.1fs — falling back", timeout)
        except Exception as exc:
            logger.warning("VS: %s — falling back to single-item distribution", exc)

        # Fail-open: return a single-item distribution wrapping the instruction
        return SampledDistribution(
            responses=[SampledResponse(text=instruction, probability=1.0)],
        )
