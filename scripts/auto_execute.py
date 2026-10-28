"""Auto-execute a weebot task with plan auto-approval.

Usage: python scripts/auto_execute.py "task description"
"""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from weebot.application.di import Container
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.session import Session, SessionStatus
from weebot.domain.models.event import WaitForUserEvent, DoneEvent, ErrorEvent, StepEvent, MessageEvent


# An unattended run gets more room than the defaults (50 iterations, 3 repetitions).
MAX_ITERATIONS = 80
MAX_STEP_REPETITIONS = 5


def build_flow(container: Container, session: Session, tools):
    """A PlanActFlow from the container, with the script's own run limits.

    The container keys its services by port type, and ``create_flow`` adds the
    mediator and state repository itself; building PlanActFlow by hand left out the
    mediator that PlanningState needs.
    """
    return container.get("create_flow")(
        flow_type="plan_act",
        session=session,
        llm=container.get(LLMPort),
        tools=tools,
        event_bus=container.get(EventBusPort),
        model=os.environ.get("WEEBOT_MODEL"),
        max_iterations=MAX_ITERATIONS,
        max_step_repetitions=MAX_STEP_REPETITIONS,
    )


def done_message(event: DoneEvent) -> str:
    """The closing line for *event*: a run with failed steps is not a success."""
    if event.status == "failed":
        return "[DONE] Flow finished with failed steps"
    return "[DONE] Flow completed successfully"


async def run_until_complete(task: str):
    container = Container()
    container.configure_defaults()
    
    # Build tools + flow config
    from weebot.interfaces.factories import build_tools as _build_tools
    # Session has no create_new(); the id must be set here.
    session = Session(id=str(uuid.uuid4()), task=task)
    tools = await _build_tools(role="admin")
    flow = build_flow(container, session, tools)
    session_id = session.id
    current_answer = task
    
    while True:
        try:
            async for event in flow.run(current_answer):
                if isinstance(event, DoneEvent):
                    print(f"\n{done_message(event)}")
                    await flow.teardown()
                    return
                elif isinstance(event, ErrorEvent):
                    print(f"\n[ERROR] {event.error}")
                elif isinstance(event, WaitForUserEvent):
                    print(f"\n[AUTO-APPROVE] Plan ready — auto-approving...")
                    # Save the session so it's in WAITING state
                    await container.get(StateRepositoryPort).save_session(flow._session)
                    
                    # Create a new flow for resume with "approve" as answer
                    await flow.teardown()
                    
                    # Resume with the existing session
                    flow_session = flow._session
                    flow_session = flow_session.set_status(SessionStatus.WAITING)
                    
                    flow = build_flow(container, flow_session, tools)
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
