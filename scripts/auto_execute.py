"""Auto-execute a weebot task with plan auto-approval.

Usage: python scripts/auto_execute.py "task description"
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from weebot.application.di import Container
from weebot.application.models.plan_act_flow_config import PlanActFlowConfig
from weebot.domain.models.session import Session, SessionStatus
from weebot.domain.models.event import WaitForUserEvent, DoneEvent, ErrorEvent, StepEvent, MessageEvent


async def run_until_complete(task: str):
    container = Container()
    container.configure_defaults()
    
    # Build tools + flow config
    from weebot.interfaces.factories import build_tools as _build_tools
    session = Session.create_new()
    tools = await _build_tools(role="admin")
    flow_cfg = PlanActFlowConfig(
        llm=container.get("llm"),
        tools=tools,
        session=session,
        event_bus=container.get("event_bus"),
        state_repo=container.get("state_repo"),
        skill_retriever=container.get("skill_retriever"),
        model=os.environ.get("WEEBOT_MODEL"),
        max_step_repetitions=5,
        max_iterations=80,
    )
    
    from weebot.application.flows.plan_act_flow import PlanActFlow
    
    flow = PlanActFlow(flow_cfg)
    session_id = session.id
    current_answer = task
    
    while True:
        try:
            async for event in flow.run(current_answer):
                if isinstance(event, DoneEvent):
                    print(f"\n[DONE] Flow completed successfully")
                    await flow.teardown()
                    return
                elif isinstance(event, ErrorEvent):
                    print(f"\n[ERROR] {event.error}")
                elif isinstance(event, WaitForUserEvent):
                    print(f"\n[AUTO-APPROVE] Plan ready — auto-approving...")
                    # Save the session so it's in WAITING state
                    state_repo = container.get("state_repo")
                    if state_repo:
                        await state_repo.save_session(flow._session)
                    
                    # Create a new flow for resume with "approve" as answer
                    await flow.teardown()
                    
                    # Resume with the existing session
                    flow_session = flow._session
                    flow_session = flow_session.set_status(SessionStatus.WAITING)
                    
                    resume_cfg = PlanActFlowConfig(
                        llm=container.get("llm"),
                        tools=tools,
                        session=flow_session,
                        event_bus=container.get("event_bus"),
                        state_repo=container.get("state_repo"),
                        skill_retriever=container.get("skill_retriever"),
                        model=os.environ.get("WEEBOT_MODEL"),
                        max_step_repetitions=5,
                        max_iterations=80,
                    )
                    flow = PlanActFlow(resume_cfg)
                    current_answer = "approve"
                    break  # break inner loop, resume with new flow
                elif isinstance(event, StepEvent):
                    status = getattr(event, 'status', '?')
                    desc = getattr(event, 'description', '')[:100]
                    print(f"  [{status.value}] {desc}")
                elif isinstance(event, MessageEvent):
                    role = getattr(event, 'role', '')
                    msg = getattr(event, 'message', '')[:150]
                    if msg:
                        print(f"  [{role}] {msg}")
            
            else:
                # Loop completed without break — flow finished
                await flow.teardown()
                return
                
        except Exception as exc:
            print(f"\n[EXCEPTION] {type(exc).__name__}: {exc}")
            await flow.teardown()
            return


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        "Build a FastAPI endpoint that returns weather stats for a city. "
        "Follow TDD: write tests first (RED), implement the endpoint (GREEN), "
        "then refactor (CLEAN). The endpoint should call wttr.in via HTTP, "
        "parse the response, and return JSON with temperature, humidity, "
        "and conditions. Include error handling for invalid cities."
    )
    print(f"Task: {task[:120]}...")
    asyncio.run(run_until_complete(task))
