"""Browser Tool using browser-use and playwright."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional, Dict, Any, TYPE_CHECKING

# NOTE: langchain BaseTool import is deferred to __init__ because
# importing langchain triggers network calls at module load time.
# BrowserTool provides name/description/parameters as class attributes
# so the ToolRegistry can inspect them without instantiation.

from weebot.tools.base import ToolResult

if TYPE_CHECKING:
    from weebot.application.ports.llm_port import LLMPort

logger = logging.getLogger(__name__)

try:
    from browser_use import Browser, Agent as BrowserAgent
    BROWSER_USE_AVAILABLE = True
except ImportError:
    BROWSER_USE_AVAILABLE = False

# langchain_openai imports are deferred to _get_llm() because
# they trigger network calls at import time.

BROWSER_TIMEOUT = 30000
HEADLESS = False


class BrowserTool:
    """Navigate and interact with web pages using AI browser automation.

    Can use Weebot's LLMPort for model selection, or fallback to OpenAI.
    """

    name: str = "browser_navigator"
    description: str = """Open a real Chrome browser and perform web tasks using AI.
    Use for: logging into websites, filling login forms, posting content,
    clicking buttons, navigating pages, extracting data, filling forms.
    Can handle authentication, 2FA (manual intervention), and file uploads.
    Opens a visible browser window — you'll see it working.
    Input: describe what to do in natural language."""

    browser: Optional[Any] = None

    def __init__(self, llm_port: Optional["LLMPort"] = None, model: Optional[str] = None, use_vision: bool = True):
        """Initialize BrowserTool.

        Args:
            llm_port: Weebot LLMPort for model selection. When None
                (constructed by RoleBasedToolRegistry), _get_llm() will
                attempt DI resolution at call time. Falls back to
                ChatOpenAI (requires OPENAI_API_KEY env var).
            model: Model identifier to use with llm_port.
            use_vision: Whether to enable vision capabilities for the browser agent.
        """
        # BrowserTool does not extend langchain's BaseTool to avoid
        # triggering network calls at import time.
        # The _run / _arun interface is provided for langchain compatibility
        # but init is plain object init.
        self._browser = None
        self._llm_port = llm_port
        self._model = model
        self._use_vision = use_vision

    async def _ensure_browser(self):
        """Initialize browser if not exists."""
        if not BROWSER_USE_AVAILABLE:
            raise ImportError("browser-use not installed. Run: pip install browser-use")
        if not self._browser:
            self._browser = Browser(headless=HEADLESS)

    def _get_llm(self):
        """Get LLM for browser agent.

        Priority:
        1. ChatBrowserUse() — purpose-built for browser tasks (3-5x faster)
        2. Weebot's LLMPort via DI (injected at construction time)
        3. OpenRouter via langchain (OPENROUTER_API_KEY)
        4. ChatOpenAI fallback (gpt-4)
        """
        import os as _os

        # ── 1. ChatBrowserUse (best — purpose-built for browser) ────
        if _os.environ.get("BROWSER_USE_API_KEY"):
            try:
                from browser_use import ChatBrowserUse
                llm = ChatBrowserUse()
                logger.debug("BrowserTool using ChatBrowserUse (purpose-built browser LLM)")
                return llm
            except ImportError:
                logger.debug("ChatBrowserUse not available, falling through")
            except Exception as exc:
                logger.debug("ChatBrowserUse init failed: %s, falling through", exc)

        # ── 2. Weebot LLMPort (DI-injected) ─────────────────────────
        if self._llm_port is not None:
            from weebot.infrastructure.llm.langchain_adapter import LLMPortLangChainAdapter
            llm = LLMPortLangChainAdapter(
                llm_port=self._llm_port,
                model=self._model,
                temperature=0,
            )
            return self._add_provider_attr(llm)

        # ── 3. OpenRouter (OPENROUTER_API_KEY) ──────────────────────
        or_key = _os.environ.get("OPENROUTER_API_KEY")
        if or_key:
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                model=_os.environ.get("OPENROUTER_MODEL", "openrouter/anthropic/claude-sonnet-4-6"),
                openai_api_key=or_key,
                openai_api_base="https://openrouter.ai/api/v1",
                temperature=0,
            )
            logger.debug("BrowserTool using OpenRouter: %s", llm.model)
            return self._add_provider_attr(llm)

        # ── 4. OpenAI fallback ──────────────────────────────────────
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model="gpt-4o", temperature=0)
        logger.debug("BrowserTool using OpenAI fallback (no BROWSER_USE_API_KEY or OPENROUTER_API_KEY)")
        return self._add_provider_attr(llm)

    @staticmethod
    def _add_provider_attr(llm):
        """browser-use expects LLM to have a 'provider' attribute."""
        if not hasattr(llm, 'provider'):
            object.__setattr__(llm, 'provider', 'openai')
        return llm

    async def _run_browser_task(self, task: str) -> str:
        """Execute browser task using browser-use."""
        try:
            await self._ensure_browser()

            llm = self._get_llm()

            agent = BrowserAgent(
                task=task,
                llm=llm,
                browser=self._browser,
                use_vision=self._use_vision,
            )

            result = await agent.run()
            return str(result)

        except Exception as e:
            logger.exception("Browser task failed")
            return f"Browser Error: {str(e)}"

    def _run(self, task: str) -> str:
        """Synchronous wrapper for browser operations."""
        try:
            try:
                asyncio.get_running_loop()
                return "Error: BrowserTool._run cannot be used inside a running event loop; use _arun instead."
            except RuntimeError:
                result = asyncio.run(self._run_browser_task(task))
                return result

        except Exception as e:
            return f"Error: {str(e)}"

    async def _arun(self, task: str) -> str:
        """Async execution."""
        return await self._run_browser_task(task)

    # ── weebot BaseTool compatibility ────────────────────────────────
    # BrowserTool extends langchain's BaseTool, but weebot's ToolCollection
    # expects execute(**kwargs) + to_param(). These bridge methods provide
    # that interface.

    parameters: dict = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "What to do: navigate to URL, log in, fill forms, post content, click buttons, extract data",
            },
        },
        "required": ["task"],
    }

    def to_param(self) -> dict:
        """Convert to OpenAI function spec (weebot-compatible)."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    async def execute(self, task: str = "", **kwargs):
        """weebot-compatible execute: delegates to _arun."""
        try:
            result = await self._arun(task)
            return ToolResult(output=str(result))
        except Exception as exc:
            return ToolResult(error=str(exc), output="")
