"""Sub-agent flow construction for Container.

Holds the flow factory the multi-agent tools spawn sub-agents with. The tool
registry calls ``_build_plan_act_flow_for_session`` directly as its fallback
factory for ``debate``, ``swarm``, ``dispatch_parallel_tasks`` and
``workflow_orchestrator`` (``weebot/tools/tool_registry.py``).

This module used to be the "web clone" configuration: ``configure_web_clone()``
registered three tool bindings -- ``browser_inspector_tool``,
``dispatch_agents_tool``, ``workflow_orchestrator_tool`` -- and nothing ever
called it, so all three were dead (phase 2.3 of
``tasks/specs/arch_audit_2026_09_remediation_plan.md``). The tool registry
builds those tools itself. What was live all along, and broken, is the
factory below -- see its docstring.
"""

from __future__ import annotations


class AgentToolsMixin:
    """The flow factory multi-agent tools spawn sub-agents with."""

    def _build_plan_act_flow_for_session(self, session):
        """A PlanActFlow for one sub-agent session.

        Every flow this built could not run. PlanningState refuses to plan
        without a mediator (since 2b6f679, 2026-06-06) and this config passed
        none -- the same defect as the web API's flows, fixed in phase 2.1,
        on a path the DI census could not see because the tool registry
        reaches it by calling this private method on an ad-hoc Container
        rather than by resolving a key. It also asked for "state_repo" and
        "event_bus" by string; both are bound by type, so both were always
        None, and the mediator's handlers load the session from the state
        repository by id.
        """
        from weebot.application.cqrs.mediator import Mediator
        from weebot.application.flows.plan_act_flow import PlanActFlow
        from weebot.application.models.plan_act_flow_config import PlanActFlowConfig
        from weebot.application.ports.llm_port import LLMPort
        from weebot.application.ports.state_repo_port import StateRepositoryPort
        from weebot.config.constants import SUBAGENT_MAX_STEPS
        from weebot.config.harness.schema import HarnessConfig

        registry = self.get("tool_registry")

        def _flow_factory(s):
            return self._build_plan_act_flow_for_session(s)

        tools = registry.create_tool_collection(
            "admin", llm_port=self._maybe_get(LLMPort), flow_factory=_flow_factory
        )
        cfg = PlanActFlowConfig(
            llm=self.get(LLMPort),
            tools=tools,
            session=session,
            mediator=self.get(Mediator),
            state_repo=self._maybe_get(StateRepositoryPort),
            # Deliberately None, as it has always been in effect: the string
            # lookup this replaced resolved to nothing. A sub-agent publishing
            # on the global bus would stream every sub-agent event into the
            # web UI's global socket -- a product change, not a wiring fix.
            event_bus=None,
            max_steps=SUBAGENT_MAX_STEPS,
            logger=self._maybe_get_str("structured_logger"),
            skill_retriever=self._maybe_get_str("skill_retriever"),
            skill_distiller=self._maybe_get_str("skill_distiller"),
            skill_review_gate=self._maybe_get_str("skill_review_gate"),
            harness_config=self._maybe_get(HarnessConfig),
            tool_registry=registry,
            mcp_bridge=self._maybe_get_str("mcp_bridge"),
            native_tool_selector=self._maybe_get_str("native_tool_selector"),
        )
        return PlanActFlow(cfg)
