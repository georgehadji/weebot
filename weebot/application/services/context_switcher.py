"""Context-aware model switching — dynamically selects models based on context size.

Extracted from PlanActFlow to isolate the model-selection concern into its own
service with a single responsibility.
"""
from __future__ import annotations

import logging
from typing import Optional

from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.agents.planner import PlannerAgent
from weebot.application.services.context_tokenizer import ContextTokenizer
from weebot.core.model_cascade_config import select_model_by_tokens
from weebot.domain.models.session import Session

logger = logging.getLogger(__name__)


class ContextSwitcher:
    """Handles dynamic model switching based on context size.

    Implements the MEMORY_ARTICLE recommendation to use sparse-attention
    models (DeepSeek DSA) for long contexts (50K+ tokens) and cheaper
    models for short contexts.

    Usage:
        switcher = ContextSwitcher(llm, event_bus)
        new_model = switcher.maybe_switch_model_for_context(session, current_model)
        if new_model:
            planner = switcher.update_agents(new_model, ...)
    """

    def __init__(
        self,
        llm: LLMPort,
        event_bus: Optional[EventBusPort] = None,
    ):
        self._llm = llm
        self._event_bus = event_bus
        self._tokenizer = ContextTokenizer()

    def maybe_switch_model_for_context(
        self,
        session: Session,
        current_model: Optional[str],
        context_aware_enabled: bool = True,
    ) -> Optional[str]:
        """Dynamically select model based on context size if enabled.

        Uses sparse-attention models for long contexts (50K+ tokens)
        and cheaper models for short contexts.

        Args:
            session: The current session whose context size is estimated.
            current_model: The currently active model ID.
            context_aware_enabled: Whether dynamic switching is enabled.

        Returns:
            New model ID if switch recommended, None otherwise.
        """
        if not context_aware_enabled:
            return None

        estimated_tokens = self._tokenizer.estimate_session_tokens(session)
        config = select_model_by_tokens("coding", estimated_tokens)

        if config.id != current_model:
            logger.info(
                "Context-aware model selection: %s -> %s for ~%d tokens",
                current_model, config.id, estimated_tokens,
            )
            return config.id

        return None

    def update_agents_with_model(
        self,
        model: str,
        skill_prompt: Optional[str] = None,
        facts: Optional[list[str]] = None,
        episodic_memory=None,
    ) -> PlannerAgent:
        """Rebuild the PlannerAgent with a new model.

        Args:
            model: The new model ID to use.
            skill_prompt: Optional skill prompt for the planner.
            facts: Session facts to inject.
            episodic_memory: Optional episodic memory instance.

        Returns:
            A new PlannerAgent configured with the given model.
        """
        return PlannerAgent(
            llm=self._llm,
            event_bus=self._event_bus,
            model=model,
            skill_prompt=skill_prompt,
            facts=facts or [],
            episodic_memory=episodic_memory,
        )
