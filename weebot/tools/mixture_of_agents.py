"""MixtureOfAgentsTool — parallel ensemble reasoning + aggregator synthesis.

Implements the Mixture-of-Agents (MoA) pattern from Wang et al. 2024
(https://arxiv.org/abs/2406.04692):
  1. Multiple reference models generate diverse independent responses in parallel
  2. An aggregator model synthesizes the best combined answer

The tool receives a pre-configured LLMPort (typically an OpenRouter adapter)
via constructor injection and routes all calls through it with model-specific
``model`` kwargs. This keeps the tool fully within the Application layer and
participates in the project's resilience infrastructure (circuit breaker, retry,
cascading).

Best suited for hard tasks where a single model underperforms: complex
reasoning, code correctness verification, research synthesis, math proofs.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, List, Optional

from pydantic import ConfigDict

from weebot.application.ports.llm_port import LLMPort
from weebot.tools.base import BaseTool, ToolResult
from weebot.utils.prompt_loader import load_prompt_with_fallback

logger = logging.getLogger(__name__)

from weebot.config.model_refs import MODEL_MOA_REFERENCE

_DEFAULT_REFERENCE_MODELS: List[str] = MODEL_MOA_REFERENCE

_AGGREGATOR_SYSTEM = load_prompt_with_fallback(
    "moa_aggregator.txt",
    "You are an expert synthesizer. Synthesize multiple responses into one unified answer."
)

_REFERENCE_SYSTEM = load_prompt_with_fallback(
    "moa_reference.txt",
    "You are a helpful AI assistant. Answer accurately and concisely.",
)

__all__ = ["MixtureOfAgentsTool"]


class MixtureOfAgentsTool(BaseTool):
    """Query multiple frontier models in parallel and synthesize with an aggregator.

    Requires an injected ``LLMPort`` configured for an OpenRouter endpoint so
    that the ``model`` kwarg routes each call to the correct provider.
    Register via ``RoleBasedToolRegistry`` with ``llm_port`` supplied.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "mixture_of_agents"
    description: str = (
        "Query multiple AI models in parallel and synthesize their responses into "
        "one superior answer. Use for hard reasoning, code review, or research "
        "questions where diverse model perspectives improve quality."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The question or task to send to all reference models.",
            },
            "reference_models": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "OpenRouter model IDs to query in parallel. "
                    "Defaults to 4 frontier models if omitted."
                ),
            },
            "aggregator_model": {
                "type": "string",
                "description": (
                    "OpenRouter model ID for the aggregator synthesis step. "
                    "Defaults to anthropic/claude-sonnet-4.6."
                ),
                "default": "anthropic/claude-sonnet-4.6",
            },
            "max_concurrency": {
                "type": "integer",
                "description": "Max simultaneous reference model calls (default: 4).",
                "default": 4,
            },
        },
        "required": ["query"],
    }

    # Injected by tool_registry or DI container; None means tool is unconfigured.
    llm_port: Optional[LLMPort] = None

    async def execute(
        self,
        query: str,
        reference_models: Optional[List[str]] = None,
        aggregator_model: str = "anthropic/claude-sonnet-4.6",
        max_concurrency: int = 4,
        **_: Any,
    ) -> ToolResult:
        if self.llm_port is None:
            return ToolResult.error_result(
                "MixtureOfAgentsTool requires an injected LLMPort configured for "
                "an OpenRouter endpoint. Ensure the tool registry passes llm_port "
                "when creating this tool."
            )

        models = reference_models or _DEFAULT_REFERENCE_MODELS
        semaphore = asyncio.Semaphore(max_concurrency)

        # Phase 1: parallel reference model calls
        raw_results = await asyncio.gather(
            *[
                self._query_one(model_id, query, self.llm_port, semaphore)
                for model_id in models
            ]
        )
        successful = [r for r in raw_results if r["response"] is not None]
        failed = [r for r in raw_results if r["response"] is None]

        if not successful:
            errors = "; ".join(r["error"] or "unknown" for r in failed)
            return ToolResult.error_result(
                f"All {len(models)} reference models failed: {errors}"
            )

        # Phase 2: aggregation
        synthesized = await self._aggregate(
            query, successful, aggregator_model, self.llm_port
        )

        return ToolResult.success_result(
            output=synthesized,
            data={
                "reference_results": raw_results,
                "successful_count": len(successful),
                "failed_count": len(failed),
                "reference_models": models,
                "aggregator_model": aggregator_model,
            },
        )

    @staticmethod
    async def _query_one(
        model_id: str,
        query: str,
        llm: LLMPort,
        semaphore: asyncio.Semaphore,
    ) -> dict[str, Any]:
        """Call one reference model and return a result dict."""
        async with semaphore:
            try:
                response = await llm.chat(
                    messages=[
                        {"role": "system", "content": _REFERENCE_SYSTEM},
                        {"role": "user", "content": query},
                    ],
                    model=model_id,
                    tools=None,
                    tool_choice=None,
                    temperature=0.7,
                    max_tokens=1024,
                )
                return {"model": model_id, "response": response.content, "error": None}
            except Exception as exc:
                logger.warning("Reference model %s failed: %s", model_id, exc)
                return {"model": model_id, "response": None, "error": str(exc)}

    @staticmethod
    async def _aggregate(
        query: str,
        successful: list[dict[str, Any]],
        aggregator_model: str,
        llm: LLMPort,
    ) -> str:
        """Synthesize reference responses into one answer via the aggregator model."""
        ref_block = "\n\n".join(
            f"### Response from {r['model']}\n{r['response']}" for r in successful
        )
        agg_prompt = (
            f"Original query: {query}\n\n"
            f"Reference model responses:\n\n{ref_block}\n\n"
            "Please synthesize the single best answer:"
        )
        try:
            response = await llm.chat(
                messages=[
                    {"role": "system", "content": _AGGREGATOR_SYSTEM},
                    {"role": "user", "content": agg_prompt},
                ],
                model=aggregator_model,
                tools=None,
                tool_choice=None,
                temperature=0.3,
                max_tokens=2048,
            )
            return response.content or "(aggregator returned empty response)"
        except Exception as exc:
            logger.error("Aggregator model %s failed: %s", aggregator_model, exc)
            best = max(successful, key=lambda r: len(r["response"] or ""))
            return (
                f"[Aggregator failed; best individual response from {best['model']}]\n\n"
                f"{best['response']}"
            )
