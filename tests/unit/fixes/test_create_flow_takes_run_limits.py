"""``create_flow`` takes the run limits, so callers need not set private attributes.

Found by review of the auto_execute fix: the script restored its limits by assigning
``flow._max_iterations`` and ``flow._max_step_repetitions`` after the flow was built,
because ``create_flow`` had no way to pass them to ``PlanActFlowConfig``.
"""

from __future__ import annotations

from weebot.application.di import Container
from weebot.application.models.tool_collection import ToolCollection
from weebot.application.ports.llm_port import LLMPort
from weebot.domain.models.session import Session


def test_create_flow_passes_the_limits_to_the_flow():
    container = Container()
    container.configure_defaults()
    flow = container.get("create_flow")(
        flow_type="plan_act",
        session=Session(id="s-limits"),
        llm=container.get(LLMPort),
        tools=ToolCollection(),
        max_iterations=80,
        max_step_repetitions=5,
    )
    assert flow._max_iterations == 80
    assert flow._max_step_repetitions == 5
