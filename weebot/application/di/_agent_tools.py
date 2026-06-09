"""Multi-agent tool bindings mixin for Container.

Web-clone bindings (BrowserInspector + DispatchAgents + WorkflowOrchestrator).
"""
from __future__ import annotations


class AgentToolsMixin:
    """Web-clone multi-agent tool bindings."""

    def configure_web_clone(self, *, db_path="./weebot_sessions.db", default_model=None):
        self.configure_defaults(db_path=db_path, default_model=default_model)
        self.register("browser_inspector_tool", self._create_browser_inspector)
        self.register("dispatch_agents_tool", self._create_dispatch_agents)
        self.register("workflow_orchestrator_tool", self._create_workflow_orchestrator)

    def _create_browser_inspector(self):
        from weebot.tools.browser_inspector import BrowserInspectorTool
        return BrowserInspectorTool()

    def _create_dispatch_agents(self):
        from weebot.tools.dispatch_agents import DispatchAgentsTool
        from weebot.application.ports.state_repo_port import StateRepositoryPort
        state_repo = self._maybe_get(StateRepositoryPort)
        def _flow_factory(session):
            return self._build_plan_act_flow_for_session(session)
        return DispatchAgentsTool(flow_factory=_flow_factory, state_repo=state_repo)

    def _create_workflow_orchestrator(self):
        from weebot.tools.workflow_orchestrator import WorkflowOrchestratorTool
        from weebot.application.ports.state_repo_port import StateRepositoryPort
        state_repo = self._maybe_get(StateRepositoryPort)
        def _flow_factory(session):
            return self._build_plan_act_flow_for_session(session)
        return WorkflowOrchestratorTool(flow_factory=_flow_factory, state_repo=state_repo)

    def _build_plan_act_flow_for_session(self, session):
        from weebot.application.flows.plan_act_flow import PlanActFlow
        from weebot.application.models.plan_act_flow_config import PlanActFlowConfig
        from weebot.tools.tool_registry import RoleBasedToolRegistry
        from weebot.config.constants import SUBAGENT_MAX_STEPS
        from weebot.application.ports.llm_port import LLMPort
        registry = RoleBasedToolRegistry()
        tools = registry.create_tool_collection("admin", llm_port=self._maybe_get(LLMPort))
        cfg = PlanActFlowConfig(
            llm=self.get(LLMPort),
            tools=tools,
            session=session,
            state_repo=self._maybe_get("state_repo"),
            event_bus=self._maybe_get("event_bus"),
            max_steps=SUBAGENT_MAX_STEPS,
            logger=self._maybe_get_str("structured_logger"),
            skill_retriever=self._maybe_get_str("skill_retriever"),
        )
        return PlanActFlow(cfg)
