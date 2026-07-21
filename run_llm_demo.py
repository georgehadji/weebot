"""Run flow via direct module import, bypassing python -m Click issue."""
import sys, os, asyncio, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(override=True)

from weebot.application.di import Container
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.services.model_selection import ModelSelectionService
from weebot.interfaces.cli.agent_runner import AgentRunner

TASK = (
    "Read README.md to understand weebot. Then create Output/dashboard_llm.html: "
    "an HTML dashboard with dark theme CSS that shows: "
    "(1) live date/time via JavaScript, "
    "(2) 3-4 bullets summarizing weebot's capabilities (from README.md), "
    "(3) list all .py filenames in weebot/tools/. "
    "Keep it simple — write the file and report the path."
)

async def main():
    container = Container()
    container.configure_defaults()
    state_repo = container.get(StateRepositoryPort)

    model_service = ModelSelectionService()
    llm = model_service.create_llm_adapter("deepseek/deepseek-chat")

    runner = AgentRunner(
        llm=llm,
        state_repo=state_repo,
        model="deepseek/deepseek-chat",
    )

    sid = str(uuid.uuid4())[:8]
    print(f"[{sid}] Running flow with DeepSeek...", flush=True)
    events = runner.run_flow(task=TASK, session_id=sid)

    step_count = 0
    async for evt in events:
        step_count += 1
        etype = getattr(evt, "event_type", "?")
        msg = getattr(evt, "message", "")[:150]
        print(f"[{sid}] {etype}: {msg}", flush=True)

    print(f"[{sid}] Done ({step_count} events)", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
