"""Stress tests for the MCP High-Probability Enhancement follow-up.

Three complex run profiles designed to expose concurrency, failure-recovery,
and budget-enforcement problems in Weebot.

Usage:
    python scripts/stress_tests.py concurrent-sessions
    python scripts/stress_tests.py adversarial-longhaul
    python scripts/stress_tests.py max-catalog-budget

Environment variables:
    STRESS_CONCURRENT_SESSIONS   number of parallel sessions (default: 2)
    STRESS_LONGHAUL_TURNS        number of adversarial turns (default: 5)
    WEEBOT_ENABLE_X_MCP          enable MCP server bridging (default: 0)
    MCP_SCOPED_AGGREGATION       enable external MCP tool scoping (default: true)
    MCP_SCOPE_NATIVE_TOOLS       enable native tool scoping (default: false)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
from collections.abc import Awaitable, Callable
from typing import Any

# Ensure the repo root is on the path when running from scripts/
sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from weebot.application.di import Container
from weebot.application.flows.mcp_scope import apply_mcp_tool_scope
from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.models.plan_act_flow_config import PlanActFlowConfig
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.session import Session


def _build_config(container: Container, prompt: str, role: str = "admin") -> PlanActFlowConfig:
    """Build a PlanActFlowConfig from the shared DI container."""
    llm = container.get(LLMPort)
    event_bus = container.get(EventBusPort)
    state_repo = container.get(StateRepositoryPort)
    registry = container.get("tool_registry")
    bridge = container.build_mcp_bridge()
    native_selector = container._create_native_tool_selector()

    return PlanActFlowConfig(
        llm=llm,
        tools=None,  # built from registry by the flow
        session=Session(title=f"stress-{prompt[:30]}", input=prompt),
        event_bus=event_bus,
        state_repo=state_repo,
        agent_role=role,
        tool_registry=registry,
        mcp_bridge=bridge,
        native_tool_selector=native_selector,
        max_iterations=int(os.environ.get("STRESS_MAX_ITERATIONS", "3")),
    )


async def _run_single_session(
    i: int,
    container: Container,
    prompt: str,
    timeout: float,
) -> dict[str, Any]:
    """Run one PlanActFlow session and return structured result metadata."""
    cfg = _build_config(container, f"{prompt} (session {i})")
    flow = PlanActFlow(config=cfg)
    try:
        await asyncio.wait_for(_drain_events(flow.run(prompt)), timeout=timeout)
        return {"index": i, "status": "ok", "result": None}
    except Exception as exc:
        return {"index": i, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}


async def _drain_events(gen):
    """Consume an async generator of AgentEvents to completion."""
    async for _event in gen:
        pass


def _new_container() -> Container:
    """Create and configure a fresh DI container."""
    c = Container()
    c.configure_defaults()
    return c


async def concurrent_sessions() -> int:
    """Run multiple PlanActFlow sessions in parallel to stress shared state."""
    count = int(os.environ.get("STRESS_CONCURRENT_SESSIONS", "2"))
    timeout = float(os.environ.get("STRESS_SESSION_TIMEOUT", "120"))
    prompt = (
        "analyze the weebot codebase for security issues, "
        "then search the web for the latest CVEs you find"
    )

    print(f"Running {count} concurrent PlanActFlow sessions (timeout={timeout}s each)...")
    print("WARNING: each session may call paid LLM APIs. Press Ctrl-C to abort.\n")

    # Share a single container so all sessions use the same registry / bridge.
    container = _new_container()
    bridge = container.build_mcp_bridge()
    try:
        await bridge.initialize()
    except Exception as exc:
        print(f"MCP bridge initialization failed: {exc}")

    results = await asyncio.gather(
        *(_run_single_session(i, container, prompt, timeout) for i in range(count)),
        return_exceptions=True,
    )

    ok = 0
    failed = 0
    for r in results:
        if isinstance(r, Exception):
            failed += 1
            print(f"session ?: EXCEPTION — {type(r).__name__}: {r}")
        else:
            if r["status"] == "ok":
                ok += 1
            else:
                failed += 1
            print(f"session {r['index']}: {r['status']} — {r.get('error', '')}")

    print(f"\nSummary: {ok}/{count} ok, {failed}/{count} failed")
    return 0 if failed == 0 else 1


async def adversarial_longhaul() -> int:
    """Run a sequence of adversarial prompts to stress failure handling."""
    turns = int(os.environ.get("STRESS_LONGHAUL_TURNS", "5"))
    timeout = float(os.environ.get("STRESS_SESSION_TIMEOUT", "60"))

    prompts = [
        "run python code that intentionally raises a ValueError",
        "execute bash command 'this_command_definitely_does_not_exist_12345'",
        "search the web with an empty query",
        "view the file /this/path/does/not/exist.txt",
        "use the file_editor composite tool without providing the required path argument",
        "create a plan with zero steps and run it",
        "ask for a summary of a session that was never started",
    ]

    print(f"Running {turns} adversarial turns (timeout={timeout}s each)...")
    print("WARNING: each turn may call paid LLM APIs. Press Ctrl-C to abort.\n")

    container = _new_container()
    bridge = container.build_mcp_bridge()
    try:
        await bridge.initialize()
    except Exception as exc:
        print(f"MCP bridge initialization failed: {exc}")

    failures = 0
    for turn in range(turns):
        prompt = random.choice(prompts)
        cfg = _build_config(container, prompt)
        flow = PlanActFlow(config=cfg)
        try:
            await asyncio.wait_for(_drain_events(flow.run(prompt)), timeout=timeout)
            print(f"turn {turn}: ok       — {prompt[:60]}")
        except Exception as exc:
            failures += 1
            print(f"turn {turn}: FAILED   — {type(exc).__name__}: {exc} — {prompt[:60]}")

    print(f"\nSummary: {turns - failures}/{turns} ok, {failures}/{turns} failed")
    return 0 if failures == 0 else 1


async def max_catalog_budget() -> int:
    """Stress the <=12 tools-per-turn budget with scoping enabled."""
    queries = [
        "search the web for Python async best practices",
        "edit a file to add a new function",
        "run a security audit on the codebase",
        "summarize recent agent activity events",
        "create a composite workflow that reads a file and then searches the web",
    ]

    print("Running max-catalog budget enforcement stress test...")
    print("Requires MCP_SCOPED_AGGREGATION=true and MCP_SCOPE_NATIVE_TOOLS=true")
    print("WARNING: may call paid LLM APIs. Press Ctrl-C to abort.\n")

    container = _new_container()
    bridge = container.build_mcp_bridge()
    try:
        await bridge.initialize()
    except Exception as exc:
        print(f"MCP bridge initialization failed: {exc}")

    # Build a minimal flow instance just to feed apply_mcp_tool_scope.
    cfg = _build_config(container, queries[0])
    flow = PlanActFlow(config=cfg)

    budget_violations = 0
    for q in queries:
        try:
            scoped_tools = await apply_mcp_tool_scope(flow, q)
            count = len(scoped_tools) if scoped_tools else 0
            status = "ok" if count <= 12 else "BUDGET VIOLATION"
            if count > 12:
                budget_violations += 1
            print(f"query: {q[:50]:50} tools: {count:3} [{status}]")
        except Exception as exc:
            print(f"query: {q[:50]:50} tools: N/A [ERROR: {type(exc).__name__}: {exc}]")

    print(f"\nSummary: {budget_violations}/{len(queries)} budget violations")
    return 0 if budget_violations == 0 else 1


COMMANDS: dict[str, Callable[[], Awaitable[int]]] = {
    "concurrent-sessions": concurrent_sessions,
    "adversarial-longhaul": adversarial_longhaul,
    "max-catalog-budget": max_catalog_budget,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Weebot stress tests")
    parser.add_argument(
        "command",
        choices=list(COMMANDS.keys()),
        help="Stress scenario to run",
    )
    args = parser.parse_args(argv)

    return asyncio.run(COMMANDS[args.command]())


if __name__ == "__main__":
    raise SystemExit(main())
