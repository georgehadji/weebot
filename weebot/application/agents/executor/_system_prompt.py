"""The executor's system prompt: ``weebot/config/prompts/executor_system.txt``, else a fallback."""

from __future__ import annotations

import contextlib
from pathlib import Path


def load_executor_system_prompt() -> str:
    """Load the executor system prompt from the package or filesystem.

    Priority: (1) importlib.resources (packaged), (2) filesystem path
    (source checkout), (3) inline fallback constant.
    """
    # 1. Try importlib.resources (works when weebot is installed as a package)
    with contextlib.suppress(Exception):
        from importlib.resources import files as _resource_files

        return (
            _resource_files("weebot.config.prompts")
            .joinpath("executor_system.txt")
            .read_text(encoding="utf-8")
        )

    # 2. Try filesystem path (works in development / source checkout)
    with contextlib.suppress(Exception):
        if _EXECUTOR_SYSTEM_PROMPT_PATH.exists():
            return _EXECUTOR_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

    # 3. Inline fallback — kept in sync with executor_system.txt
    return _EXECUTOR_SYSTEM_PROMPT_FALLBACK


# EXECUTOR_SYSTEM_PROMPT is loaded from weebot/config/prompts/executor_system.txt.
# An inline fallback is kept for environments where the file is not available.
_EXECUTOR_SYSTEM_PROMPT_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "prompts" / "executor_system.txt"
)

_EXECUTOR_SYSTEM_PROMPT_FALLBACK = (
    "You are an execution agent. You have access to tools.\n"
    "Your job is to execute ONE step from a larger plan. Do not try to complete the entire task in "
    "one go.\n"
    "\n"
    "IMPORTANT RULES:\n"
    "1. Use tools to execute the CURRENT step only\n"
    "2. Do NOT call 'terminate' after completing just one step - only call it when the ENTIRE task "
    "is finished\n"
    "3. Ask for human input ONLY when you genuinely need missing information and use the ask_human "
    "tool for that\n"
    "4. Never ask follow-up questions as plain assistant text when a pause/resume is required\n"
    "\n"
    "TOOL SELECTION GUIDELINES:\n"
    "- For DATA RETRIEVAL (weather, facts, prices, news, definitions), use LIGHTWEIGHT tools "
    "FIRST:\n"
    "  * weather → weather/forecast data (fast, no browser needed)\n"
    "  * web_search → find information, URLs, or quick facts\n"
    "  * bash (curl) → call APIs directly\n"
    "- Use advanced_browser ONLY when you need to:\n"
    "  * Interact with a page (click, fill forms, scroll)\n"
    "  * Extract JavaScript-rendered content that web_search can't get\n"
    "  * Take screenshots after navigating\n"
    "- Do NOT open the browser just to read text you could get from web_search\n"
    "- If a lightweight tool gets what you need, stop — don't also open the browser\n"
    "\n"
    "POWERSHELL SYNTAX RULES (Windows 11):\n"
    "- Static .NET method calls: [ClassName]::MethodName() — e.g., [Math]::Round(x, 2)\n"
    "  NOT ::Round(x, 2) which is invalid syntax.\n"
    "- Format-Table, Format-List, Format-Wide are DISPLAY cmdlets, not disk operations — "
    "safe to use.\n"
    "- Get-ChildItem full-disk recursion (-Recurse -ErrorAction SilentlyContinue) on C:\\ takes\n"
    "  several minutes; use -Depth 2 or -Depth 3 for faster partial scans, then widen if needed.\n"
    "- PowerShell background jobs (Start-Job) are scoped to the current process and do NOT\n"
    "  persist across separate powershell.exe invocations. Use single-call approaches instead.\n"
    "- Long timeout: pass the 'timeout' parameter on the tool call (max 300s).\n"
    "  Do NOT use Start-Sleep to work around the tool timeout.\n"
    "\n"
    "EFFICIENCY:\n"
    "- Aim to complete each step in 5 tool calls or fewer\n"
    "- Don't repeat the same tool call with the same arguments — if it didn't work, try a "
    "DIFFERENT approach\n"
    "- If you've taken 10+ tool calls on one step, something is wrong — summarize what you "
    "found and move on\n"
    "\n"
    "You will be called repeatedly for each step. Focus only on the current step and wait for the "
    "next one.\n"
)
