"""Token bucket rate limiter for tool execution control.

Provides rate limiting per tool to prevent:
- API cost overruns
- Resource exhaustion
- Service abuse

Usage:
    from weebot.utils.rate_limiter import rate_limited, TokenBucket
    
    @rate_limited("web_search")
    async def search(query: str):
        return await web_search_tool.execute(query=query)
"""
from __future__ import annotations

import time
import asyncio
from dataclasses import dataclass, field
from functools import wraps
from typing import Callable, Optional, Dict
from threading import Lock


@dataclass
class TokenBucket:
    """
    Token bucket for rate limiting.
    
    Attributes:
        rate: Tokens added per second (sustained rate)
        capacity: Maximum tokens (burst capacity)
        _tokens: Current available tokens
        _last_update: Last time tokens were added
        _lock: Thread safety lock
    """
    rate: float = 1.0
    capacity: float = 10.0
    _tokens: float = field(default=0.0, repr=False)
    _last_update: float = field(default_factory=time.monotonic, repr=False)
    _lock: Lock = field(default_factory=Lock, repr=False)
    
    def __post_init__(self):
        # Start with full bucket
        self._tokens = self.capacity
    
    def consume(self, tokens: float = 1.0) -> bool:
        """
        Attempt to consume tokens from the bucket.
        
        Args:
            tokens: Number of tokens to consume
            
        Returns:
            True if tokens were consumed, False if not enough available
        """
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_update
            
            # Add tokens based on elapsed time
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            self._last_update = now
            
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False
    
    def get_wait_time(self, tokens: float = 1.0) -> float:
        """
        Calculate how long to wait before tokens will be available.
        
        Args:
            tokens: Number of tokens needed
            
        Returns:
            Seconds to wait (0.0 if tokens are available now)
        """
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_update
            current_tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            
            if current_tokens >= tokens:
                return 0.0
            
            # Calculate time needed to generate enough tokens
            tokens_needed = tokens - current_tokens
            return tokens_needed / self.rate


# Global registry of rate limit buckets
_rate_limit_buckets: Dict[str, TokenBucket] = {}
_buckets_lock = Lock()


# Default rate limits per tool
DEFAULT_RATE_LIMITS = {
    # Tool name: (rate per second, burst capacity)
    "web_search": (0.5, 5),        # 5 burst, 0.5/s sustained
    "bash": (2.0, 10),             # 10 burst, 2/s sustained
    "python_execute": (1.0, 5),    # 5 burst, 1/s sustained
    "file_editor": (5.0, 20),      # 20 burst, 5/s sustained
    "advanced_browser": (0.2, 2),  # 2 burst, 0.2/s sustained (slow)
    "computer_use": (0.5, 3),      # 3 burst, 0.5/s sustained
    "screen_capture": (1.0, 5),    # 5 burst, 1/s sustained
    "schedule": (2.0, 10),         # 10 burst, 2/s sustained
    "knowledge": (5.0, 20),        # 20 burst, 5/s sustained
    "product": (2.0, 10),          # 10 burst, 2/s sustained
    "video_ingest": (0.1, 1),      # 1 burst, 0.1/s sustained (very slow)
    "ocr": (0.5, 3),               # 3 burst, 0.5/s sustained
    "powershell": (2.0, 10),       # 10 burst, 2/s sustained
}


def get_bucket(tool_name: str) -> TokenBucket:
    """
    Get or create a rate limit bucket for a tool.
    
    Args:
        tool_name: Name of the tool
        
    Returns:
        TokenBucket for the tool
    """
    with _buckets_lock:
        if tool_name not in _rate_limit_buckets:
            rate, capacity = DEFAULT_RATE_LIMITS.get(tool_name, (1.0, 10))
            _rate_limit_buckets[tool_name] = TokenBucket(rate=rate, capacity=capacity)
        return _rate_limit_buckets[tool_name]


def set_rate_limit(tool_name: str, rate: float, capacity: float) -> None:
    """
    Configure rate limit for a tool.
    
    Args:
        tool_name: Name of the tool
        rate: Tokens per second
        capacity: Maximum burst capacity
    """
    with _buckets_lock:
        _rate_limit_buckets[tool_name] = TokenBucket(rate=rate, capacity=capacity)


def reset_bucket(tool_name: str) -> None:
    """Reset a tool's rate limit bucket to full."""
    with _buckets_lock:
        if tool_name in _rate_limit_buckets:
            del _rate_limit_buckets[tool_name]


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""
    
    def __init__(self, tool_name: str, retry_after: float):
        self.tool_name = tool_name
        self.retry_after = retry_after
        super().__init__(
            f"Rate limit exceeded for '{tool_name}'. "
            f"Retry after {retry_after:.1f} seconds."
        )


def rate_limited(
    tool_name: str,
    tokens: float = 1.0,
    wait: bool = False,
    max_wait: float = 60.0
):
    """
    Decorator to rate limit a function.
    
    Args:
        tool_name: Name of the tool (for rate limit bucket)
        tokens: Number of tokens to consume per call
        wait: If True, wait for tokens to be available instead of raising
        max_wait: Maximum time to wait if wait=True
        
    Usage:
        @rate_limited("web_search")
        async def search(query: str):
            return await web_search.execute(query=query)
            
        @rate_limited("bash", wait=True, max_wait=10.0)
        async def run_command(cmd: str):
            return await bash.execute(command=cmd)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            bucket = get_bucket(tool_name)
            
            if bucket.consume(tokens):
                return await func(*args, **kwargs)
            
            if wait:
                wait_time = bucket.get_wait_time(tokens)
                if wait_time > max_wait:
                    raise RateLimitExceeded(tool_name, wait_time)
                await asyncio.sleep(wait_time)
                return await async_wrapper(*args, **kwargs)
            else:
                wait_time = bucket.get_wait_time(tokens)
                raise RateLimitExceeded(tool_name, wait_time)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            bucket = get_bucket(tool_name)
            
            if bucket.consume(tokens):
                return func(*args, **kwargs)
            
            wait_time = bucket.get_wait_time(tokens)
            raise RateLimitExceeded(tool_name, wait_time)
        
        # Return appropriate wrapper based on whether func is async
        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    return decorator


def check_rate_limit(tool_name: str, tokens: float = 1.0) -> tuple[bool, float]:
    """
    Check if a tool call would exceed rate limit without consuming tokens.
    
    Args:
        tool_name: Name of the tool
        tokens: Number of tokens needed
        
    Returns:
        (allowed, retry_after) - allowed is True if call is allowed,
        retry_after is seconds to wait if not allowed
    """
    bucket = get_bucket(tool_name)
    
    if bucket.consume(tokens):
        return True, 0.0
    
    wait_time = bucket.get_wait_time(tokens)
    return False, wait_time


# Convenience function for manual rate limit checks
async def acquire_token(tool_name: str, tokens: float = 1.0, timeout: float = 30.0) -> bool:
    """
    Acquire tokens with optional waiting.
    
    Args:
        tool_name: Name of the tool
        tokens: Number of tokens to acquire
        timeout: Maximum time to wait
        
    Returns:
        True if tokens acquired, False if timeout
    """
    bucket = get_bucket(tool_name)
    start_time = time.monotonic()
    
    while time.monotonic() - start_time < timeout:
        if bucket.consume(tokens):
            return True
        await asyncio.sleep(0.1)
    
    return False


def get_rate_limit_status() -> Dict[str, Dict[str, float]]:
    """
    Get current rate limit status for all tools.
    
    Returns:
        Dictionary mapping tool names to their status
    """
    with _buckets_lock:
        status = {}
        for name, bucket in _rate_limit_buckets.items():
            status[name] = {
                "rate": bucket.rate,
                "capacity": bucket.capacity,
                "available": bucket._tokens,
                "utilization": 1.0 - (bucket._tokens / bucket.capacity) if bucket.capacity > 0 else 0.0,
            }
        return status
