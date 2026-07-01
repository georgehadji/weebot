"""OSWorld Agent Adapter — weebot as an OSWorld-compatible agent.

Plugs weebot's resilient LLM stack into the OSWorld evaluation loop as a
drop-in replacement for ``mm_agents.agent.PromptAgent``. It honors the exact
contract that ``lib_run_single.run_single_example`` depends on:

    response, actions = agent.predict(instruction, obs)   # actions: list[str]
    for action in actions:
        obs, reward, done, info = env.step(action, ...)    # action: pyautogui code
    ...
    agent.reset(runtime_logger, vm_ip=env.vm_ip)

``actions`` is a **list of pyautogui code strings** (or the special tokens
``WAIT`` / ``DONE`` / ``FAIL``), matching ``action_space="pyautogui"``.

The paper (OSWorld, Xie et al. 2024) frames each task as a POMDP: the agent
observes a screenshot + accessibility (a11y) tree and emits an executable
action, capped at ~15 steps, scored by an execution-based evaluator. This
adapter implements the agent side of that loop.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import re
from typing import Any, Optional

logger = logging.getLogger("desktopenv.agent")

# Special control tokens in the OSWorld pyautogui action space.
_SPECIAL_ACTIONS = ("WAIT", "DONE", "FAIL")

# System prompt instructing the VLM to emit pyautogui code, mirroring
# OSWorld's SYS_PROMPT_IN_BOTH_OUT_CODE contract closely enough that the
# shared parser (parse_pyautogui_code) can extract executable actions.
_SYSTEM_PROMPT = """You are an autonomous agent controlling a real computer to complete a task.

At each step you receive a screenshot of the current screen and (optionally) an
accessibility tree describing on-screen elements with their coordinates. Decide
the single next action and return it as Python code using the `pyautogui`
library, wrapped in a fenced code block.

Rules:
- Return exactly ONE fenced ```python ... ``` block per step.
- Use real pixel coordinates from the screenshot / accessibility tree.
- Common calls: pyautogui.click(x, y), pyautogui.doubleClick(x, y),
  pyautogui.rightClick(x, y), pyautogui.moveTo(x, y),
  pyautogui.dragTo(x, y), pyautogui.write('text', interval=0.05),
  pyautogui.press('enter'), pyautogui.hotkey('ctrl', 'c'),
  pyautogui.scroll(amount).
- You may chain a few related calls in the one block when they form a single
  logical step.
- When the task is fully complete, return the single word DONE (no code block).
- When the task is impossible/infeasible, return the single word FAIL.
- When you must wait for the screen to update, return the single word WAIT.

Respond with the code block or one of DONE / FAIL / WAIT — no extra prose."""


def parse_pyautogui_code(response: str) -> list[str]:
    """Extract executable actions from a model response.

    Mirrors the semantics of OSWorld's ``parse_code_from_string`` so the
    adapter is a faithful drop-in and is unit-testable without OSWorld on the
    path. Returns a list of pyautogui code strings and/or the special tokens
    WAIT / DONE / FAIL, in order. Returns ``[]`` when nothing parses.
    """
    if not response:
        return []

    # Normalise semicolon-separated one-liners (OSWorld does the same).
    normalized = "\n".join(
        line.strip() for line in response.split(";") if line.strip()
    )

    # A bare special token is itself a valid action.
    if normalized.strip() in _SPECIAL_ACTIONS:
        return [normalized.strip()]

    # Capture ```...``` or ```python ...``` fenced blocks.
    blocks = re.findall(r"```(?:\w+\s+)?(.*?)```", normalized, re.DOTALL)

    actions: list[str] = []
    for block in blocks:
        block = block.strip()
        if block in _SPECIAL_ACTIONS:
            actions.append(block)
        elif block.split("\n")[-1] in _SPECIAL_ACTIONS:
            # A trailing DONE/FAIL/WAIT after some code — keep both.
            lines = block.split("\n")
            if len(lines) > 1:
                actions.append("\n".join(lines[:-1]))
            actions.append(lines[-1])
        else:
            actions.append(block)

    # Fallback: a response that is just a special token without fences but with
    # surrounding whitespace/prose.
    if not actions:
        for token in _SPECIAL_ACTIONS:
            if re.search(rf"\b{token}\b", normalized):
                return [token]

    return actions


class WeebotOSWorldAgent:
    """OSWorld-compatible agent backed by weebot's resilient LLM stack.

    Drop-in replacement for ``mm_agents.agent.PromptAgent``: same
    ``predict`` / ``reset`` / ``action_space`` surface consumed by
    ``lib_run_single.run_single_example``.
    """

    def __init__(
        self,
        model: str = "openai/gpt-4o",
        max_tokens: int = 1500,
        top_p: float = 0.9,
        temperature: float = 1.0,
        action_space: str = "pyautogui",
        observation_type: str = "screenshot_a11y_tree",
        max_trajectory_length: int = 3,
        a11y_char_budget: int = 6000,
        llm: Any | None = None,
    ) -> None:
        if action_space != "pyautogui":
            # The adapter emits pyautogui code; computer_13 is not supported.
            raise ValueError(
                f"WeebotOSWorldAgent only supports action_space='pyautogui', "
                f"got {action_space!r}"
            )
        self.model = model
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.temperature = temperature
        self.action_space = action_space
        self.observation_type = observation_type
        self.max_trajectory_length = max_trajectory_length
        self.a11y_char_budget = a11y_char_budget

        # Injected LLM (for tests) or lazily constructed weebot adapter.
        self._llm = llm
        self.vm_ip: Optional[str] = None

        # Trajectory state (parallel lists, like PromptAgent).
        self.observations: list[dict] = []
        self.actions: list[list[str]] = []
        self.responses: list[str] = []

    # ── OSWorld agent interface ─────────────────────────────────────

    def predict(self, instruction: str, obs: dict[str, Any]) -> tuple[str, list[str]]:
        """Return ``(response_text, actions)`` for the current observation.

        ``actions`` is a list of pyautogui code strings (or WAIT/DONE/FAIL),
        exactly what ``run_single_example`` iterates over and feeds to
        ``env.step``.
        """
        messages = self._build_messages(instruction, obs)
        response_text = self._call_llm(messages)
        actions = parse_pyautogui_code(response_text)

        # Record trajectory (bounded by callers via max_trajectory_length).
        self.observations.append(obs)
        self.actions.append(actions)
        self.responses.append(response_text)

        return response_text, actions

    def reset(self, _logger: Any | None = None, vm_ip: str | None = None, **kwargs: Any) -> None:
        """Reset trajectory between tasks. Signature matches PromptAgent.reset."""
        global logger
        if _logger is not None:
            logger = _logger
        self.vm_ip = vm_ip
        self.observations.clear()
        self.actions.clear()
        self.responses.clear()

    # ── Message construction ────────────────────────────────────────

    def _build_messages(self, instruction: str, obs: dict[str, Any]) -> list[dict]:
        """Build the chat payload: system + recent trajectory + current obs."""
        system_text = (
            _SYSTEM_PROMPT
            + "\n\nYou are asked to complete the following task: "
            + instruction
        )
        messages: list[dict] = [
            {"role": "system", "content": [{"type": "text", "text": system_text}]}
        ]

        # Recent trajectory (last N obs/action pairs), oldest first.
        if self.max_trajectory_length > 0 and self.observations:
            recent_obs = self.observations[-self.max_trajectory_length:]
            recent_actions = self.actions[-self.max_trajectory_length:]
            for past_obs, past_actions in zip(recent_obs, recent_actions):
                messages.append(self._obs_to_user_message(past_obs, history=True))
                messages.append(
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "\n".join(past_actions) or "WAIT"}
                        ],
                    }
                )

        # Current observation.
        messages.append(self._obs_to_user_message(obs, history=False))
        return messages

    def _obs_to_user_message(self, obs: dict[str, Any], *, history: bool) -> dict:
        """Render one observation (a11y tree text + screenshot image)."""
        content: list[dict] = []

        a11y = self._format_a11y_tree(obs.get("accessibility_tree"))
        prompt = (
            "Given the screenshot"
            + (" and accessibility tree" if a11y else "")
            + " below, what is the next action?"
        )
        if a11y:
            prompt += f"\n\nAccessibility tree:\n{a11y}"
        content.append({"type": "text", "text": prompt})

        screenshot = obs.get("screenshot")
        if screenshot:
            b64 = self._encode_screenshot(screenshot)
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{b64}",
                        "detail": "high",
                    },
                }
            )
        return {"role": "user", "content": content}

    @staticmethod
    def _encode_screenshot(screenshot: Any) -> str:
        """Return a base64 PNG string from raw bytes or an existing b64 string."""
        if isinstance(screenshot, (bytes, bytearray)):
            return base64.b64encode(screenshot).decode()
        # Already a base64 string (possibly a data URL).
        text = str(screenshot)
        return text.split("base64,", 1)[-1]

    def _format_a11y_tree(self, a11y_tree: Any) -> str:
        """Render the a11y tree as text within the char budget."""
        if not a11y_tree:
            return ""
        if isinstance(a11y_tree, (bytes, bytearray)):
            text = a11y_tree.decode(errors="replace")
        else:
            text = str(a11y_tree)
        if len(text) > self.a11y_char_budget:
            text = text[: self.a11y_char_budget] + "\n[... truncated]"
        return text

    # ── LLM invocation ──────────────────────────────────────────────

    def _ensure_llm(self) -> Any:
        """Lazily construct weebot's resilient OpenAI-compatible adapter."""
        if self._llm is None:
            from weebot.infrastructure.adapters.llm.openai_adapter import OpenAIAdapter

            self._llm = OpenAIAdapter(api_key=None, default_model=self.model)
        return self._llm

    def _call_llm(self, messages: list[dict]) -> str:
        """Run the async LLM call from this synchronous interface."""
        llm = self._ensure_llm()
        coro = llm.chat(
            messages=messages,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        response = self._run_coro(coro)
        return (getattr(response, "content", None) or "").strip()

    @staticmethod
    def _run_coro(coro: Any) -> Any:
        """Execute a coroutine, whether or not a loop is already running.

        The OSWorld runner calls ``predict`` synchronously (no running loop),
        so ``asyncio.run`` is the normal path. If a loop is already running we
        execute on a dedicated background loop to avoid re-entrancy errors.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        # A loop is already running in this thread — run the coroutine on a
        # fresh loop in a worker thread to avoid "loop already running".
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
