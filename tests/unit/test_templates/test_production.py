"""Tests for production features."""
from __future__ import annotations

import pytest
from unittest.mock import Mock, patch, AsyncMock
import asyncio


class TestRateLimiter:
    """Test rate limiting."""
    
    @pytest.fixture
    def limiter(self):
        from weebot.templates.production import RateLimiter, RateLimitConfig
        return RateLimiter(
            backend="memory",
            config=RateLimitConfig(
                requests_per_second=10.0,
                burst_size=5,
            )
        )
    
    def test_rate_limit_allows_within_limit(self, limiter):
        """Requests within limit are allowed."""
        # Should allow burst_size requests
        for i in range(5):
            assert limiter.is_allowed("user1") is True
    
    def test_rate_limit_blocks_excess(self, limiter):
        """Requests over limit are blocked."""
        # Use up burst
        for i in range(5):
            limiter.is_allowed("user1")
        
        # Next request should be blocked
        assert limiter.is_allowed("user1") is False
    
    def test_rate_limit_per_user(self, limiter):
        """Rate limits are per-user."""
        # User1 uses all tokens
        for i in range(5):
            limiter.is_allowed("user1")
        
        # User2 should still have tokens
        assert limiter.is_allowed("user2") is True
    
    def test_wait_time_calculation(self, limiter):
        """Wait time is calculated correctly."""
        # Use up tokens
        for i in range(5):
            limiter.is_allowed("user1")
        
        wait_time = limiter.get_wait_time("user1")
        assert wait_time > 0


class TestAuthenticator:
    """Test authentication."""
    
    @pytest.fixture
    def auth(self):
        from weebot.templates.production import Authenticator
        return Authenticator()
    
    def test_register_user(self, auth):
        """User registration."""
        user = auth.register_user(
            user_id="user1",
            name="Test User",
            email="test@example.com",
            roles={"user"},
        )
        
        assert user.id == "user1"
        assert user.name == "Test User"
        assert "user" in user.roles
    
    def test_generate_api_key(self, auth):
        """API key generation."""
        auth.register_user("user1", "Test", "test@example.com")
        api_key = auth.generate_api_key("user1")
        
        assert len(api_key) == 32
        assert auth._users["user1"].api_key == api_key
    
    def test_authenticate_valid_key(self, auth):
        """Authentication with valid key."""
        auth.register_user("user1", "Test", "test@example.com")
        api_key = auth.generate_api_key("user1")
        
        user = auth.authenticate(api_key)
        assert user is not None
        assert user.id == "user1"
    
    def test_authenticate_invalid_key(self, auth):
        """Authentication with invalid key."""
        user = auth.authenticate("invalid_key")
        assert user is None
    
    def test_authorize_admin(self, auth):
        """Admin has all permissions."""
        auth.register_user("admin1", "Admin", "admin@example.com", roles={"admin"})
        admin = auth._users["admin1"]
        
        assert auth.authorize(admin, "template:execute") is True
        assert auth.authorize(admin, "template:delete") is True
    
    def test_authorize_user_limited(self, auth):
        """User has limited permissions."""
        auth.register_user("user1", "User", "user@example.com", roles={"user"})
        user = auth._users["user1"]
        
        assert auth.authorize(user, "template:execute") is True
        assert auth.authorize(user, "template:delete") is False


class TestHealthChecker:
    """Test health checks."""
    
    @pytest.fixture
    def checker(self):
        from weebot.templates.production import HealthChecker
        return HealthChecker()
    
    @pytest.mark.asyncio
    async def test_health_check_all_healthy(self, checker):
        """All checks pass."""
        checker.register_check("test1", lambda: True)
        checker.register_check("test2", lambda: True)
        
        result = await checker.check_all()
        
        assert result["healthy"] is True
        assert result["status"] == "healthy"
        assert result["checks"]["test1"]["healthy"] is True
    
    @pytest.mark.asyncio
    async def test_health_check_with_failure(self, checker):
        """One check fails."""
        checker.register_check("test1", lambda: True)
        checker.register_check("test2", lambda: False)
        
        result = await checker.check_all()
        
        assert result["healthy"] is False
        assert result["checks"]["test2"]["healthy"] is False
    
    @pytest.mark.asyncio
    async def test_health_check_with_error(self, checker):
        """One check throws error."""
        def failing_check():
            raise Exception("Check failed")
        
        checker.register_check("test1", lambda: True)
        checker.register_check("test2", failing_check)
        
        result = await checker.check_all()
        
        assert result["healthy"] is False
        assert result["checks"]["test2"]["status"] == "error"


class TestProductionEngine:
    """Test production template engine."""
    
    @pytest.fixture
    def prod_engine(self):
        from weebot.templates.production import ProductionTemplateEngine
        return ProductionTemplateEngine()
    
    @pytest.mark.asyncio
    async def test_execute_rate_limited(self, prod_engine):
        """Execution is rate limited."""
        # execute() rate-limits on the "execute" resource bucket, so drain that
        # bucket (not the default one) to trip the limit before template lookup.
        for i in range(25):
            prod_engine.rate_limiter.is_allowed("test_user", "execute")
        
        result = await prod_engine.execute(
            "Test Template",
            user=Mock(id="test_user", roles={"user"}),
        )
        
        assert result.success is False
        assert "Rate limit" in result.error
    
    @pytest.mark.asyncio
    async def test_execute_unauthorized(self, prod_engine):
        """Unauthorized user cannot execute."""
        from weebot.templates.production import User
        
        user = User(
            id="test_user",
            name="Test",
            email="test@example.com",
            roles={"readonly"},
        )
        
        result = await prod_engine.execute("Test Template", user=user)
        
        assert result.success is False
        assert "Insufficient permissions" in result.error
    
    @pytest.mark.asyncio
    async def test_health_check(self, prod_engine):
        """Health check returns status."""
        result = await prod_engine.health_check()
        
        assert "status" in result
        assert "timestamp" in result


class TestRedisCache:
    """Test Redis caching."""
    
    @pytest.fixture
    def mock_cache(self):
        with patch("weebot.templates.production.redis.from_url") as mock_redis:
            mock_instance = Mock()
            mock_redis.return_value = mock_instance
            
            from weebot.templates.production import RedisCache
            cache = RedisCache(valkey_url="redis://localhost:6379/0")
            cache.redis = mock_instance
            
            yield cache
    
    def test_set_and_get_template(self, mock_cache):
        """Template caching."""
        from weebot.templates.parser import WorkflowTemplate
        
        template = WorkflowTemplate(
            name="Test",
            version="1.0",
            workflow={"task1": {}},
        )
        
        mock_cache.set_template("Test", "1.0", template)
        
        # Verify Redis setex was called
        mock_cache.redis.setex.assert_called_once()
    
    def test_get_stats(self, mock_cache):
        """Cache statistics."""
        mock_cache.redis.info.return_value = {
            "used_memory": 1024 * 1024,  # 1 MB
        }
        mock_cache.redis.info.return_value = {
            "connected_clients": 5,
        }
        
        stats = mock_cache.get_stats()
        
        assert "used_memory_mb" in stats


class TestDatabaseManager:
    """Test database manager."""
    
    @pytest.mark.asyncio
    async def test_record_execution(self):
        """Record execution in database."""
        with patch("weebot.templates.production.create_async_engine"):
            from weebot.templates.production import DatabaseManager
            
            db = DatabaseManager("postgresql+asyncpg://user:pass@localhost/db")
            
            # Mock session
            mock_session = AsyncMock()
            db.async_session = Mock(return_value=mock_session)
            
            from weebot.templates.engine import TemplateExecutionResult
            result = TemplateExecutionResult(
                success=True,
                template_name="Test",
                parameters={},
                execution_time_ms=100,
            )
            
            # This would need proper async mocking
            # await db.record_execution(...)


class TestIntegration:
    """Integration tests."""
    
    @pytest.mark.asyncio
    async def test_full_production_flow(self):
        """Complete production flow."""
        from weebot.templates.production import (
            ProductionTemplateEngine,
            Authenticator,
            User,
        )
        
        # Create engine
        engine = ProductionTemplateEngine()

        # Register the template so the flow reaches execution (not a registry miss)
        from weebot.templates.parser import WorkflowTemplate
        engine.engine.registry.register(
            WorkflowTemplate(name="Test Template", version="1.0", workflow={"task1": {}})
        )

        # Register and authenticate user
        engine.authenticator.register_user(
            "user1",
            "Test User",
            "test@example.com",
            roles={"user"},
        )
        api_key = engine.authenticator.generate_api_key("user1")
        user = engine.authenticator.authenticate(api_key)
        
        assert user is not None
        
        # Execute (will be rate limited in this test)
        result = await engine.execute("Test Template", user=user)
        
        # Should either succeed or be rate limited
        assert result.success or "Rate limit" in result.error
