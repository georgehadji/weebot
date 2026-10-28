"""Typed container keys: a name that carries the type of what it resolves to.

The container grew string keys (``register("llm_pool", ...)``) next to type keys
(``register(StateRepositoryPort, ...)``). A string key is untyped at every use: a
caller asking for ``"llm_pol"`` finds out at run time, and nothing says what comes
back. ``Key[T]`` fixes both without a new mechanism -- it is a hashable value, so
``Container.register`` and ``Container.get`` take it as they take any key -- and
``get`` is overloaded so a type checker sees ``Key[LLMPool]`` return ``LLMPool``
(CPL-2 / Sep plan pattern P2).

Migrate a string key by defining a ``Key`` here and replacing every use of the
string in one change; ``scripts/lint_di_wiring.py`` ratchets ``string_di_keys`` down.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.services.routing.adaptive_capability_router import (
        AdaptiveCapabilityRouter,
    )
    from weebot.application.ports.skill_store_port import SkillStorePort
    from weebot.application.ports.step_evaluator_port import StepEvaluatorPort
    from weebot.domain.services.skill_promotion_gate import SkillPromotionGate
    from weebot.application.services.session_cost import SessionCostMeter
    from weebot.application.strategies.llm_pool import LLMPool


@dataclass(frozen=True)
class Key[T]:
    """A container binding name that remembers the type it resolves to."""

    name: str

    def __str__(self) -> str:
        return self.name


LLM_POOL: Key[LLMPool] = Key("llm_pool")
SESSION_COST_METER: Key[SessionCostMeter] = Key("session_cost_meter")
# The skill store live steps count candidate-skill uses against (RecordSkillUseHandler).
LEARNING_SKILL_STORE: Key[SkillStorePort] = Key("learning_skill_store")
# One model router for every step executor, so what it learns is shared and stored.
ACR_ROUTER: Key[AdaptiveCapabilityRouter] = Key("acr_router")
# Per-step progress evaluator; resolves to None while WEEBOT_STEP_EVALUATOR is off.
STEP_EVALUATOR: Key[StepEvaluatorPort | None] = Key("step_evaluator")
# Chain-of-verification veto on candidate -> trusted; None while its flag is off.
SKILL_PROMOTION_GATE: Key[SkillPromotionGate | None] = Key("skill_promotion_gate")
