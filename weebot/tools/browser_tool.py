"""Browser Tool using browser-use and playwright."""
import asyncio
from typing import Optional, Dict, Any
from langchain.tools import BaseTool

try:
    from browser_use import Browser, Agent as BrowserAgent
    from langchain_openai import ChatOpenAI
    BROWSER_USE_AVAILABLE = True
except ImportError:
    BROWSER_USE_AVAILABLE = False

BROWSER_TIMEOUT = 30000
HEADLESS = False


class BrowserTool(BaseTool):
    name: str = "browser_navigator"
    description: str = """Navigate and interact with web pages using AI browser automation.
    Use for: web scraping, form filling, clicking buttons, extracting data from websites.
    Input should be a natural language description of the task."""
    
    browser: Optional[Any] = None
    
    def __init__(self):
        super().__init__()
        self._browser = None
    
    async def _ensure_browser(self):
        """Initialize browser if not exists."""
        if not BROWSER_USE_AVAILABLE:
            raise ImportError("browser-use not installed")
        if not self._browser:
            self._browser = Browser(headless=HEADLESS)
    
    async def _run_browser_task(self, task: str) -> str:
        """Execute browser task using browser-use."""
        try:
            await self._ensure_browser()
            
            # Initialize browser-use agent
            llm = ChatOpenAI(model="gpt-4", temperature=0)
            agent = BrowserAgent(
                task=task,
                llm=llm,
                browser=self._browser
            )
            
            result = await agent.run()
            return str(result)
            
        except Exception as e:
            return f"Browser Error: {str(e)}"
    
    def _run(self, task: str) -> str:
        """Synchronous wrapper for browser operations."""
        try:
            # Run async code in sync context
            try:
                asyncio.get_running_loop()
                # If we're already in an event loop, avoid asyncio.run()
                # and return a clear error for sync callers.
                return "Error: BrowserTool._run cannot be used inside a running event loop; use _arun instead."
            except RuntimeError:
                # No running loop in this thread
                result = asyncio.run(self._run_browser_task(task))
                return result
            
        except Exception as e:
            return f"Error: {str(e)}"
    
    async def _arun(self, task: str) -> str:
        """Async execution."""
        return await self._run_browser_task(task)
