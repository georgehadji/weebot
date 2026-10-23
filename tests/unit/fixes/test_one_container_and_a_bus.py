"""The web process has one DI container, and CLI flows publish on its bus (F55, F56).

The web lifespan built its own `Container()`, while `build_tools`,
`create_flow` and the gateways use `factories.shared_container()`: sub-agent
events went to the second container's bus and never reached the WebSocket
broadcaster. CLI `flow run` / `flow resume` built AgentRunner with no event
bus, so no domain events and no skill-gap subscription fired.
"""

from __future__ import annotations

import inspect


def test_the_web_lifespan_uses_the_shared_container():
    from weebot.interfaces.web import main

    src = inspect.getsource(main.lifespan)
    assert "shared_container()" in src and "Container()" not in src.replace(
        "shared_container()", ""
    )


def test_cli_run_and_resume_pass_the_event_bus():
    from cli.commands import flow

    for fn in (flow.flow_run, flow.flow_resume):
        src = inspect.getsource(fn.callback)
        assert "event_bus=" in src, fn.name


async def test_agent_runner_close_tears_the_tools_down():
    # flow run / resume never tore their tools down, so Apify's aiohttp sessions
    # and the shared browser were left open at exit ("Unclosed client session").
    from unittest.mock import AsyncMock, MagicMock

    from weebot.interfaces.cli.agent_runner import AgentRunner

    runner = AgentRunner(llm=MagicMock(), state_repo=MagicMock())
    tools = MagicMock()
    tools.teardown = AsyncMock()
    runner._tools = tools
    await runner.close()
    tools.teardown.assert_awaited_once()
