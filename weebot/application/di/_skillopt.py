"""SkillOpt bindings mixin for Container — largest extraction (~200 lines)."""
from __future__ import annotations

from typing import Any, Optional

from weebot.config.model_refs import MODEL_DI_SKILLOPT


class SkillOptMixin:
    """SkillOpt flow builder + scorer + optimizer bindings."""

    def configure_skillopt(
        self, *, db_path="./weebot_sessions.db",
        optimizer_model=MODEL_DI_SKILLOPT,
        target_model=None, harness="direct_chat",
    ):
        self.configure_defaults(db_path=db_path, default_model=target_model)
        self.register("optimizer_llm", lambda: self._create_llm_by_id(optimizer_model))
        self.register("optimizer_port", self._create_optimizer_agent)
        self.register("skill_store", lambda: self._create_skill_store(db_path))
        self.register("trajectory_repo", lambda: self._create_trajectory_repo(db_path))
        self.register("validation_gate", lambda: self._create_validation_gate(harness))
        self.register("evolution_tracker", self._create_evolution_tracker)

    def build_skill_opt_flow(
        self, skill_name, train_tasks, validation_tasks=None,
        output_path="best_skill.md", epochs=4, steps_per_epoch=5,
        batch_size=40, use_planning=False,
    ):
        from weebot.application.flows.skill_opt_flow import SkillOptFlow
        mediator = self.build_mediator()
        gate = self._maybe_get_str("validation_gate")
        if gate is not None:
            mediator.add_pipeline_behavior(gate)
        from weebot.application.cqrs.handlers import register_skillopt_handlers
        from weebot.application.services.trajectory_builder import TrajectoryBuilder
        from weebot.application.ports.llm_port import LLMPort
        from weebot.application.ports.optimizer_port import OptimizerPort
        scoring_port = self.get(OptimizerPort)
        llm = self._maybe_get(LLMPort)
        trajectory_builder = TrajectoryBuilder(llm=llm)
        self.register("trajectory_builder", trajectory_builder)
        register_skillopt_handlers(
            mediator, self.get("skill_store"), scoring_port,
            trajectory_builder=trajectory_builder,
            evolution_tracker=self._maybe_get_str("evolution_tracker"),
            llm_port=llm,
        )
        flow = SkillOptFlow(
            skill_name=skill_name, train_tasks=train_tasks,
            validation_tasks=validation_tasks, output_path=output_path,
            epochs=epochs, steps_per_epoch=steps_per_epoch,
            batch_size=batch_size, use_planning=use_planning,
            mediator=mediator,
            skill_store=self.get("skill_store"),
            optimizer_llm=self.get("optimizer_llm"),
            target_factory=self._create_target_flow_factory(db_path),
            scorer=self._create_scorer(harness),
            trajectory_repo=self.get("trajectory_repo"),
            evolution_tracker=self._maybe_get_str("evolution_tracker"),
        )
        return flow

    def _create_llm_by_id(self, model_id: str):
        from weebot.config.model_registry import ModelProvider
        from weebot.infrastructure.adapters.llm.adapter_factory import create_adapter
        provider = ModelProvider.from_model_name(model_id).value
        return create_adapter(provider, model=model_id)

    def _create_optimizer_agent(self):
        from weebot.application.agents.optimizer_agent import OptimizerAgent
        from weebot.application.ports.llm_port import LLMPort
        return OptimizerAgent(llm=self.get("optimizer_llm"))

    @staticmethod
    def _create_skill_store(db_path: str):
        from weebot.infrastructure.persistence.skill_store import SkillStore
        return SkillStore(db_path=db_path)

    @staticmethod
    def _create_trajectory_repo(db_path: str):
        from weebot.infrastructure.persistence.trajectory_repo import (
            TrajectoryRepository,
        )
        return TrajectoryRepository(db_path=db_path)

    @staticmethod
    def _create_evolution_tracker():
        from weebot.application.services.evolution_tracker import EvolutionTracker
        return EvolutionTracker()

    def _create_validation_gate(self, harness: str):
        from weebot.application.cqrs.behaviors.validation_gate import (
            ValidationGateBehavior,
        )
        scoring_port = self._maybe_get_str("scoring_port")
        scorer = scoring_port or self._maybe_get_str("optimizer_port")
        return ValidationGateBehavior(
            baseline_score=0.0,
            score_delta_threshold=0.01,
            scorer=scorer,
            harness=harness,
        )

    def _create_target_flow_factory(self, db_path: str):
        """Return a callable that builds a PlanActFlow for SkillOpt rollouts."""
        from weebot.application.flows.plan_act_flow import PlanActFlow
        from weebot.application.ports.llm_port import LLMPort
        from weebot.application.ports.state_repo_port import StateRepositoryPort
        from weebot.application.ports.event_bus_port import EventBusPort
        from weebot.config.harness.schema import HarnessConfig

        class _LazyLLM:
            def __init__(self, container):
                self._c = container
            def __getattr__(self, name):
                llm = self._c._maybe_get(LLMPort)
                if llm is None:
                    raise RuntimeError("LLMPort not configured in SkillOpt target factory")
                return getattr(llm, name)

        def factory(session):
            from weebot.application.models.plan_act_flow_config import PlanActFlowConfig
            cfg = PlanActFlowConfig(
                llm=self.get(LLMPort),
                tools=None,
                session=session,
                state_repo=self._maybe_get(StateRepositoryPort),
                event_bus=self._maybe_get(EventBusPort),
                max_steps=5,
                logger=self._maybe_get_str("structured_logger"),
                skill_retriever=self._maybe_get_str("skill_retriever"),
                skill_distiller=self._maybe_get_str("skill_distiller"),
                code_reviewer=self._maybe_get_str("code_reviewer"),
                harness_config=self._maybe_get(HarnessConfig),
            )
            return PlanActFlow(cfg)
        return factory

    def _create_scorer(self, harness: str):
        """Build a scoring function for SkillOpt validation."""
        from weebot.application.ports.scoring_port import ScoringPort

        def fallback_scorer(target, actual, options=None):
            if target == actual:
                return 1.0
            if isinstance(target, str) and isinstance(actual, str):
                target_words = set(target.lower().split())
                actual_words = set(actual.lower().split())
                if not target_words:
                    return 0.0
                return len(target_words & actual_words) / len(target_words)
            return 0.0

        return fallback_scorer
