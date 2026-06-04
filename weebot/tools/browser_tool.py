"""Browser Tool using browser-use and playwright."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional, Dict, Any, TYPE_CHECKING

from langchain.tools import BaseTool

from weebot.tools.base import ToolResult

if TYPE_CHECKING:
    from weebot.application.ports.llm_port import LLMPort

logger = logging.getLogger(__name__)

try:
    from browser_use import Browser, Agent as BrowserAgent
    from langchain_openai import ChatOpenAI
    BROWSER_USE_AVAILABLE = True
except ImportError:
    BROWSER_USE_AVAILABLE = False

BROWSER_TIMEOUT = 30000
HEADLESS = False


class BrowserTool(BaseTool):
    """Navigate and interact with web pages using AI browser automation.

    Can use Weebot's LLMPort for model selection, or fallback to OpenAI.
    """

    name: str = "browser_navigator"
    description: str = """Navigate and interact with web pages using AI browser automation.
    Use for: web scraping, form filling, clicking buttons, extracting data from websites.
    Input should be a natural language description of the task."""

    browser: Optional[Any] = None

    def __init__(self, llm_port: Optional["LLMPort"] = None, model: Optional[str] = None, use_vision: bool = True):
        """Initialize BrowserTool.

        Args:
            llm_port: Weebot LLMPort for model selection. If None, uses ChatOpenAI.
            model: Model identifier to use with llm_port.
            use_vision: Whether to enable vision capabilities for the browser agent.
        """
        super().__init__()
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
        """Get LLM for browser agent."""
        if self._llm_port is not None:
            # Use Weebot's LLMPort via adapter
            from weebot.infrastructure.llm.langchain_adapter import LLMPortLangChainAdapter
            llm = LLMPortLangChainAdapter(
                llm_port=self._llm_port,
                model=self._model,
                temperature=0,
            )
        else:
            # Fallback to OpenAI
            logger.debug("No LLMPort provided, using default ChatOpenAI")
            # Import here to handle case where browser-use is not installed
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(model="gpt-4", temperature=0)
        
        # browser-use expects LLM to have a 'provider' attribute
        if not hasattr(llm, 'provider'):
            object.__setattr__(llm, 'provider', 'openai') # Defaulting to openai for compatibility
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
                "description": "Natural language task for the browser agent",
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
