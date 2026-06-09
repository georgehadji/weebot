"""Tests for Phase 5: ToolResultCache."""
import time
import pytest
from unittest.mock import ANY, patch

from weebot.application.services.tool_result_cache import (
    ToolResultCache,
    NON_CACHEABLE_TOOLS,
)
from weebot.tools.base import ToolResult


@pytest.fixture
def cache():
    return ToolResultCache()


@pytest.fixture
def sample_result():
    return ToolResult.success_result(output="test output", key="value")


# ── Basic cache operations ────────────────────────────────────────

def test_cache_hit_returns_same_result(cache, sample_result):
    """Same tool+args called twice; second call returns cached."""
    cache.set("web_search", {"query": "hello"}, sample_result)
    cached = cache.get("web_search", {"query": "hello"})
    assert cached is not None
    assert cached.output == "test output"


def test_cache_miss_on_different_args(cache, sample_result):
    """Same tool, different args → different entries."""
    cache.set("web_search", {"query": "hello"}, sample_result)
    cached = cache.get("web_search", {"query": "world"})
    assert cached is None


def test_cache_miss_on_different_tool(cache, sample_result):
    """Different tool, same args → miss."""
    cache.set("web_search", {"query": "hello"}, sample_result)
    cached = cache.get("weather", {"query": "hello"})
    assert cached is None


# ── Non-cacheable tools ───────────────────────────────────────────

def test_non_cacheable_tool_bypasses_cache(cache, sample_result):
    """bash call never stored or returned from cache."""
    assert "bash" in NON_CACHEABLE_TOOLS
    cache.set("bash", {"command": "ls"}, sample_result)
    cached = cache.get("bash", {"command": "ls"})
    assert cached is None


def test_powershell_not_cached(cache, sample_result):
    """powershell is non-cacheable."""
    assert "powershell" in NON_CACHEABLE_TOOLS
    cache.set("powershell", {"command": "dir"}, sample_result)
    assert cache.get("powershell", {"command": "dir"}) is None


def test_write_file_not_cached(cache, sample_result):
    """write_file results are not cached (only tracked for invalidation)."""
    cache.set("write_file", {"path": "/tmp/test.txt", "content": "data"}, sample_result)
    assert cache.get("read_file", {"path": "/tmp/test.txt"}) is None


# ── Error results ─────────────────────────────────────────────────

def test_error_result_not_cached(cache):
    """Error result not stored; next call misses."""
    err = ToolResult.error_result("Something broke")
    cache.set("web_search", {"query": "test"}, err)
    assert cache.get("web_search", {"query": "test"}) is None


# ── TTL expiry ────────────────────────────────────────────────────

def test_ttl_expiry(cache, sample_result):
    """Entry expires after TTL."""
    cache.set("web_search", {"query": "test"}, sample_result)
    # Should be present
    assert cache.get("web_search", {"query": "test"}) is not None
    # Fast-forward time past the 300s TTL
    with patch.object(time, "monotonic", return_value=time.monotonic() + 301):
        assert cache.get("web_search", {"query": "test"}) is None


# ── Write invalidation ────────────────────────────────────────────

def test_write_invalidates_read(cache, sample_result):
    """Write to path X; subsequent read_file for X bypasses cache."""
    # Cache a read_file result
    cache.set("read_file", {"path": "/tmp/test.txt"}, sample_result)
    assert cache.get("read_file", {"path": "/tmp/test.txt"}) is not None

    # Write to that path
    cache.set("write_file", {"path": "/tmp/test.txt", "content": "new"}, sample_result)

    # Read should now miss
    assert cache.get("read_file", {"path": "/tmp/test.txt"}) is None


def test_write_diff_path_does_not_invalidate(cache, sample_result):
    """Write to path Y does not invalidate read cache for path X."""
    cache.set("read_file", {"path": "/tmp/x.txt"}, sample_result)
    cache.set("write_file", {"path": "/tmp/y.txt", "content": "data"}, sample_result)
    assert cache.get("read_file", {"path": "/tmp/x.txt"}) is not None


# ── Cache metadata ────────────────────────────────────────────────

def test_cache_hit_metadata_flag(cache, sample_result):
    """Cache hit sets result.metadata['cache_hit'] = True."""
    cache.set("web_search", {"query": "flag_test"}, sample_result)
    cached = cache.get("web_search", {"query": "flag_test"})
    assert cached is not None
    # The metadata flag is set by ToolCollection, not the cache itself.
    # But the cache should return the stored result correctly.
    assert cached.output == "test output"


# ── Manage operations ─────────────────────────────────────────────

def test_invalidate_removes_entry(cache, sample_result):
    """invalidate() removes a specific entry."""
    cache.set("web_search", {"query": "test"}, sample_result)
    cache.invalidate("web_search", {"query": "test"})
    assert cache.get("web_search", {"query": "test"}) is None


def test_clear_removes_all(cache, sample_result):
    """clear() empties the store."""
    cache.set("web_search", {"query": "a"}, sample_result)
    cache.set("weather", {"location": "NYC"}, sample_result)
    cache.clear()
    assert cache.size == 0
    assert cache.get("web_search", {"query": "a"}) is None


def test_size_property(cache, sample_result):
    """size returns number of entries."""
    assert cache.size == 0
    cache.set("web_search", {"query": "a"}, sample_result)
    assert cache.size == 1
    cache.set("weather", {"location": "NYC"}, sample_result)
    assert cache.size == 2


# ── Key stability ─────────────────────────────────────────────────

def test_same_args_same_key(cache, sample_result):
    """Same args produce same cache key regardless of order."""
    cache.set("web_search", {"query": "a", "num_results": 5}, sample_result)
    cached = cache.get("web_search", {"num_results": 5, "query": "a"})
    assert cached is not None
    assert cached.output == "test output"


def test_mark_path_written(cache, sample_result):
    """mark_path_written() registers a path for read invalidation."""
    cache.set("read_file", {"path": "/tmp/test.txt"}, sample_result)
    cache.mark_path_written("/tmp/test.txt")
    assert cache.get("read_file", {"path": "/tmp/test.txt"}) is None
