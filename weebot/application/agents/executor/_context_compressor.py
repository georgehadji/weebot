"""ContextCompressor — manages conversation buffer, compression, screenshots, and reflection.

Extracted from the original ExecutorAgent god class.  Owns all context-windowing
logic: token tracking, auto-compression, screenshot ingestion, and structured
vision reflection.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from collections import deque


logger = logging.getLogger(__name__)


class ContextCompressor:
    """Manages conversation buffer flow control.

    Wraps token accounting, auto-compression at the context limit,
    screenshot injection, and structured vision reflection
    (observe -> plan -> self-correct).
    """

    def __init__(
        self,
        conversation_buffer: deque,
        auto_compress: bool = True,
        context_window: int = 128_000,
        llm=None,  # LLMPort
        model: str | None = None,
        compressor=None,  # ConversationCompressor | None
    ) -> None:
        self._conversation_buffer = conversation_buffer
        self._auto_compress = auto_compress
        self._context_window = context_window
        self._llm = llm
        self._model = model
        self._compressor = compressor
        self._total_prompt_tokens: int = 0
        self._total_completion_tokens: int = 0
        self._last_expected_outcome: Optional[str] = None

    # ── Token tracking & compression ───────────────────────────────

    @property
    def total_prompt_tokens(self) -> int:
        return self._total_prompt_tokens

    @property
    def total_completion_tokens(self) -> int:
        return self._total_completion_tokens

    async def track_usage_and_maybe_compress(self, resp: Any) -> None:
        """Accumulate real token usage from *resp* and trigger compression if needed.

        Called as a post-success callback from CascadeExecutor and from
        vision reflection calls. Handles both object-attribute and dict usage.
        """
        if hasattr(resp, "usage") and resp.usage:
            usage = resp.usage
            if isinstance(usage, dict):
                self._total_prompt_tokens += usage.get("prompt_tokens", 0) or 0
                self._total_completion_tokens += usage.get("completion_tokens", 0) or 0
            else:
                self._total_prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
                self._total_completion_tokens += getattr(usage, "completion_tokens", 0) or 0

        if self._auto_compress:
            try:
                await self._maybe_compress()
            except Exception as exc:
                logger.warning(
                    "Compressor quarantine: _maybe_compress failed — %s: %s",
                    type(exc).__name__, exc,
                )

    async def _maybe_compress(self) -> None:
        """Summarize the middle of the conversation buffer when approaching limit."""
        conversation = list(self._conversation_buffer)
        if not conversation:
            return

        # Crude estimate: 4 chars per token
        estimated_tokens = sum(len(str(m.get("content", ""))) // 4 for m in conversation)

        if estimated_tokens < self._context_window * 0.75:
            return

        try:
            if self._compressor is None:
                from weebot.application.services.conversation_compressor import (
                    ConversationCompressor,
                )
                self._compressor = ConversationCompressor(
                    llm=self._llm,
                    cheap_model=self._model,
                )

            keep_first = max(1, len(conversation) // 4)
            keep_last = max(1, len(conversation) // 4)
            middle = conversation[keep_first:-keep_last] if keep_last > 0 else conversation[keep_first:]
            if not middle:
                return

            summary = await self._compressor.compress(middle)
            if summary:
                self._conversation_buffer.clear()
                for msg in conversation[:keep_first]:
                    self._conversation_buffer.append(msg)
                self._conversation_buffer.append({"role": "system", "content": summary})
                for msg in conversation[-keep_last:]:
                    self._conversation_buffer.append(msg)
                logger.info(
                    "Compressed conversation: %d -> %d messages, %d tokens cleared",
                    len(conversation), len(self._conversation_buffer),
                    estimated_tokens,
                )
        except Exception as exc:
            logger.warning(
                "Compressor quarantine: compression failed — %s: %s",
                type(exc).__name__, exc,
            )

    # ── Vision helpers ─────────────────────────────────────────────

    @property
    def vision_enabled(self) -> bool:
        """True when vision-in-the-loop is on and the active model accepts images."""
        from weebot.config.feature_flags import is_enabled
        if not is_enabled("VISION_IN_LOOP_ENABLED"):
            return False
        from weebot.infrastructure.adapters.llm._multimodal import model_supports_vision
        return model_supports_vision(self._model or "")

    @property
    def reflection_enabled(self) -> bool:
        """True when Phase 2 structured reflection is on (requires vision + reflection flags)."""
        from weebot.config.feature_flags import is_enabled
        return self.vision_enabled and is_enabled("VISION_REFLECTION_ENABLED")

    def inject_screenshot(self, tool_name: str, image_b64: str) -> None:
        """Append the latest screenshot as an image message for the next LLM call.

        Bounds token cost by keeping only the most recent screenshot live —
        image blocks already in the buffer are downgraded to a text placeholder.
        """
        from weebot.infrastructure.adapters.llm._multimodal import build_image_message

        updated = []
        for msg in self._conversation_buffer:
            content = msg.get("content")
            if isinstance(content, list):
                new_content = [
                    {"type": "text", "text": "[earlier screenshot omitted]"}
                    if isinstance(b, dict) and b.get("type") == "image"
                    else b
                    for b in content
                ]
                updated.append({**msg, "content": new_content})
            else:
                updated.append(msg)
        self._conversation_buffer.clear()
        for m in updated:
            self._conversation_buffer.append(m)
        self._conversation_buffer.append(
            build_image_message(f"Current screen after {tool_name}:", image_b64)
        )

    async def reflect_on_screenshot(
        self, tool_name: str, image_b64: str, task_context: str = "",
    ) -> Optional[dict]:
        """Ask the LLM to produce a structured PageObservation + NextActionPlan.

        Grounds the reflection in the current task goal and, when available, the
        previously predicted outcome — so the model can self-correct by comparing
        what it expected against what it now sees.

        Non-blocking: any parse/validation error returns None so execution continues.
        """
        if not self.reflection_enabled:
            return None

        from weebot.config.constants import MAX_TOKENS_SHORT, TEMPERATURE_DETERMINISTIC
        from weebot.models.structured_output import VisionReflection

        goal_line = (
            f"Current task goal: {task_context.strip()}\n"
            if task_context and task_context.strip()
            else ""
        )
        prior_line = (
            f"Your previous action predicted this outcome: {self._last_expected_outcome!r}. "
            "Compare it to what you now see and note in 'summary' whether it held.\n"
            if self._last_expected_outcome
            else ""
        )
        prompt = (
            "You are observing the current screen state after a tool action.\n"
            + goal_line
            + prior_line
            + "Examine the screenshot and respond with a JSON object matching this schema exactly:\n"
            "{\n"
            '  "observation": {\n'
            '    "summary": "<one-sentence description>",\n'
            '    "key_elements": ["<element1>", "..."],\n'
            '    "is_task_complete": false,\n'
            '    "confidence": 0.8\n'
            "  },\n"
            '  "plan": {\n'
            '    "action_type": "click|type|scroll|navigate|wait|none",\n'
            '    "selector": "<CSS selector or text label or null>",\n'
            '    "value": "<text to type or URL or null>",\n'
            '    "coordinates": {"x": 0, "y": 0},\n'
            '    "reasoning": "<why this action>",\n'
            '    "expected_outcome": "<what screen should show after>",\n'
            '    "confidence": 0.7\n'
            "  }\n"
            "}\n"
            "Judge 'is_task_complete' against the task goal above.\n"
            "Use coordinates only when no text selector exists (visual/unlabeled elements).\n"
            "Respond with raw JSON only — no markdown, no prose."
        )
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image", "data": image_b64, "media_type": "image/png"},
                ],
            }
        ]

        try:
            response = await self._llm.chat(
                messages=messages,
                model=self._model,
                max_tokens=MAX_TOKENS_SHORT,
                temperature=TEMPERATURE_DETERMINISTIC,
            )
        except Exception:
            logger.debug("Vision reflection LLM call failed for %s (non-fatal)", tool_name)
            return None

        try:
            await self.track_usage_and_maybe_compress(response)
        except Exception as exc:
            logger.warning(
                "Compressor quarantine: track_usage_and_maybe_compress in reflection failed "
                "for %s — %s: %s", tool_name, type(exc).__name__, exc,
            )

        try:
            import json
            raw = (response.content or "").strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            data = json.loads(raw)
            result = VisionReflection.model_validate(data)
            self._last_expected_outcome = result.plan.expected_outcome
            return result
        except Exception:
            logger.debug("Vision reflection parse/validate failed for %s (non-fatal)", tool_name)
            return None

    def inject_reflection(self, reflection: Any) -> None:
        """Append a structured observation context message to the conversation buffer.

        Stores expected_outcome for self-correction on the next screenshot.
        """
        obs = reflection.observation
        plan = reflection.plan

        completion_tag = " [TASK COMPLETE]" if obs.is_task_complete else ""
        context = (
            f"[Vision observation{completion_tag}] {obs.summary}"
            + (f" | Elements: {', '.join(obs.key_elements)}" if obs.key_elements else "")
            + f" | Confidence: {obs.confidence:.0%}"
            + f"\n[Next action plan] {plan.action_type}"
            + (f" selector={plan.selector!r}" if plan.selector else "")
            + (f" coords={plan.coordinates}" if plan.coordinates else "")
            + (f" value={plan.value!r}" if plan.value else "")
            + f" | {plan.reasoning}"
            + f"\n[Expected outcome] {plan.expected_outcome}"
        )
        self._conversation_buffer.append({"role": "system", "content": context})
        self._last_expected_outcome = plan.expected_outcome

    def reset_step_state(self) -> None:
        """Clear per-step state (called at the start of each step)."""
        self._last_expected_outcome = None
