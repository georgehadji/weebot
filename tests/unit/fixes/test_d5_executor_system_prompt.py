"""D5 (plan 2026-10-29): one executor system-prompt loader, and it finds the prompt.

``_base.py`` and ``_tool_executor.py`` each had a loader and a fallback. The second read
``weebot.config/executor_system_prompt.txt``, which does not exist, so the end-of-step
summary always ran on a three-line stub. Both now use ``_system_prompt.py``.
"""

from __future__ import annotations

from pathlib import Path

from weebot.application.agents.executor import _base, _tool_executor
from weebot.application.agents.executor._system_prompt import load_executor_system_prompt

_PROMPT = Path("weebot/config/prompts/executor_system.txt").read_text(encoding="utf-8")


def test_the_loader_returns_the_prompt_file():
    assert load_executor_system_prompt() == _PROMPT


def test_the_step_and_the_summary_use_the_same_loader():
    assert _base.load_executor_system_prompt is load_executor_system_prompt
    assert _tool_executor.load_executor_system_prompt is load_executor_system_prompt
