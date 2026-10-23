"""A step executor with no role (no SOUL.md profile) uses the executor cascade.

`create_flow` passes the profile name as the agent role, so the default flow
had role None and its steps ran `_DEFAULT_ROLE_CASCADE`, which falls back to a
premium model, not `ROLE_MODEL_CONFIG["executor"]`.
"""

from __future__ import annotations

from weebot.application.agents.executor import ExecutorAgent
from weebot.application.models.tool_collection import ToolCollection


def test_no_role_means_the_executor_role_for_the_cascade():
    agent = ExecutorAgent(llm=object(), tools=ToolCollection())
    assert agent._cascade._agent_role == "executor"


def test_a_named_role_is_kept():
    agent = ExecutorAgent(llm=object(), tools=ToolCollection(), agent_role="coder")
    assert agent._cascade._agent_role == "coder"
