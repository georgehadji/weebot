"""ModelSelector — extracted from PlanActFlow for context-aware model switching."""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ModelSelector:
    """Dynamic model selection based on context size and session state."""

    def __init__(self, default_model: Optional[str] = None):
        self._default_model = default_model

    def maybe_switch_for_context(self, session, current_model: Optional[str], context_aware_enabled: bool) -> Optional[str]:
        """Dynamically select model based on context size if enabled.

        Returns:
            New model ID if switch recommended, None otherwise.
        """
        # Delegate to ContextSwitcher service
        from weebot.application.services.context_switcher import ContextSwitcher
        switcher = ContextSwitcher(llm=None, event_bus=None)
        return switcher.maybe_switch_model_for_context(
            session=session,
            current_model=current_model,
            context_aware_enabled=context_aware_enabled,
        )

    def update_agents(self, model: str, skill_prompt, facts, episodic_memory) -> tuple:
        """Create updated agent instances for a new model.

        Returns:
            Tuple of (planner, executor_kwargs)
        """
        from weebot.application.agents.planner import PlannerAgent
        planner = PlannerAgent(
            llm=None,
            event_bus=None,
            model=model,
            skill_prompt=skill_prompt,
            facts=facts,
            episodic_memory=episodic_memory,
        )
        return planner
