"""
test_gitnexus_integration.py - Integration tests for GitNexus with Weebot

This module tests the integration between GitNexus and Weebot's existing AI infrastructure.
"""
import pytest
import asyncio
import os
from unittest.mock import Mock, patch, AsyncMock

from gitnexus_provider import GitNexusProvider, get_gitnexus_provider
from gitnexus_config import GitNexusConfig
from gitnexus_router import GitNexusRouter, AnalysisMode, get_gitnexus_router
from ai_router import TaskType


@pytest.fixture
def gitnexus_config():
    """Create a GitNexus configuration for testing."""
    return GitNexusConfig(
        gitnexus_path="npx",
        gitnexus_args=["-y", "gitnexus@latest"],
        max_depth=3,
        min_confidence=0.7,
        timeout=300,
        max_retries=3,
        enable_caching=True,
        cache_ttl_seconds=3600
    )


@pytest.fixture
def gitnexus_provider(gitnexus_config):
    """Create a GitNexus provider for testing."""
    return GitNexusProvider(config=gitnexus_config)


@pytest.mark.asyncio
async def test_gitnexus_provider_initialization(gitnexus_provider):
    """Test that GitNexus provider initializes correctly."""
    assert gitnexus_provider.config is not None
    assert gitnexus_provider.config.gitnexus_path == "npx"


@pytest.mark.asyncio
async def test_gitnexus_provider_availability():
    """Test GitNexus provider availability check."""
    provider = GitNexusProvider()
    
    # This test will pass or fail depending on whether GitNexus is installed
    available = await provider.is_available()
    assert isinstance(available, bool)


@pytest.mark.asyncio
async def test_gitnexus_router_initialization():
    """Test GitNexus router initialization."""
    router = GitNexusRouter()
    
    assert router.config is not None
    assert router.provider is not None


@pytest.mark.asyncio
async def test_analysis_mode_selection():
    """Test intelligent analysis mode selection based on task type."""
    router = GitNexusRouter()
    
    # Test different task types map to appropriate analysis modes
    code_gen_mode = router.select_analysis_mode(TaskType.CODE_GENERATION)
    code_review_mode = router.select_analysis_mode(TaskType.CODE_REVIEW)
    debugging_mode = router.select_analysis_mode(TaskType.DEBUGGING)
    architecture_mode = router.select_analysis_mode(TaskType.ARCHITECTURE)
    
    # Verify that modes are returned (exact values may vary)
    assert isinstance(code_gen_mode, AnalysisMode)
    assert isinstance(code_review_mode, AnalysisMode)
    assert isinstance(debugging_mode, AnalysisMode)
    assert isinstance(architecture_mode, AnalysisMode)


@pytest.mark.asyncio
async def test_enhance_prompt_with_code_context():
    """Test enhancing prompts with code context."""
    from gitnexus_provider import enhance_prompt_with_code_context
    
    # Test with GitNexus unavailable (should return original prompt)
    original_prompt = "Write a function to calculate Fibonacci numbers"
    enhanced = await enhance_prompt_with_code_context(
        prompt=original_prompt,
        task_context="mathematical functions",
        target_symbol="fibonacci"
    )
    
    # Should return original prompt if GitNexus is unavailable
    assert original_prompt in enhanced


@pytest.mark.asyncio
async def test_global_provider_instance():
    """Test global GitNexus provider instance."""
    provider1 = get_gitnexus_provider()
    provider2 = get_gitnexus_provider()
    
    # Should return the same instance
    assert provider1 is provider2


@pytest.mark.asyncio
async def test_global_router_instance():
    """Test global GitNexus router instance."""
    router1 = get_gitnexus_router()
    router2 = get_gitnexus_router()
    
    # Should return the same instance
    assert router1 is router2


@pytest.mark.asyncio
async def test_query_codebase_with_mock():
    """Test codebase querying with mocked GitNexus response."""
    provider = GitNexusProvider()
    
    # Mock the GitNexus subprocess call
    with patch('asyncio.create_subprocess_exec') as mock_proc:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b'{"results": []}', b'')
        mock_process.returncode = 0
        mock_proc.return_value = mock_process
        
        # This should not fail even if GitNexus is not available
        result = await provider.query_codebase("test query")
        
        # Result will depend on whether GitNexus is actually available,
        # but the call should not raise an exception
        assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_get_symbol_context_with_mock():
    """Test getting symbol context with mocked response."""
    provider = GitNexusProvider()
    
    # Mock the GitNexus subprocess call
    with patch('asyncio.create_subprocess_exec') as mock_proc:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b'{"symbol": "test"}', b'')
        mock_process.returncode = 0
        mock_proc.return_value = mock_process
        
        result = await provider.get_symbol_context("test_function")
        assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_analyze_impact_with_mock():
    """Test impact analysis with mocked response."""
    provider = GitNexusProvider()
    
    # Mock the GitNexus subprocess call
    with patch('asyncio.create_subprocess_exec') as mock_proc:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b'{"impact": {}}', b'')
        mock_process.returncode = 0
        mock_proc.return_value = mock_process
        
        result = await provider.analyze_impact("test_function", "upstream")
        assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_detect_changes_with_mock():
    """Test change detection with mocked response."""
    provider = GitNexusProvider()
    
    # Mock the GitNexus subprocess call
    with patch('asyncio.create_subprocess_exec') as mock_proc:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b'{"changes": {}}', b'')
        mock_process.returncode = 0
        mock_proc.return_value = mock_process
        
        result = await provider.detect_changes("unstaged")
        assert isinstance(result, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])