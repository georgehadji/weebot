"""Unit tests for ApifyActorTool and create_apify_preset_tools."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from weebot.infrastructure.external_service_integration import ServiceResponse, ServiceStatus
from weebot.tools.apify_actor_tool import ApifyActorTool
from weebot.tools.apify_presets import create_apify_preset_tools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_service(items=None, success=True, error=None):
    svc = MagicMock()
    resp = ServiceResponse(
        success=success,
        data=items if success else None,
        error=error,
        status_code=200 if success else 400,
        execution_time_ms=42.0,
    )
    svc.execute = AsyncMock(return_value=resp)
    svc.health_check = AsyncMock(
        return_value=ServiceStatus.HEALTHY if success else ServiceStatus.UNAVAILABLE
    )
    return svc


def _make_tool(actor_id="apify/test-actor", service=None):
    return ApifyActorTool(
        name="apify_test",
        description="Test actor",
        parameters={"type": "object", "properties": {}},
        actor_id=actor_id,
        apify_service=service or _mock_service(items=[{"result": "ok"}]),
    )


# ---------------------------------------------------------------------------
# Tests: execute
# ---------------------------------------------------------------------------

class TestApifyActorToolExecute:
    @pytest.mark.asyncio
    async def test_success_returns_items(self):
        items = [{"url": "https://example.com", "title": "Example"}]
        tool = _make_tool(service=_mock_service(items=items))

        result = await tool.execute(run_input={"queries": "test"})

        assert result.success
        assert result.data["items"] == items
        assert result.data["count"] == 1
        assert result.data["actor_id"] == "apify/test-actor"

    @pytest.mark.asyncio
    async def test_output_is_json_preview(self):
        items = [{"x": i} for i in range(60)]  # 60 items, only 50 in preview
        tool = _make_tool(service=_mock_service(items=items))

        result = await tool.execute(run_input={})

        import json
        preview = json.loads(result.output)
        assert len(preview) == 50  # capped at 50

    @pytest.mark.asyncio
    async def test_actor_failure_returns_error_result(self):
        tool = _make_tool(
            service=_mock_service(success=False, error="Actor timed out")
        )
        result = await tool.execute(run_input={})

        assert not result.success
        assert "Actor timed out" in result.error

    @pytest.mark.asyncio
    async def test_service_exception_returns_error_result(self):
        svc = MagicMock()
        svc.execute = AsyncMock(side_effect=RuntimeError("network down"))
        tool = _make_tool(service=svc)

        result = await tool.execute(run_input={})

        assert not result.success
        assert "network down" in result.error

    @pytest.mark.asyncio
    async def test_list_response_used_directly(self):
        items = [{"a": 1}, {"b": 2}]
        svc = MagicMock()
        svc.execute = AsyncMock(
            return_value=ServiceResponse(success=True, data=items, execution_time_ms=10.0)
        )
        tool = _make_tool(service=svc)

        result = await tool.execute(run_input={})

        assert result.data["items"] == items

    @pytest.mark.asyncio
    async def test_dict_response_wraps_in_list(self):
        svc = MagicMock()
        svc.execute = AsyncMock(
            return_value=ServiceResponse(
                success=True, data={"title": "page"}, execution_time_ms=10.0
            )
        )
        tool = _make_tool(service=svc)

        result = await tool.execute(run_input={})

        assert result.data["items"] == [{"title": "page"}]

    @pytest.mark.asyncio
    async def test_kwargs_forwarded_as_payload(self):
        svc = _mock_service(items=[])
        tool = _make_tool(service=svc)

        await tool.execute(startUrls=[{"url": "https://x.com"}])

        call_kwargs = svc.execute.call_args.kwargs
        assert call_kwargs["run_input"] == {"startUrls": [{"url": "https://x.com"}]}

    @pytest.mark.asyncio
    async def test_memory_mbytes_forwarded(self):
        svc = _mock_service(items=[])
        tool = _make_tool(service=svc)

        await tool.execute(run_input={}, memory_mbytes=512)

        call_kwargs = svc.execute.call_args.kwargs
        assert call_kwargs["memory_mbytes"] == 512


# ---------------------------------------------------------------------------
# Tests: health_check
# ---------------------------------------------------------------------------

class TestApifyActorToolHealthCheck:
    @pytest.mark.asyncio
    async def test_healthy_when_service_healthy(self):
        tool = _make_tool(service=_mock_service())
        assert await tool.health_check()

    @pytest.mark.asyncio
    async def test_unhealthy_when_service_unavailable(self):
        tool = _make_tool(service=_mock_service(success=False))
        assert not await tool.health_check()


# ---------------------------------------------------------------------------
# Tests: preset tools
# ---------------------------------------------------------------------------

class TestApifyPresets:
    def test_returns_10_tools(self):
        tools = create_apify_preset_tools(_mock_service())
        assert len(tools) == 10

    def test_all_tools_are_apify_actor_tools(self):
        tools = create_apify_preset_tools(_mock_service())
        for tool in tools:
            assert isinstance(tool, ApifyActorTool)

    def test_tool_names_are_unique(self):
        tools = create_apify_preset_tools(_mock_service())
        names = [t.name for t in tools]
        assert len(names) == len(set(names))

    def test_all_have_actor_ids(self):
        tools = create_apify_preset_tools(_mock_service())
        for tool in tools:
            assert "/" in tool.actor_id, f"{tool.name} actor_id should contain /"

    def test_all_have_descriptions(self):
        tools = create_apify_preset_tools(_mock_service())
        for tool in tools:
            assert len(tool.description) > 10, f"{tool.name} has too short description"

    @pytest.mark.asyncio
    async def test_preset_tools_are_executable(self):
        svc = _mock_service(items=[{"result": "data"}])
        tools = create_apify_preset_tools(svc)
        result = await tools[0].execute(run_input={})
        assert result.success
