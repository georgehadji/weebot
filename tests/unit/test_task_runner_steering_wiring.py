"""Tests for T1.4 — steering reaches PlanActFlow via create_plan_act_factory.

SteeringPort and InMemorySteeringAdapter were already fully implemented
and PlanActFlow already polls steering between steps (see steering_port.py,
plan_act_flow.py). The only gap was create_plan_act_factory silently
dropping any steering argument — this test proves the factory now passes
it through, so the /sessions/{id}/steer endpoint has somewhere to deliver.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from weebot.application.services.task_runner import TaskRunner
from weebot.infrastructure.adapters.steering_adapter import InMemorySteeringAdapter


def test_create_plan_act_factory_forwards_steering_to_flow():
    state_repo = MagicMock()
    runner = TaskRunner(state_repo=state_repo)
    steering = InMemorySteeringAdapter()
    llm = MagicMock()
    tools = MagicMock()

    factory = runner.create_plan_act_factory(llm=llm, tools=tools, steering=steering)

    session = MagicMock()
    session.id = "sess-steer-1"
    flow = factory(session)

    assert flow._steering is steering


def test_create_plan_act_factory_defaults_steering_to_none():
    state_repo = MagicMock()
    runner = TaskRunner(state_repo=state_repo)
    llm = MagicMock()
    tools = MagicMock()

    factory = runner.create_plan_act_factory(llm=llm, tools=tools)

    session = MagicMock()
    session.id = "sess-steer-2"
    flow = factory(session)

    assert flow._steering is None
