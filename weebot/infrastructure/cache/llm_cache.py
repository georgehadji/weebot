"""Two-tier caching system for LLM responses."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any, Dict

from weebot.application.ports.llm_port import LLMResponse

logger = logging.getLogger(__name__)

# Try to import diskcache, fallback to memory-only if not available
try:
    import diskcache
    DISKCACHE_AVAILABLE = True
except ImportError:
    diskcache = None
    DISKCACHE_AVAILABLE = False


@dataclass(frozen=True)
class CacheKey:
    """
    Immutable cache key from request parameters.
    
    Only includes parameters that affect the response:
    - messages (hashed)
    - model
    - temperature
    - tools (hashed, if present)
    """
    messages_hash: str
    model: str
    temperature: float
    tools_hash: Optional[str] = None
    
    @classmethod
    def from_request(
        cls,
        messages: list,
        model: str,
        temperature: float,
        tools: Optional[list] = None
    ) -> "CacheKey":
        """Create a cache key from request parameters."""
        # Hash messages (exclude dynamic content like timestamps)
        msg_normalized = cls._normalize_messages(messages)
        msg_str = json.dumps(msg_normalized, sort_keys=True, ensure_ascii=True)
        msg_hash = hashlib.sha256(msg_str.encode()).hexdigest()[:32]
        
        # Hash tools if present
        tools_hash = None
        if tools:
            tools_str = json.dumps(tools, sort_keys=True, ensure_ascii=True)
            tools_hash = hashlib.sha256(tools_str.encode()).hexdigest()[:16]
        
        return cls(
            messages_hash=msg_hash,
            model=model,
            temperature=temperature,
            tools_hash=tools_hash
        )
    
    @staticmethod
    def _normalize_messages(messages: list) -> list:
        """
        Normalize messages for consistent hashing.
        
        Removes or normalizes fields that shouldn't affect caching:
        - Trims whitespace
        - Normalizes case for system messages
        """
        normalized = []
        for msg in messages:
            if isinstance(msg, dict):
                norm_msg = msg.copy()
                if "content" in norm_msg and isinstance(norm_msg["content"], str):
                    # Normalize whitespace
                    norm_msg["content"] = " ".join(norm_msg["content"].split())
                normalized.append(norm_msg)
            else:
                normalized.append(msg)
        return normalized
    
    def to_string(self) -> str:
        """Convert to string for use as cache key."""
        parts = [self.messages_hash, self.model, f"{self.temperature:.2f}"]
        if self.tools_hash:
            parts.append(self.tools_hash)
        return ":".join(parts)


class LLMCache:
    """
    Two-tier cache for LLM responses.
    
    Tier 1: In-memory LRU (fastest, small, process-local)
    Tier 2: Disk cache (slower, large, persistent across restarts)
    
    Usage:
        cache = LLMCache(memory_size=100, disk_path=".cache/llm")
        
        # Store
        await cache.set(key, response, ttl=3600)
        
        # Retrieve
        response = await cache.get(key)
    
    Attributes:
        memory_size: Maximum items in memory cache
        disk_path: Path for disk cache directory
        default_ttl: Default time-to-live in seconds
    """
    
    def __init__(
        self,
        memory_size: int = 100,
        disk_path: str = ".cache/llm",
        default_ttl: int = 3600,
        model_name: Optional[str] = None
    ):
        """
        Initialize LLM cache.
        
        Args:
            memory_size: Maximum items in memory cache (LRU eviction)
            disk_path: Directory for disk cache
            default_ttl: Default cache entry lifetime in seconds
            model_name: Optional model name for cache isolation
        """
        self.memory_size = memory_size
        self.default_ttl = default_ttl
        
        # Memory cache: OrderedDict for O(1) LRU
        self._memory: OrderedDict[str, LLMResponse] = OrderedDict()
        
        # Disk cache
        self._disk = None
        if DISKCACHE_AVAILABLE:
            cache_dir = Path(disk_path)
            if model_name:
                cache_dir = cache_dir / model_name.replace("/", "_")
            cache_dir.mkdir(parents=True, exist_ok=True)
            self._disk = diskcache.Cache(str(cache_dir))
            logger.debug(f"Disk cache initialized at {cache_dir}")
        else:
            logger.warning("diskcache not available, using memory-only cache")
        
        # Statistics
        self._hits = {"memory": 0, "disk": 0, "miss": 0}
        self._lock = asyncio.Lock()
    
    async def get(self, key: CacheKey) -> Optional[LLMResponse]:
        """
        Get cached response.
        
        Checks memory first, then disk. Promotes disk hits to memory.
        
        Args:
            key: Cache key
        
        Returns:
            Cached LLMResponse or None if not found
        """
        key_str = key.to_string()
        
        # Check memory first (fastest)
        async with self._lock:
            if key_str in self._memory:
                # Move to end (most recently used)
                self._memory.move_to_end(key_str)
                self._hits["memory"] += 1
                logger.debug(f"Memory cache hit: {key_str[:16]}...")
                return self._memory[key_str]
        
        # Check disk cache
        if self._disk:
            try:
                data = self._disk.get(key_str)
                if data:
                    response = self._deserialize_response(data)
                    
                    # Promote to memory cache
                    async with self._lock:
                        self._memory[key_str] = response
                        self._memory.move_to_end(key_str)
                        if len(self._memory) > self.memory_size:
                            self._memory.popitem(last=False)
                    
                    self._hits["disk"] += 1
                    logger.debug(f"Disk cache hit: {key_str[:16]}...")
                    return response
            except Exception as e:
                logger.warning(f"Disk cache read error: {e}")
        
        self._hits["miss"] += 1
        return None
    
    async def set(
        self,
        key: CacheKey,
        response: LLMResponse,
        ttl: Optional[int] = None
    ) -> bool:
        """
        Store response in cache.
        
        Args:
            key: Cache key
            response: LLM response to cache
            ttl: Time-to-live in seconds (uses default if not specified)
        
        Returns:
            True if cached successfully, False otherwise
        """
        # Validate response before caching
        if not self._should_cache(response):
            return False
        
        key_str = key.to_string()
        ttl = ttl or self.default_ttl
        
        try:
            # Update memory cache
            async with self._lock:
                self._memory[key_str] = response
                self._memory.move_to_end(key_str)
                
                # Evict oldest if over capacity
                if len(self._memory) > self.memory_size:
                    removed_key, _ = self._memory.popitem(last=False)
                    logger.debug(f"Memory cache evicted: {removed_key[:16]}...")
            
            # Update disk cache
            if self._disk:
                data = self._serialize_response(response)
                self._disk.set(key_str, data, expire=ttl)
            
            logger.debug(f"Cached response: {key_str[:16]}...")
            return True
            
        except Exception as e:
            logger.warning(f"Cache write error: {e}")
            return False
    
    async def delete(self, key: CacheKey) -> bool:
        """Delete entry from cache."""
        key_str = key.to_string()
        
        deleted = False
        
        # Remove from memory
        async with self._lock:
            if key_str in self._memory:
                del self._memory[key_str]
                deleted = True
        
        # Remove from disk
        if self._disk:
            try:
                self._disk.delete(key_str)
                deleted = True
            except Exception:
                logger.debug("Disk cache delete failed for %s", key_str, exc_info=True)
        
        return deleted
    
    async def clear(self) -> None:
        """Clear all cached entries."""
        async with self._lock:
            self._memory.clear()
        
        if self._disk:
            self._disk.clear()
        
        self._hits = {"memory": 0, "disk": 0, "miss": 0}
        logger.info("Cache cleared")
    
    def _should_cache(self, response: LLMResponse) -> bool:
        """
        Determine if response should be cached.
        
        Don't cache:
        - Empty/error responses
        - Responses with no content and no tool calls
        """
        if not response:
            return False
        
        # Don't cache error responses
        has_content = bool(response.content and response.content.strip())
        has_tool_calls = bool(response.tool_calls)
        
        return has_content or has_tool_calls
    
    def _serialize_response(self, response: LLMResponse) -> dict:
        """Serialize response for disk storage."""
        return {
            "content": response.content,
            "tool_calls": response.tool_calls,
            "model": response.model,
            "usage": response.usage,
        }
    
    def _deserialize_response(self, data: dict) -> LLMResponse:
        """Deserialize response from disk storage."""
        return LLMResponse(
            content=data.get("content", ""),
            tool_calls=data.get("tool_calls"),
            model=data.get("model", "unknown"),
            usage=data.get("usage", {}),
        )
    
    def get_stats(self) -> dict:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with hit rates, counts, etc.
        """
        total = sum(self._hits.values())
        hit_rate = 0.0
        if total > 0:
            hit_rate = (self._hits["memory"] + self._hits["disk"]) / total
        
        stats = {
            "hit_rate": hit_rate,
            "hits": self._hits.copy(),
            "total_requests": total,
            "memory_size": len(self._memory),
            "memory_limit": self.memory_size,
            "disk_enabled": self._disk is not None,
        }
        
        if self._disk:
            stats["disk_size"] = len(self._disk)
        
        return stats
    
    async def close(self) -> None:
        """Close cache and release resources."""
        if self._disk:
            self._disk.close()
            logger.debug("Disk cache closed")


# Factory for creating model-specific caches
_cache_instances: Dict[str, LLMCache] = {}
_cache_lock = asyncio.Lock()


async def get_cache_for_model(
    model_name: str,
    memory_size: int = 100,
    disk_path: str = ".cache/llm"
) -> LLMCache:
    """
    Get or create a cache instance for a specific model.
    
    This ensures model isolation - different models don't share cache entries.
    
    Args:
        model_name: Name of the model (e.g., "gpt-4o", "claude-3-sonnet")
        memory_size: Maximum items in memory cache
        disk_path: Base directory for disk cache
    
    Returns:
        LLMCache instance for the model
    """
    async with _cache_lock:
        if model_name not in _cache_instances:
            cache = LLMCache(
                memory_size=memory_size,
                disk_path=disk_path,
                model_name=model_name
            )
            _cache_instances[model_name] = cache
            logger.info(f"Created cache for model: {model_name}")
        
        return _cache_instances[model_name]


async def close_all_caches() -> None:
    """Close all cache instances."""
    global _cache_instances
    
    async with _cache_lock:
        for name, cache in list(_cache_instances.items()):
            try:
                await cache.close()
                logger.debug(f"Closed cache for {name}")
            except Exception as e:
                logger.warning(f"Error closing cache {name}: {e}")
        
        _cache_instances.clear()
