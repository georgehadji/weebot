"""Unit tests for the OSWorld agent adapter — verify the PromptAgent contract.

These run without a VM or network: the LLM is a stub returning canned text.
They lock down the exact interface OSWorld's ``run_single_example`` depends on.
"""
from __future__ import annotations

import pytest

from weebot.osworld.agent_adapter import WeebotOSWorldAgent, parse_pyautogui_code


class _StubLLM:
    """Minimal LLM stub matching weebot's async ``chat`` -> object with .content."""

    def __init__(self, content: str):
        self._content = content
        self.calls: list[dict] = []

    async def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})

        class _Resp:
            content = self._content

        return _Resp()


def _obs(screenshot=b"\x89PNG_fake", a11y="tag\tname\tbutton\tOK"):
    return {"screenshot": screenshot, "accessibility_tree": a11y}


# ── parse_pyautogui_code ────────────────────────────────────────────

def test_parse_fenced_python_block():
    resp = "Here is the step:\n```python\npyautogui.click(100, 200)\n```"
    assert parse_pyautogui_code(resp) == ["pyautogui.click(100, 200)"]


def test_parse_bare_special_tokens():
    assert parse_pyautogui_code("DONE") == ["DONE"]
    assert parse_pyautogui_code("FAIL") == ["FAIL"]
    assert parse_pyautogui_code("WAIT") == ["WAIT"]


def test_parse_special_token_with_surrounding_prose():
    assert parse_pyautogui_code("The task is complete. DONE") == ["DONE"]


def test_parse_trailing_done_after_code():
    resp = "```python\npyautogui.press('enter')\nDONE\n```"
    assert parse_pyautogui_code(resp) == ["pyautogui.press('enter')", "DONE"]


def test_parse_empty_returns_empty_list():
    assert parse_pyautogui_code("") == []
    assert parse_pyautogui_code("no code, no token here") == []


# ── predict contract ────────────────────────────────────────────────

def test_predict_returns_response_and_action_list():
    llm = _StubLLM("```python\npyautogui.click(10, 20)\n```")
    agent = WeebotOSWorldAgent(llm=llm)

    response, actions = agent.predict("click OK", _obs())

    assert isinstance(response, str)
    assert isinstance(actions, list)
    assert actions == ["pyautogui.click(10, 20)"]


def test_predict_done_token_flows_to_actions():
    agent = WeebotOSWorldAgent(llm=_StubLLM("DONE"))
    _, actions = agent.predict("finish", _obs())
    assert actions == ["DONE"]


def test_predict_sends_screenshot_as_image():
    llm = _StubLLM("WAIT")
    agent = WeebotOSWorldAgent(llm=llm)
    agent.predict("look", _obs(screenshot=b"PNGDATA"))

    user_msg = next(m for m in llm.calls[0]["messages"] if m["role"] == "user")
    image_parts = [c for c in user_msg["content"] if c["type"] == "image_url"]
    assert image_parts, "screenshot must be attached as an image_url part"
    assert "base64," in image_parts[0]["image_url"]["url"]


def test_predict_includes_a11y_tree_text():
    llm = _StubLLM("WAIT")
    agent = WeebotOSWorldAgent(llm=llm)
    agent.predict("look", _obs(a11y="UNIQUE_TREE_MARKER"))

    user_msg = next(m for m in llm.calls[0]["messages"] if m["role"] == "user")
    text = " ".join(c.get("text", "") for c in user_msg["content"])
    assert "UNIQUE_TREE_MARKER" in text


# ── reset contract ──────────────────────────────────────────────────

def test_reset_accepts_logger_and_vm_ip():
    agent = WeebotOSWorldAgent(llm=_StubLLM("WAIT"))
    agent.predict("step", _obs())
    assert agent.observations  # trajectory populated

    # Exact call shape used by lib_run_single.run_single_example.
    agent.reset(object(), vm_ip="10.0.0.5")

    assert agent.vm_ip == "10.0.0.5"
    assert agent.observations == []
    assert agent.actions == []


def test_reset_without_args_also_works():
    agent = WeebotOSWorldAgent(llm=_StubLLM("WAIT"))
    agent.predict("step", _obs())
    agent.reset(vm_ip="1.2.3.4")
    assert agent.observations == []


# ── trajectory accumulation ─────────────────────────────────────────

def test_trajectory_accumulates_and_is_bounded_in_prompt():
    llm = _StubLLM("```python\npyautogui.scroll(-3)\n```")
    agent = WeebotOSWorldAgent(llm=llm, max_trajectory_length=2)

    for _ in range(4):
        agent.predict("scroll down", _obs())

    # All steps recorded...
    assert len(agent.observations) == 4
    # ...but the last prompt only embeds the recent window (<= 2 history pairs).
    last_messages = llm.calls[-1]["messages"]
    assistant_msgs = [m for m in last_messages if m["role"] == "assistant"]
    assert len(assistant_msgs) <= 2


# ── action space guard ──────────────────────────────────────────────

def test_rejects_unsupported_action_space():
    with pytest.raises(ValueError):
        WeebotOSWorldAgent(action_space="computer_13")
