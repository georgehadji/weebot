"""SkillOpt bindings mixin for Container — largest extraction (~200 lines)."""

from __future__ import annotations


from weebot.config.model_refs import MODEL_DI_SKILLOPT


class SkillOptMixin:
    """SkillOpt flow builder + scorer + optimizer bindings."""

    def configure_skillopt(
        self,
        *,
        db_path="./weebot_sessions.db",
        optimizer_model=MODEL_DI_SKILLOPT,
        target_model=None,
        harness="direct_chat",
    ):
        self.configure_defaults(db_path=db_path, default_model=target_model)
        self.register("optimizer_llm", lambda: self._create_llm_by_id(optimizer_model))
        self.register("optimizer_port", self._create_optimizer_agent)
        self.register("skill_store", lambda: self._create_skill_store(db_path))
        self.register("trajectory_repo", lambda: self._create_trajectory_repo(db_path))
        self.register("validation_gate", lambda: self._create_validation_gate(harness))
        self.register("evolution_tracker", self._create_evolution_tracker)
        self.register("validation_runner", lambda: self._create_validation_runner(db_path))
        self.register("transfer_flow_factory", lambda: self._create_transfer_flow_factory(db_path))
        self.register("harness_optimization_target", self._create_harness_optimization_target)

    def build_skill_opt_flow(
        self,
        skill_name,
        train_tasks,
        validation_tasks=None,
        output_path="best_skill.md",
        epochs=4,
        steps_per_epoch=5,
        batch_size=40,
        use_planning=False,
        use_archive_search: bool = False,
        use_evaluator_slot: bool = False,
        db_path: str = "./weebot_sessions.db",
        harness: str = "direct_chat",
    ):
        from weebot.application.flows.skill_opt_flow import SkillOptFlow

        mediator = self.build_mediator()
        gate = self._maybe_get_str("validation_gate")
        if gate is not None:
            mediator.add_pipeline_behavior(gate)
        from weebot.application.cqrs.handlers import register_skillopt_handlers
        from weebot.application.services.trajectory_builder import TrajectoryBuilder
        from weebot.application.ports.llm_port import LLMPort
        from weebot.application.ports.state_repo_port import StateRepositoryPort

        # "optimizer_port" is registered under a string key (line ~19 above),
        # not the OptimizerPort type — self.get(OptimizerPort) raised KeyError
        # unconditionally, since Container.get() does not cross-resolve
        # between type and string keys.
        scoring_port = self.get("optimizer_port")
        llm = self._maybe_get(LLMPort)
        trajectory_builder = TrajectoryBuilder(llm=llm)
        self.register_instance("trajectory_builder", trajectory_builder)
        register_skillopt_handlers(
            mediator,
            scoring_port=scoring_port,
            state_repo=self._maybe_get(StateRepositoryPort),
            trajectory_builder=trajectory_builder,
            skill_store=self.get("skill_store"),
            trajectory_repo=self.get("trajectory_repo"),
            validation_runner=self.get("validation_runner"),
            flow_factory=self.get("transfer_flow_factory"),
            llm_port=llm,
            harness_target=self._maybe_get_str("harness_optimization_target"),
        )
        # ── Optional evaluator co-evolution (R3) ─────────────────
        evaluator_kwargs = {}
        if use_evaluator_slot:
            from weebot.domain.models.evaluator_state import EvaluatorState
            from weebot.application.services.evaluator_selector import EvaluatorSelector
            from weebot.application.services.selective_erasure import SelectiveErasure
            from weebot.application.services.adversarial_pool import AdversarialPool
            from weebot.application.ports.llm_port import LLMPort

            evaluator_llm = self._maybe_get(LLMPort)
            evaluator_kwargs["evaluator_slot"] = EvaluatorState(
                evaluator_id="skillopt-evaluator",
                evaluator_type="scorer",
                prompt="Score the agent output from 0.0 to 1.0.",
            )
            evaluator_kwargs["evaluator_selector"] = EvaluatorSelector(llm=evaluator_llm)
            evaluator_kwargs["selective_erasure"] = SelectiveErasure()
            evaluator_kwargs["adversarial_pool"] = AdversarialPool()

        # ── Optional archive search (R5) ───────────────────────────
        archive_kwargs = {}
        if use_archive_search:
            from weebot.application.services.thompson_sampler import ThompsonSampler

            archive_kwargs["use_archive_search"] = True
            archive_kwargs["thompson_sampler"] = ThompsonSampler(
                optimizer=self.get("optimizer_port"),
                skill_store=self.get("skill_store"),
                trajectory_repo=self.get("trajectory_repo"),
            )

        from weebot.application.ports.event_bus_port import EventBusPort

        flow = SkillOptFlow(
            skill_name=skill_name,
            train_tasks=train_tasks,
            validation_tasks=validation_tasks,
            output_path=output_path,
            epochs=epochs,
            steps_per_epoch=steps_per_epoch,
            batch_size=batch_size,
            use_planning=use_planning,
            mediator=mediator,
            skill_store=self.get("skill_store"),
            optimizer=scoring_port,
            target_flow_factory=self._create_target_flow_factory(db_path),
            event_bus=self._maybe_get(EventBusPort),
            trajectory_repo=self.get("trajectory_repo"),
            evolution_tracker=self._maybe_get_str("evolution_tracker"),
            **evaluator_kwargs,
            **archive_kwargs,
        )
        return flow

    def _create_llm_by_id(self, model_id: str):
        from weebot.config.model_registry import ModelProvider
        from weebot.infrastructure.adapters.llm.adapter_factory import create_adapter

        provider = ModelProvider.from_model_name(model_id).value
        return create_adapter(provider, model=model_id)

    def _create_optimizer_agent(self):
        from weebot.application.agents.optimizer_agent import OptimizerAgent

        return OptimizerAgent(optimizer_llm=self.get("optimizer_llm"))

    @staticmethod
    def _create_skill_store(db_path: str):
        from weebot.infrastructure.persistence.skill_store import SkillStore

        return SkillStore(db_path=db_path)

    @staticmethod
    def _create_trajectory_repo(db_path: str):
        from weebot.infrastructure.persistence.trajectory_repo import TrajectoryRepository

        return TrajectoryRepository(db_path=db_path)

    def _create_evolution_tracker(self):
        """EvolutionTracker narrates epoch-boundary skill evolution — the same
        optimizer-tier reasoning role as OptimizerAgent, so it shares the
        optimizer_llm binding rather than the target model."""
        from weebot.application.services.evolution_tracker import EvolutionTracker

        return EvolutionTracker(llm=self.get("optimizer_llm"))

    @staticmethod
    def _create_harness_optimization_target():
        """Build the HarnessOptimizationTarget for ApplyHarnessEditsHandler.

        Resolves the active harness YAML the same way FactoriesMixin's
        ``_create_harness_config`` does (WEEBOT_HARNESS_VERSION, default
        v0.2.0), so edits are applied against whatever harness is actually
        live rather than a hardcoded path. Construction only — the handler
        calls ``target.load()`` itself on first use.
        """
        import os
        from pathlib import Path
        from weebot.application.services.harness_optimization_target import (
            HarnessOptimizationTarget,
        )

        version = os.getenv("WEEBOT_HARNESS_VERSION", "v0.2.0")
        harness_path = Path("weebot") / "config" / "harness" / f"{version}.yaml"
        return HarnessOptimizationTarget(harness_path=harness_path)

    def _create_validation_gate(self, harness: str):
        """Build the pipeline behavior that gates ApplySkillEditsCommand.

        ValidationGateBehavior.__init__ only accepts validation_runner —
        it calls runner.validate(candidate_content=..., validation_task_ids=...,
        baseline_score=None) internally and reads .passed/.score_delta off the
        ValidationResult. baseline_score/score_delta_threshold/scorer/harness
        are not fields on that class; this previously raised TypeError on
        every resolution, so the gate never engaged for a single command.
        `harness` is accepted for interface-stability with configure_skillopt's
        call site but is not consumed here — weebot has one execution harness
        (see _create_transfer_flow_factory).
        """
        from weebot.application.cqrs.behaviors.validation_gate import ValidationGateBehavior

        return ValidationGateBehavior(validation_runner=self._maybe_get_str("validation_runner"))

    def _create_target_flow_factory(self, db_path: str):
        """Return a callable that builds a PlanActFlow for SkillOpt rollouts."""
        from weebot.application.flows.plan_act_flow import PlanActFlow
        from weebot.application.ports.llm_port import LLMPort
        from weebot.application.ports.state_repo_port import StateRepositoryPort
        from weebot.application.ports.event_bus_port import EventBusPort
        from weebot.application.cqrs.mediator import Mediator
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
                mediator=self._maybe_get(Mediator),
                max_steps=5,
                logger=self._maybe_get_str("structured_logger"),
                skill_retriever=self._maybe_get_str("skill_retriever"),
                skill_distiller=self._maybe_get_str("skill_distiller"),
                skill_review_gate=self._maybe_get_str("skill_review_gate"),
                code_reviewer=self._maybe_get_str("code_reviewer"),
                harness_config=self._maybe_get(HarnessConfig),
            )
            return PlanActFlow(cfg)

        return factory

    def _create_validation_runner(self, db_path: str):
        """Build the ValidationRunner used by ValidateSkillHandler.

        Reuses TaskRunner (already bound by configure_defaults) and the same
        rollout factory SkillOptFlow itself uses. Scoring reuses TaskScorer's
        existing no-expected-answer fallback (session-status heuristic) by
        passing it a WeebotTask with an empty sample tuple — validation task
        ids here are raw prompts, not WeebotTask objects with known answers.
        """
        from weebot.application.services.validation_runner import ValidationRunner
        from weebot.application.services.task_runner import TaskRunner

        async def scoring_fn(session):
            from weebot.application.harness.scorer import TaskScorer
            from weebot.domain.models.benchmark_task import WeebotTask

            task = WeebotTask(task_id=session.id, description="", samples=())
            return await TaskScorer.score(session, task)

        return ValidationRunner(
            task_runner=self.get(TaskRunner),
            flow_factory=self._create_target_flow_factory(db_path),
            scoring_fn=scoring_fn,
        )

    def _create_transfer_flow_factory(self, db_path: str):
        """Return a callable for ValidateTransferHandler's cross-model rollouts.

        Signature matches the handler's call site exactly:
        ``factory(session=..., model=..., harness=..., skill_content=...)``.
        weebot has one execution harness (PlanActFlow / "direct_chat"); other
        harness identifiers are rejected explicitly rather than silently
        running as direct_chat, so an unsupported harness fails the command
        instead of producing a misleading transfer score.
        """
        from weebot.application.ports.llm_port import LLMPort
        from weebot.application.ports.state_repo_port import StateRepositoryPort
        from weebot.application.ports.event_bus_port import EventBusPort
        from weebot.application.cqrs.mediator import Mediator
        from weebot.config.harness.schema import HarnessConfig

        def factory(session, model=None, harness="direct_chat", skill_content=None):
            if harness not in (None, "direct_chat"):
                raise ValueError(
                    f"transfer validation harness '{harness}' is not supported — "
                    "weebot only executes rollouts through PlanActFlow (direct_chat)"
                )
            from weebot.application.flows.plan_act_flow import PlanActFlow
            from weebot.application.models.plan_act_flow_config import PlanActFlowConfig

            llm = self._create_llm_by_id(model) if model else self._maybe_get(LLMPort)
            cfg = PlanActFlowConfig(
                llm=llm,
                tools=None,
                session=session,
                state_repo=self._maybe_get(StateRepositoryPort),
                event_bus=self._maybe_get(EventBusPort),
                mediator=self._maybe_get(Mediator),
                max_steps=5,
                logger=self._maybe_get_str("structured_logger"),
                skill_retriever=None,  # transfer eval controls skill content directly
                skill_distiller=self._maybe_get_str("skill_distiller"),
                skill_review_gate=self._maybe_get_str("skill_review_gate"),
                code_reviewer=self._maybe_get_str("code_reviewer"),
                harness_config=self._maybe_get(HarnessConfig),
            )
            return PlanActFlow(cfg)

        return factory
