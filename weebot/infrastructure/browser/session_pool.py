"""Browser session pool for reusable Playwright sessions."""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Optional, Set

from weebot.application.ports.browser_port import BrowserConfig, BrowserType

logger = logging.getLogger(__name__)


@dataclass
class BrowserSession:
    """A pooled browser session."""
    browser: Any  # playwright Browser
    context: Any  # playwright BrowserContext
    page: Any  # playwright Page
    config: BrowserConfig
    created_at: float = field(default_factory=time.monotonic)
    last_used: float = field(default_factory=time.monotonic)
    use_count: int = 0
    
    def is_expired(self, ttl_seconds: float) -> bool:
        """Check if session has exceeded its TTL."""
        return time.monotonic() - self.created_at > ttl_seconds
    
    def is_idle(self, idle_seconds: float) -> bool:
        """Check if session has been idle for too long."""
        return time.monotonic() - self.last_used > idle_seconds
    
    def mark_used(self):
        """Update last used timestamp."""
        self.last_used = time.monotonic()
        self.use_count += 1
    
    async def close(self):
        """Close the session and cleanup resources."""
        try:
            if self.context:
                await self.context.close()
        except Exception as e:
            logger.debug(f"Error closing context: {e}")
        
        try:
            if self.browser:
                await self.browser.close()
        except Exception as e:
            logger.debug(f"Error closing browser: {e}")


class BrowserSessionPool:
    """
    Pool of reusable browser sessions for fast browser automation.
    
    Maintains warm browser contexts ready for immediate use, dramatically
    reducing per-request startup time from ~3s to <100ms.
    
    Usage:
        pool = BrowserSessionPool(min_sessions=2, max_sessions=5)
        await pool.start()
        
        # Acquire a session
        async with pool.acquire() as session:
            await session.page.goto("https://example.com")
            ...
        
        await pool.close()
    
    Attributes:
        min_sessions: Minimum sessions to keep warm
        max_sessions: Maximum concurrent sessions allowed
        session_ttl: Maximum lifetime of a session before replacement
        headless: Whether to run browsers in headless mode
    """
    
    def __init__(
        self,
        min_sessions: int = 1,
        max_sessions: int = 5,
        session_ttl: float = 300.0,  # 5 minutes
        idle_timeout: float = 60.0,  # 1 minute
        headless: bool = True,
        default_config: Optional[BrowserConfig] = None
    ):
        """
        Initialize browser session pool.
        
        Args:
            min_sessions: Minimum warm sessions to maintain
            max_sessions: Maximum concurrent sessions allowed
            session_ttl: Maximum session lifetime in seconds
            idle_timeout: Time before idle sessions are closed
            headless: Whether to run browsers headless
            default_config: Default browser configuration
        """
        self.min_sessions = max(1, min_sessions)
        self.max_sessions = max(self.min_sessions, max_sessions)
        self.session_ttl = session_ttl
        self.idle_timeout = idle_timeout
        self.headless = headless
        self.default_config = default_config or BrowserConfig(headless=headless)
        
        # Pool state
        self._available: asyncio.Queue[BrowserSession] = asyncio.Queue()
        self._in_use: Set[BrowserSession] = set()
        self._playwright: Optional[Any] = None
        
        # Concurrency control
        self._semaphore = asyncio.Semaphore(self.max_sessions)
        self._lock = asyncio.Lock()
        
        # Background maintenance
        self._maintenance_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Statistics
        self._stats = {
            "created": 0,
            "reused": 0,
            "expired": 0,
            "errors": 0
        }
    
    async def start(self) -> None:
        """
        Initialize playwright and warm up minimum sessions.
        
        This should be called during application startup.
        """
        if self._running:
            return
        
        from playwright.async_api import async_playwright
        
        logger.info(f"Starting browser pool (min={self.min_sessions}, max={self.max_sessions})")
        
        self._playwright = await async_playwright().start()
        self._running = True
        
        # Pre-warm minimum sessions
        for i in range(self.min_sessions):
            try:
                session = await self._create_session()
                await self._available.put(session)
                self._stats["created"] += 1
                logger.debug(f"Pre-warmed session {i+1}/{self.min_sessions}")
            except Exception as e:
                logger.error(f"Failed to pre-warm session: {e}")
        
        # Start background maintenance
        self._maintenance_task = asyncio.create_task(self._maintenance_loop())
        
        logger.info(f"Browser pool ready with {self._available.qsize()} sessions")
    
    @asynccontextmanager
    async def acquire(
        self,
        config: Optional[BrowserConfig] = None,
        timeout: float = 30.0
    ):
        """
        Acquire a browser session from the pool.
        
        Args:
            config: Optional browser configuration override
            timeout: Maximum seconds to wait for a session
        
        Yields:
            BrowserSession: Ready-to-use browser session
        """
        if not self._running:
            raise RuntimeError("Browser pool not started. Call start() first.")
        
        config = config or self.default_config
        session = None
        
        async with self._semaphore:
            try:
                # Try to get from available pool
                session = await asyncio.wait_for(
                    self._available.get(),
                    timeout=1.0  # Short timeout for available sessions
                )
                
                # Check if expired or config mismatch
                if (session.is_expired(self.session_ttl) or 
                    not self._config_matches(session.config, config)):
                    logger.debug("Session expired or config mismatch, creating new")
                    await session.close()
                    session = await self._create_session(config)
                    self._stats["created"] += 1
                else:
                    self._stats["reused"] += 1
                
            except asyncio.TimeoutError:
                # Create new session if pool exhausted
                logger.debug("Pool exhausted, creating new session")
                session = await self._create_session(config)
                self._stats["created"] += 1
            
            # Mark as in-use
            async with self._lock:
                self._in_use.add(session)
            
            session.mark_used()
            
            try:
                yield session
            finally:
                # Return to pool
                async with self._lock:
                    self._in_use.discard(session)
                
                # Clear cookies/storage for privacy
                try:
                    await session.context.clear_cookies()
                except Exception:
                    pass
                
                # Return to available pool if not expired
                if not session.is_expired(self.session_ttl):
                    await self._available.put(session)
                else:
                    await session.close()
                    self._stats["expired"] += 1
    
    async def _create_session(
        self,
        config: Optional[BrowserConfig] = None
    ) -> BrowserSession:
        """Create a new browser session."""
        config = config or self.default_config
        
        if not self._playwright:
            raise RuntimeError("Playwright not initialized")
        
        try:
            # Select browser type
            if config.browser_type == BrowserType.FIREFOX:
                browser_type = self._playwright.firefox
            elif config.browser_type == BrowserType.WEBKIT:
                browser_type = self._playwright.webkit
            else:
                browser_type = self._playwright.chromium
            
            # Launch browser
            launch_options = {"headless": config.headless}
            if config.proxy_server:
                launch_options["proxy"] = {"server": config.proxy_server}
            
            browser = await browser_type.launch(**launch_options)
            
            # Create context
            context_options = {
                "viewport": {
                    "width": config.viewport_width,
                    "height": config.viewport_height,
                },
            }
            
            if config.user_agent:
                context_options["user_agent"] = config.user_agent
            if config.locale:
                context_options["locale"] = config.locale
            if config.timezone:
                context_options["timezone_id"] = config.timezone
            
            context = await browser.new_context(**context_options)
            page = await context.new_page()
            
            return BrowserSession(
                browser=browser,
                context=context,
                page=page,
                config=config,
                created_at=time.monotonic(),
                last_used=time.monotonic(),
                use_count=0
            )
            
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Failed to create browser session: {e}")
            raise
    
    def _config_matches(self, cached: BrowserConfig, requested: BrowserConfig) -> bool:
        """Check if cached session config matches requested config."""
        # Only check critical parameters
        return (
            cached.browser_type == requested.browser_type and
            cached.headless == requested.headless and
            cached.viewport_width == requested.viewport_width and
            cached.viewport_height == requested.viewport_height
        )
    
    async def _maintenance_loop(self) -> None:
        """Background task to maintain pool health."""
        while self._running:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                
                if not self._running:
                    break
                
                # Ensure minimum warm sessions
                current_available = self._available.qsize()
                if current_available < self.min_sessions:
                    needed = self.min_sessions - current_available
                    logger.debug(f"Maintenance: creating {needed} warm sessions")
                    
                    for _ in range(needed):
                        try:
                            session = await self._create_session()
                            await self._available.put(session)
                            self._stats["created"] += 1
                        except Exception as e:
                            logger.warning(f"Maintenance: failed to create session: {e}")
                
                # Remove expired sessions from pool
                temp_sessions = []
                while not self._available.empty():
                    try:
                        session = self._available.get_nowait()
                        if session.is_expired(self.session_ttl) or session.is_idle(self.idle_timeout):
                            await session.close()
                            self._stats["expired"] += 1
                        else:
                            temp_sessions.append(session)
                    except asyncio.QueueEmpty:
                        break
                
                # Put back valid sessions
                for session in temp_sessions:
                    await self._available.put(session)
                    
            except Exception as e:
                logger.error(f"Maintenance loop error: {e}")
    
    async def close(self) -> None:
        """Close all sessions and cleanup resources."""
        logger.info("Shutting down browser pool")
        self._running = False
        
        # Stop maintenance loop
        if self._maintenance_task:
            self._maintenance_task.cancel()
            try:
                await self._maintenance_task
            except asyncio.CancelledError:
                pass
        
        # Close available sessions
        closed_count = 0
        while not self._available.empty():
            try:
                session = self._available.get_nowait()
                await session.close()
                closed_count += 1
            except asyncio.QueueEmpty:
                break
            except Exception as e:
                logger.debug(f"Error closing session: {e}")
        
        # Close in-use sessions (shouldn't happen in normal shutdown)
        async with self._lock:
            for session in list(self._in_use):
                try:
                    await session.close()
                    closed_count += 1
                except Exception as e:
                    logger.debug(f"Error closing in-use session: {e}")
            self._in_use.clear()
        
        # Stop playwright
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        
        logger.info(f"Browser pool closed ({closed_count} sessions closed)")
    
    def get_stats(self) -> dict:
        """Get pool statistics."""
        return {
            "available": self._available.qsize(),
            "in_use": len(self._in_use),
            "min_sessions": self.min_sessions,
            "max_sessions": self.max_sessions,
            "running": self._running,
            **self._stats
        }
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()


# Global pool instance for application-wide reuse
_global_pool: Optional[BrowserSessionPool] = None
_pool_lock = asyncio.Lock()


async def get_browser_pool(
    min_sessions: int = 1,
    max_sessions: int = 5,
    **kwargs
) -> BrowserSessionPool:
    """
    Get or create the global browser pool.
    
    Args:
        min_sessions: Minimum warm sessions
        max_sessions: Maximum concurrent sessions
        **kwargs: Additional pool configuration
    
    Returns:
        BrowserSessionPool instance
    """
    global _global_pool
    
    async with _pool_lock:
        if _global_pool is None:
            _global_pool = BrowserSessionPool(
                min_sessions=min_sessions,
                max_sessions=max_sessions,
                **kwargs
            )
            await _global_pool.start()
            logger.info("Global browser pool initialized")
        
        return _global_pool


async def close_global_pool() -> None:
    """Close the global browser pool."""
    global _global_pool
    
    async with _pool_lock:
        if _global_pool:
            await _global_pool.close()
            _global_pool = None
            logger.info("Global browser pool closed")
