"""Phase 1 unit tests — LLM-backed skill distillation."""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from weebot.application.services.autonomous_learning import (
    AutonomousSkillCreator,
    _parse_distiller_response,
)
from weebot.domain.models.skill import Skill, TrustTier


# ── _parse_distiller_response ─────────────────────────────────────────────────


class TestParseDistillerResponse:
    def _make_json(self, **kwargs) -> str:
        defaults = {
            "worth_creating": True,
            "name": "deploy-docker-image",
            "description": "Deploy a Docker image to a remote host.",
            "content": "## When to Use\n...\n## Procedure\n1. Step one\n2. Step two\n## Notes\n- Note",
        }
        defaults.update(kwargs)
        return json.dumps(defaults)

    def test_valid_response_returns_tuple(self):
        result = _parse_distiller_response(self._make_json())
        assert result is not None
        name, desc, content = result
        assert name == "deploy-docker-image"
        assert "Deploy" in desc
        assert "## Procedure" in content

    def test_not_worth_creating_returns_none(self):
        raw = self._make_json(worth_creating=False)
        assert _parse_distiller_response(raw) is None

    def test_missing_json_returns_none(self):
        assert _parse_distiller_response("no json here") is None

    def test_invalid_json_returns_none(self):
        assert _parse_distiller_response("{bad json}") is None

    def test_empty_name_returns_none(self):
        raw = self._make_json(name="", content="some content")
        assert _parse_distiller_response(raw) is None

    def test_empty_content_returns_none(self):
        raw = self._make_json(name="my-skill", content="")
        assert _parse_distiller_response(raw) is None

    def test_name_is_sanitised_to_kebab(self):
        raw = self._make_json(name="My Complex Skill Name!!")
        result = _parse_distiller_response(raw)
        assert result is not None
        name, _, _ = result
        assert " " not in name
        assert "!" not in name

    def test_name_truncated_to_50_chars(self):
        raw = self._make_json(name="a" * 60, content="body")
        result = _parse_distiller_response(raw)
        assert result is not None
        name, _, _ = result
        assert len(name) <= 50

    def test_json_embedded_in_text(self):
        raw = 'Here is the analysis:\n' + self._make_json() + '\nEnd.'
        result = _parse_distiller_response(raw)
        assert result is not None


# ── AutonomousSkillCreator ────────────────────────────────────────────────────


class TestAutonomousSkillCreatorInit:
    def test_no_args_constructs_ok(self):
        creator = AutonomousSkillCreator()
        assert creator._llm is None
        assert creator._skill_store is None

    def test_llm_and_store_stored(self):
        llm = MagicMock()
        store = MagicMock()
        creator = AutonomousSkillCreator(llm=llm, skill_store=store)
        assert creator._llm is llm
        assert creator._skill_store is store


class TestAnalyzeSession:
    def _make_creator(self, llm_response_json: str | None = None):
        # spec=LLMPort guards against mocking a non-existent method (e.g. the
        # earlier `complete()` bug that a bare AsyncMock would have hidden).
        from weebot.application.ports.llm_port import LLMPort

        llm = AsyncMock(spec=LLMPort)
        if llm_response_json is not None:
            resp = MagicMock()
            resp.content = llm_response_json
            llm.chat = AsyncMock(return_value=resp)
        else:
            llm.chat = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        store = AsyncMock()
        store.save = AsyncMock()
        return AutonomousSkillCreator(llm=llm, skill_store=store), store

    GOOD_TRAJECTORY = "\n".join([
        "Task: Deploy microservice to production Kubernetes cluster",
        "Steps completed: 5, tool calls: 8",
        "  - [s1] Built Docker image with multi-stage build to reduce final image size",
        "  - [s2] Pushed image to private container registry with appropriate tags",
        "  - [s3] Updated Kubernetes deployment manifest with new image tag and resource limits",
        "  - [s4] Applied manifest via kubectl apply, verified rollout began successfully",
        "  - [s5] Verified rollout status via kubectl rollout status, confirmed 3/3 replicas ready",
        "  - [s6] Checked application logs to confirm no startup errors",
        "  - [s7] Updated deployment documentation with new image version and release notes",
    ])

    GOOD_LLM_RESPONSE = json.dumps({
        "worth_creating": True,
        "name": "k8s-deploy-microservice",
        "description": "Deploy a microservice to Kubernetes via Docker.",
        "content": "## When to Use\nWhen deploying to Kubernetes.\n## Procedure\n1. Build\n2. Push\n3. Deploy\n## Notes\n- Use kubectl",
    })

    @pytest.mark.asyncio
    async def test_returns_quarantined_skill(self):
        creator, _ = self._make_creator(self.GOOD_LLM_RESPONSE)
        skill = await creator.analyze_session("sess-001", self.GOOD_TRAJECTORY)
        assert skill is not None
        assert isinstance(skill, Skill)
        assert skill.metadata.trust == "quarantined"

    @pytest.mark.asyncio
    async def test_provenance_set_correctly(self):
        creator, _ = self._make_creator(self.GOOD_LLM_RESPONSE)
        skill = await creator.analyze_session("sess-001", self.GOOD_TRAJECTORY)
        assert skill is not None
        assert skill.metadata.provenance.origin == "distilled"
        assert skill.metadata.provenance.session_id == "sess-001"
        assert skill.metadata.provenance.created_at is not None

    @pytest.mark.asyncio
    async def test_skill_saved_to_store(self):
        creator, store = self._make_creator(self.GOOD_LLM_RESPONSE)
        await creator.analyze_session("sess-001", self.GOOD_TRAJECTORY)
        store.save.assert_awaited_once()
        saved_skill = store.save.call_args[0][0]
        assert saved_skill.name == "k8s-deploy-microservice"

    @pytest.mark.asyncio
    async def test_too_short_trajectory_returns_none(self):
        creator, store = self._make_creator(self.GOOD_LLM_RESPONSE)
        skill = await creator.analyze_session("sess-001", "short")
        assert skill is None
        store.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_llm_returns_none(self):
        creator = AutonomousSkillCreator(llm=None, skill_store=AsyncMock())
        skill = await creator.analyze_session("sess-001", self.GOOD_TRAJECTORY)
        assert skill is None

    @pytest.mark.asyncio
    async def test_llm_error_returns_none(self):
        creator, store = self._make_creator(llm_response_json=None)
        skill = await creator.analyze_session("sess-001", self.GOOD_TRAJECTORY)
        assert skill is None
        store.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_not_worth_creating_returns_none(self):
        not_worth = json.dumps({"worth_creating": False, "name": "", "description": "", "content": ""})
        creator, store = self._make_creator(not_worth)
        skill = await creator.analyze_session("sess-001", self.GOOD_TRAJECTORY)
        assert skill is None
        store.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_store_save_failure_is_non_blocking(self):
        creator, store = self._make_creator(self.GOOD_LLM_RESPONSE)
        store.save = AsyncMock(side_effect=RuntimeError("DB down"))
        # Should not raise
        skill = await creator.analyze_session("sess-001", self.GOOD_TRAJECTORY)
        assert skill is not None  # skill is still returned even if store fails


# ── Config field presence ─────────────────────────────────────────────────────


class TestConfigField:
    def test_plan_act_flow_config_has_skill_distiller(self):
        import dataclasses
        from weebot.application.models.plan_act_flow_config import PlanActFlowConfig
        fields = {f.name for f in dataclasses.fields(PlanActFlowConfig)}
        assert "skill_distiller" in fields

    def test_plan_act_flow_stores_skill_distiller(self):
        from unittest.mock import MagicMock, patch
        from weebot.application.flows.plan_act_flow import PlanActFlow
        from weebot.application.models.plan_act_flow_config import PlanActFlowConfig
        from weebot.domain.models.session import Session

        session = Session(id="test-session")
        distiller = MagicMock()
        cfg = PlanActFlowConfig(
            llm=MagicMock(),
            tools=None,
            session=session,
            skill_distiller=distiller,
        )
        flow = PlanActFlow(cfg)
        assert flow._skill_distiller is distiller
