"""OSWorld Agent Adapter — weebot as an OSWorld-compatible agent.

Plugs weebot's VLM-based executor into the OSWorld evaluation loop.
Receives OSWorld observations (screenshots + a11y trees) and produces
pyautogui actions in the format expected by DesktopEnv.step().

Usage with OSWorld run.py:
    from weebot.osworld.agent_adapter import WeebotOSWorldAgent
    agent = WeebotOSWorldAgent(model="openai/gpt-4o")
    # Then pass to lib_run_single.run_single_example(agent, env, ...)

This adapter implements the same interface as mm_agents.agent.PromptAgent
so it can be used as a drop-in replacement in the OSWorld benchmark.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from io import BytesIO
from typing import Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# OSWorld action space → weebot tool mapping
_ACTION_MAP = {
    "MOVE_TO": "move_mouse",
    "CLICK": "click",
    "DOUBLE_CLICK": "double_click",
    "RIGHT_CLICK": "click",        # weebot: click with button="right"
    "DRAG_TO": "drag",
    "SCROLL": "scroll",
    "TYPING": "type",
    "PRESS": "press_key",
    "KEY_DOWN": "key_down",
    "KEY_UP": "key_up",
    "HOTKEY": "press_key",         # weebot: press_key with modifiers
    "WAIT": "wait",
    "FAIL": "fail",
    "DONE": "done",
}

# OSWorld Scroll dy → weebot direction
# Positive dy = scroll up (away from user) → weebot scroll positive
# Negative dy = scroll down (toward user) → weebot scroll negative


class WeebotOSWorldAgent:
    """OSWorld-compatible agent backed by weebot's VLM and desktop tools.

    Implements the same predict() interface as OSWorld's PromptAgent
    so it can be dropped into run.py as a replacement.
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
    ):
        self.model = model
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.temperature = temperature
        self.action_space = action_space
        self.observation_type = observation_type
        self.max_trajectory_length = max_trajectory_length

        # Lazy-init: created on first call to avoid DI container overhead
        self._llm = None
        self._tools = None
        self._executor = None
        self._conversation_history: list[dict] = []

    async def _ensure_initialized(self):
        """Lazy-init the weebot LLM and tools."""
        if self._llm is not None:
            return

        # Minimal DI setup — avoid full container for benchmark speed
        from weebot.infrastructure.adapters.llm.openai_adapter import OpenAIAdapter
        from weebot.tools.base import ToolCollection
        from weebot.tools.computer_use import ComputerUseTool
        from weebot.tools.screen_tool import ScreenCaptureBaseTool

        self._llm = OpenAIAdapter(
            api_key=None,  # Loaded from env
            model=self.model,
        )

        self._tools = ToolCollection(
            ComputerUseTool(),
            ScreenCaptureBaseTool(),
        )

    # ── OSWorld Agent Interface ─────────────────────────────────────

    def predict(
        self,
        instruction: str,
        obs: dict[str, Any],
        max_tokens: int | None = None,
        chat_mode: bool = False,
    ) -> tuple[str, list]:
        """OSWorld-compatible predict() — returns (action_str, flags).

        This is the primary interface OSWorld calls in its agent loop.

        Args:
            instruction: The task description.
            obs: Observation dict with 'screenshot' (PNG bytes) and
                 optionally 'accessibility_tree' (XML string).
            max_tokens: Override for max tokens.
            chat_mode: If True, return text response; if False, return action.

        Returns:
            (response, flags) — response is the action string or text,
            flags is a list for compatibility (empty).
        """
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return loop.run_until_complete(
                self._async_predict(instruction, obs, chat_mode)
            )
        return asyncio.run(
            self._async_predict(instruction, obs, chat_mode)
        )

    async def _async_predict(
        self,
        instruction: str,
        obs: dict[str, Any],
        chat_mode: bool = False,
    ) -> tuple[str, list]:
        """Async prediction using weebot's VLM."""
        await self._ensure_initialized()

        # Build messages with screenshot + a11y tree
        messages = self._build_messages(instruction, obs)

        # Call VLM (GPT-4o) to decide next action
        response = await self._llm.chat(
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )

        action_str = response.content or "WAIT"
        action_str = action_str.strip()

        # Parse action from VLM response
        parsed = self._parse_action(action_str)
        self._conversation_history.append({
            "instruction": instruction,
            "action": parsed,
        })

        return (parsed, [])

    # ── Message Building ────────────────────────────────────────────

    def _build_messages(
        self,
        instruction: str,
        obs: dict[str, Any],
    ) -> list[dict]:
        """Build VLM messages with screenshot and optional a11y tree.

        Follows the OSWorld protocol: screenshot as image, a11y tree
        as pre-prompt text, action space as system prompt.
        """
        system_prompt = (
            "You are a computer control agent. Given a task instruction, "
            "a screenshot of the current desktop, and an accessibility tree, "
            "decide the next action to take.\n\n"
            "Available actions:\n"
            + self._action_space_prompt()
            + "\n\nRespond with ONLY the action JSON. No explanation."
        )

        user_content = []

        # Screenshot (primary observation)
        screenshot_png = obs.get("screenshot")
        if screenshot_png:
            b64 = base64.b64encode(screenshot_png).decode()
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            })

        # Accessibility tree (secondary observation)
        a11y_tree = obs.get("accessibility_tree")
        if a11y_tree:
            # Prune: limit to first 4000 chars for token budget
            tree_text = self._format_a11y_tree(a11y_tree)
            user_content.append({
                "type": "text",
                "text": f"Accessibility Tree:\n{tree_text[:4000]}",
            })

        # Task instruction
        user_content.append({
            "type": "text",
            "text": f"Task: {instruction}\n\nWhat is the next action?",
        })

        # Trajectory history (last N actions)
        if self._conversation_history:
            history_text = "\n".join(
                f"Step {i+1}: {h['action']}"
                for i, h in enumerate(self._conversation_history[-self.max_trajectory_length:])
            )
            user_content.append({
                "type": "text",
                "text": f"Previous actions:\n{history_text}",
            })

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    def _action_space_prompt(self) -> str:
        """Generate the action space description for the system prompt."""
        return """{
  "action": "CLICK",        // or: MOVE_TO, DOUBLE_CLICK, RIGHT_CLICK,
                             //     DRAG_TO, SCROLL, TYPING, PRESS,
                             //     KEY_DOWN, KEY_UP, HOTKEY
  "x": 500,                 // pixel x (if applicable)
  "y": 300,                 // pixel y (if applicable)
  "button": "left",         // "left", "right", "middle" (if applicable)
  "text": "hello",          // for TYPING
  "key": "enter",           // for PRESS/KEY_DOWN/KEY_UP
  "keys": ["ctrl", "c"],    // for HOTKEY
  "dx": 0, "dy": -3,        // for SCROLL (negative dy = scroll down)
  "num_clicks": 1           // for CLICK (1, 2, or 3)
}

Special actions:
  {"action": "WAIT"}        — pause until next action
  {"action": "FAIL"}        — task is impossible
  {"action": "DONE"}        — task is complete"""

    def _format_a11y_tree(self, a11y_tree) -> str:
        """Format a11y tree for VLM consumption.

        OSWorld provides either a dict (parsed) or raw XML string.
        """
        if isinstance(a11y_tree, dict):
            return json.dumps(a11y_tree, indent=2)
        if isinstance(a11y_tree, str):
            return a11y_tree
        return str(a11y_tree)

    # ── Action Parsing ──────────────────────────────────────────────

    def _parse_action(self, action_str: str) -> str:
        """Parse VLM response into OSWorld-compatible action string.

        Expects JSON like: {"action": "CLICK", "x": 500, "y": 300}
        Falls back to raw string if JSON parsing fails.
        """
        try:
            # Try to extract JSON from the response
            action_str = action_str.strip()
            # Remove markdown code fences if present
            if action_str.startswith("```"):
                lines = action_str.split("\n")
                action_str = "\n".join(lines[1:-1])
            action = json.loads(action_str)
        except (json.JSONDecodeError, ValueError):
            # Fallback: return raw string (OSWorld handles parsing)
            return action_str

        # Validate and normalize
        action_type = action.get("action", "WAIT").upper()
        if action_type not in _ACTION_MAP:
            logger.warning("Unknown action type: %s", action_type)
            return "WAIT"

        return json.dumps(action)

    # ── Reset between tasks ─────────────────────────────────────────

    def reset(self):
        """Reset conversation history for a new task."""
        self._conversation_history.clear()
