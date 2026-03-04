"""
Production Hardening for Template Engine.

Features:
- Rate limiting
- Authentication & authorization
- Database persistence
- Redis caching
- Health checks
- Audit logging
"""
from __future__ import annotations

import functools
import hashlib
import json
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Set, Union
from urllib.parse import urlparse

import redis
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Boolean, Text,
    create_engine, ForeignKey, Index
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.sql import func

from weebot.templates.engine import TemplateEngine, TemplateExecutionResult
from weebot.templates.parser import WorkflowTemplate

_log = logging.getLogger(__name__)

Base = declarative_base()


# ==================== Database Models ====================

class TemplateExecutionRecord(Base):
    """Database record for template executions."""
    __tablename__ = "template_executions"
    
    id = Column(Integer, primary_key=True)
    execution_id = Column(String(64), unique=True, index=True)
    template_name = Column(String(255), index=True)
    template_version = Column(String(50))
    user_id = Column(String(255), index=True)
    parameters_hash = Column(String(64))
    success = Column(Boolean)
    error_message = Column(Text, nullable=True)
    execution_time_ms = Column(Float)
    created_at = Column(DateTime, default=func.now())
    
    # Relationships
    audit_logs = relationship("AuditLog", back_populates="execution")
    
    __table_args__ = (
        Index('idx_executions_template_user', 'template_name', 'user_id'),
        Index('idx_executions_created', 'created_at'),
    )


class AuditLog(Base):
    """Audit log for template operations."""
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True)
    execution_id = Column(String(64), ForeignKey("template_executions.execution_id"))
    action = Column(String(50))  # EXECUTE, VALIDATE, EXPORT, etc.
    user_id = Column(String(255), index=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    details = Column(Text)  # JSON
    created_at = Column(DateTime, default=func.now())
    
    execution = relationship("TemplateExecutionRecord", back_populates="audit_logs")
    
    __table_args__ = (
        Index('idx_audit_user_action', 'user_id', 'action'),
        Index('idx_audit_created', 'created_at'),
    )


class UserQuota(Base):
    """User rate limiting quotas."""
    __tablename__ = "user_quotas"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), unique=True, index=True)
    executions_today = Column(Integer, default=0)
    executions_total = Column(Integer, default=0)
    last_execution_at = Column(DateTime, nullable=True)
    quota_reset_at = Column(DateTime, default=func.now())
    
    # Quota limits
    daily_limit = Column(Integer, default=100)
    hourly_limit = Column(Integer, default=20)


class TemplateCache(Base):
    """Database cache for parsed templates."""
    __tablename__ = "template_cache"
    
    id = Column(Integer, primary_key=True)
    template_name = Column(String(255), unique=True, index=True)
    template_data = Column(Text)  # JSON
    cache_hash = Column(String(64))
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    access_count = Column(Integer, default=0)
    last_accessed_at = Column(DateTime, nullable=True)


# ==================== Rate Limiting ====================

@dataclass
class RateLimitConfig:
    """Rate limiting configuration."""
    requests_per_second: float = 10.0
    requests_per_minute: int = 100
    requests_per_hour: int = 1000
    requests_per_day: int = 10000
    burst_size: int = 20


class RateLimiter:
    """
    Token bucket rate limiter with HARDEN mode bounds.
    
    HARDEN Mode Additions:
    - Max buckets limit to prevent memory exhaustion
    - LRU eviction for bucket management
    - Bucket TTL (time-based expiration)
    - Memory usage metrics
    
    Supports multiple backends: memory, Redis, database.
    """
    
    # HARDEN: Bounds to prevent memory exhaustion
    MAX_BUCKETS = 10000  # Maximum number of tracked users
    BUCKET_TTL_SECONDS = 3600  # 1 hour idle expiration
    EVICTION_BATCH_SIZE = 100  # Buckets to evict when at limit
    
    def __init__(
        self,
        backend: str = "memory",
        redis_client: Optional[redis.Redis] = None,
        config: Optional[RateLimitConfig] = None,
    ):
        self.backend = backend
        self.redis = redis_client
        self.config = config or RateLimitConfig()
        
        # Memory storage for "memory" backend
        self._buckets: Dict[str, Dict[str, Any]] = {}
        
        # HARDEN: Access tracking for LRU eviction
        self._access_times: Dict[str, float] = {}
        
        # HARDEN: Metrics for monitoring
        self._eviction_count = 0
        self._rejection_count = 0
        self._total_requests = 0
    
    def _get_bucket_key(self, user_id: str, resource: str) -> str:
        """Generate bucket key."""
        return f"rate_limit:{user_id}:{resource}"
    
    def is_allowed(self, user_id: str, resource: str = "default") -> bool:
        """
        Check if request is allowed under rate limit.
        
        Returns:
            True if allowed, False if rate limited
        """
        if self.backend == "redis" and self.redis:
            return self._check_redis(user_id, resource)
        else:
            return self._check_memory(user_id, resource)
    
    def _check_memory(self, user_id: str, resource: str) -> bool:
        """Memory-based rate limiting with HARDEN mode bounds."""
        key = self._get_bucket_key(user_id, resource)
        now = time.time()
        self._total_requests += 1
        
        # HARDEN: Check bucket TTL and clean expired
        self._cleanup_expired_buckets(now)
        
        # HARDEN: Enforce max buckets limit with LRU eviction
        if key not in self._buckets and len(self._buckets) >= self.MAX_BUCKETS:
            self._evict_lru_buckets()
            
            # If still at limit after eviction, reject
            if len(self._buckets) >= self.MAX_BUCKETS:
                self._rejection_count += 1
                _log.warning(
                    "Rate limiter at capacity (%d buckets). Rejecting request for %s.",
                    self.MAX_BUCKETS, user_id[:8]
                )
                return False
        
        if key not in self._buckets:
            self._buckets[key] = {
                "tokens": self.config.burst_size,
                "last_update": now,
            }
        
        bucket = self._buckets[key]
        
        # Add tokens based on time passed
        time_passed = now - bucket["last_update"]
        tokens_to_add = time_passed * self.config.requests_per_second
        bucket["tokens"] = min(
            self.config.burst_size,
            bucket["tokens"] + tokens_to_add
        )
        bucket["last_update"] = now
        
        # HARDEN: Track access time for LRU
        self._access_times[key] = now
        
        # Check if request can be processed
        if bucket["tokens"] >= 1:
            bucket["tokens"] -= 1
            return True
        
        return False
    
    def _cleanup_expired_buckets(self, now: float) -> None:
        """HARDEN: Remove buckets that have exceeded TTL."""
        expired_keys = [
            key for key, bucket in self._buckets.items()
            if now - bucket["last_update"] > self.BUCKET_TTL_SECONDS
        ]
        for key in expired_keys:
            del self._buckets[key]
            self._access_times.pop(key, None)
    
    def _evict_lru_buckets(self) -> None:
        """HARDEN: Evict least recently used buckets."""
        if not self._access_times:
            return
        
        # Sort by access time (oldest first)
        sorted_keys = sorted(
            self._access_times.keys(),
            key=lambda k: self._access_times[k]
        )
        
        # Evict batch
        to_evict = sorted_keys[:self.EVICTION_BATCH_SIZE]
        for key in to_evict:
            del self._buckets[key]
            del self._access_times[key]
        
        self._eviction_count += len(to_evict)
        _log.info("Evicted %d LRU rate limit buckets", len(to_evict))
    
    def get_metrics(self) -> Dict[str, Any]:
        """HARDEN: Get rate limiter metrics for monitoring."""
        return {
            "backend": self.backend,
            "active_buckets": len(self._buckets),
            "max_buckets": self.MAX_BUCKETS,
            "utilization": len(self._buckets) / self.MAX_BUCKETS,
            "total_requests": self._total_requests,
            "eviction_count": self._eviction_count,
            "rejection_count": self._rejection_count,
            "ttl_seconds": self.BUCKET_TTL_SECONDS,
        }
    
    def _check_redis(self, user_id: str, resource: str) -> bool:
        """Redis-based rate limiting."""
        key = self._get_bucket_key(user_id, resource)
        
        pipe = self.redis.pipeline()
        now = time.time()
        
        # Get current state
        pipe.hgetall(key)
        result = pipe.execute()
        
        bucket_data = result[0] if result else {}
        
        if not bucket_data:
            # Initialize bucket
            self.redis.hmset(key, {
                "tokens": self.config.burst_size - 1,
                "last_update": now,
            })
            self.redis.expire(key, 3600)  # 1 hour TTL
            return True
        
        tokens = float(bucket_data.get(b"tokens", 0))
        last_update = float(bucket_data.get(b"last_update", now))
        
        # Add tokens
        time_passed = now - last_update
        tokens = min(
            self.config.burst_size,
            tokens + time_passed * self.config.requests_per_second
        )
        
        if tokens >= 1:
            tokens -= 1
            self.redis.hmset(key, {
                "tokens": tokens,
                "last_update": now,
            })
            return True
        
        return False
    
    def get_wait_time(self, user_id: str, resource: str = "default") -> float:
        """Get seconds until next request is allowed."""
        if self.is_allowed(user_id, resource):
            return 0.0
        
        # Calculate wait time
        return 1.0 / self.config.requests_per_second


# ==================== Authentication ====================

@dataclass
class User:
    """User model."""
    id: str
    name: str
    email: str
    roles: Set[str]
    api_key: Optional[str] = None
    created_at: Optional[datetime] = None
    is_active: bool = True


class Authenticator:
    """
    Simple authenticator for template engine.
    
    Supports API key and token-based auth.
    """
    
    def __init__(self, db_session_factory=None):
        self.db = db_session_factory
        self._users: Dict[str, User] = {}
        self._api_keys: Dict[str, str] = {}  # api_key -> user_id
    
    def register_user(
        self,
        user_id: str,
        name: str,
        email: str,
        roles: Optional[Set[str]] = None,
    ) -> User:
        """Register a new user."""
        user = User(
            id=user_id,
            name=name,
            email=email,
            roles=roles or {"user"},
            created_at=datetime.now(),
        )
        
        self._users[user_id] = user
        
        _log.info(f"Registered user: {user_id}")
        return user
    
    def generate_api_key(self, user_id: str) -> str:
        """Generate API key for user."""
        if user_id not in self._users:
            raise ValueError(f"User {user_id} not found")
        
        # Generate key
        key_data = f"{user_id}:{datetime.now().isoformat()}"
        api_key = hashlib.sha256(key_data.encode()).hexdigest()[:32]
        
        self._users[user_id].api_key = api_key
        self._api_keys[api_key] = user_id
        
        return api_key
    
    def authenticate(self, api_key: str) -> Optional[User]:
        """Authenticate by API key."""
        user_id = self._api_keys.get(api_key)
        if user_id:
            user = self._users.get(user_id)
            if user and user.is_active:
                return user
        return None
    
    def authorize(self, user: User, permission: str) -> bool:
        """Check if user has permission."""
        # Simple RBAC
        role_permissions = {
            "admin": {"*"},  # All permissions
            "user": {
                "template:execute",
                "template:read",
                "template:list",
            },
            "readonly": {
                "template:read",
                "template:list",
            },
        }
        
        for role in user.roles:
            perms = role_permissions.get(role, set())
            if "*" in perms or permission in perms:
                return True
        
        return False


# ==================== Database Persistence ====================

class DatabaseManager:
    """
    Database manager for template persistence.
    
    Uses SQLAlchemy for ORM.
    """
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = create_async_engine(database_url, echo=False)
        self.async_session = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
    
    async def init_db(self):
        """Initialize database tables."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _log.info("Database initialized")
    
    async def record_execution(
        self,
        execution_id: str,
        template_name: str,
        template_version: str,
        user_id: str,
        parameters: Dict[str, Any],
        result: TemplateExecutionResult,
    ):
        """Record template execution."""
        async with self.async_session() as session:
            record = TemplateExecutionRecord(
                execution_id=execution_id,
                template_name=template_name,
                template_version=template_version,
                user_id=user_id,
                parameters_hash=hashlib.sha256(
                    json.dumps(parameters, sort_keys=True).encode()
                ).hexdigest(),
                success=result.success,
                error_message=result.error,
                execution_time_ms=result.execution_time_ms or 0,
            )
            session.add(record)
            await session.commit()
    
    async def log_audit(
        self,
        execution_id: str,
        action: str,
        user_id: str,
        details: Dict[str, Any],
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ):
        """Create audit log entry."""
        async with self.async_session() as session:
            log = AuditLog(
                execution_id=execution_id,
                action=action,
                user_id=user_id,
                ip_address=ip_address,
                user_agent=user_agent,
                details=json.dumps(details),
            )
            session.add(log)
            await session.commit()
    
    async def get_user_stats(self, user_id: str) -> Dict[str, Any]:
        """Get execution statistics for user."""
        async with self.async_session() as session:
            from sqlalchemy import select
            
            # Total executions
            result = await session.execute(
                select(func.count()).where(
                    TemplateExecutionRecord.user_id == user_id
                )
            )
            total = result.scalar()
            
            # Successful executions
            result = await session.execute(
                select(func.count()).where(
                    TemplateExecutionRecord.user_id == user_id,
                    TemplateExecutionRecord.success == True
                )
            )
            successful = result.scalar()
            
            # Average execution time
            result = await session.execute(
                select(func.avg(TemplateExecutionRecord.execution_time_ms)).where(
                    TemplateExecutionRecord.user_id == user_id
                )
            )
            avg_time = result.scalar() or 0
            
            return {
                "total_executions": total,
                "successful": successful,
                "failed": total - successful,
                "success_rate": successful / total if total > 0 else 0,
                "avg_execution_time_ms": avg_time,
            }


# ==================== Redis Caching ====================

class RedisCache:
    """
    Redis-based caching for templates and results.
    """
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        default_ttl: int = 3600,
    ):
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.default_ttl = default_ttl
    
    def get_template(self, name: str, version: str) -> Optional[WorkflowTemplate]:
        """Get cached template."""
        key = f"template:{name}:{version}"
        data = self.redis.get(key)
        
        if data:
            from weebot.templates.parser import TemplateParser
            parser = TemplateParser()
            return parser.parse(data)
        
        return None
    
    def set_template(
        self,
        name: str,
        version: str,
        template: WorkflowTemplate,
        ttl: Optional[int] = None,
    ):
        """Cache template."""
        key = f"template:{name}:{version}"
        
        import yaml
        data = yaml.dump({
            "name": template.name,
            "version": template.version,
            "description": template.description,
            "author": template.author,
            "parameters": {
                name: {
                    "type": param.type,
                    "description": param.description,
                    "required": param.required,
                    "default": param.default,
                }
                for name, param in template.parameters.items()
            },
            "workflow": template.workflow,
            "output": template.output,
        })
        
        self.redis.setex(key, ttl or self.default_ttl, data)
    
    def get_execution_result(self, execution_id: str) -> Optional[TemplateExecutionResult]:
        """Get cached execution result."""
        key = f"execution:{execution_id}"
        data = self.redis.get(key)
        
        if data:
            result_dict = json.loads(data)
            return TemplateExecutionResult(**result_dict)
        
        return None
    
    def set_execution_result(
        self,
        execution_id: str,
        result: TemplateExecutionResult,
        ttl: Optional[int] = None,
    ):
        """Cache execution result."""
        key = f"execution:{execution_id}"
        data = json.dumps({
            "success": result.success,
            "template_name": result.template_name,
            "parameters": result.parameters,
            "output": result.output,
            "error": result.error,
            "execution_time_ms": result.execution_time_ms,
            "task_results": result.task_results,
        })
        
        self.redis.setex(key, ttl or 300, data)  # 5 min default for results
    
    def invalidate_template(self, name: str, version: str):
        """Invalidate cached template."""
        key = f"template:{name}:{version}"
        self.redis.delete(key)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        info = self.redis.info("memory")
        return {
            "used_memory_mb": info.get("used_memory", 0) / 1024 / 1024,
            "connected_clients": self.redis.info().get("connected_clients", 0),
            "hit_rate": self.redis.info("stats").get("keyspace_hits", 0) / (
                self.redis.info("stats").get("keyspace_hits", 0) +
                self.redis.info("stats").get("keyspace_misses", 1)
            ),
        }


# ==================== Health Checks ====================

class HealthChecker:
    """Health check system for template engine."""
    
    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        redis_cache: Optional[RedisCache] = None,
    ):
        self.db = db_manager
        self.redis = redis_cache
        self.checks: Dict[str, Callable] = {}
    
    def register_check(self, name: str, check_func: Callable):
        """Register a health check."""
        self.checks[name] = check_func
    
    async def check_all(self) -> Dict[str, Any]:
        """Run all health checks."""
        results = {}
        healthy = True
        
        for name, check_func in self.checks.items():
            try:
                if asyncio.iscoroutinefunction(check_func):
                    result = await check_func()
                else:
                    result = check_func()
                
                results[name] = {
                    "status": "healthy" if result else "unhealthy",
                    "healthy": bool(result),
                }
                
                if not result:
                    healthy = False
                    
            except Exception as e:
                results[name] = {
                    "status": "error",
                    "healthy": False,
                    "error": str(e),
                }
                healthy = False
        
        return {
            "status": "healthy" if healthy else "unhealthy",
            "healthy": healthy,
            "checks": results,
            "timestamp": datetime.now().isoformat(),
        }
    
    def check_database(self) -> bool:
        """Check database connectivity."""
        if not self.db:
            return True  # No DB configured
        
        try:
            # Simple check
            import asyncio
            asyncio.run(self.db.init_db())
            return True
        except:
            return False
    
    def check_redis(self) -> bool:
        """Check Redis connectivity."""
        if not self.redis:
            return True  # No Redis configured
        
        try:
            self.redis.redis.ping()
            return True
        except:
            return False


import asyncio


# ==================== Production Engine ====================

class ProductionTemplateEngine:
    """
    Production-ready template engine.
    
    Combines all production features:
    - Rate limiting
    - Authentication
    - Database persistence
    - Redis caching
    - Health checks
    - Audit logging
    - Adaptive suggestions (NEW in v2.2.0)
    """
    
    def __init__(
        self,
        database_url: Optional[str] = None,
        redis_url: Optional[str] = None,
        rate_limit_backend: str = "memory",
        enable_adaptive: bool = False,
    ):
        self.engine = TemplateEngine()
        
        # Production components
        self.rate_limiter = RateLimiter(backend=rate_limit_backend)
        self.authenticator = Authenticator()
        self.db = DatabaseManager(database_url) if database_url else None
        self.cache = RedisCache(redis_url) if redis_url else None
        self.health = HealthChecker(self.db, self.cache)
        
        # Adaptive suggestion engine (NEW)
        self.adaptive_engine = None
        if enable_adaptive and self.db:
            from weebot.templates.adaptive import AdaptiveSuggestionEngine
            self.adaptive_engine = AdaptiveSuggestionEngine(
                db_session_factory=self.db.async_session,
                enable_collaborative=True,
                enable_personal=True,
                privacy_mode="strict",
            )
        
        # Register default health checks
        if self.db:
            self.health.register_check("database", self.health.check_database)
        if self.cache:
            self.health.register_check("redis", self.health.check_redis)
        if self.adaptive_engine:
            self.health.register_check("adaptive_engine", self._check_adaptive_engine)
    
    def _check_adaptive_engine(self) -> bool:
        """Health check for adaptive engine."""
        return self.adaptive_engine is not None
    
    async def get_suggestions(
        self,
        template_name: str,
        user: Optional[User] = None,
        current_input: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get parameter suggestions for a template.
        
        Args:
            template_name: Template to get suggestions for
            user: Current user
            current_input: Partial parameters already provided
            
        Returns:
            List of suggestions with confidence scores
        """
        if not self.adaptive_engine:
            return []
        
        from weebot.templates.adaptive import SuggestionContext
        from weebot.templates.feature_flags import get_feature_flags
        
        # Check feature flag
        user_id = user.id if user else "anonymous"
        if not get_feature_flags().is_enabled("adaptive_suggestions", user_id):
            return []
        
        # Get template
        template = self.engine.registry.get(template_name)
        if not template:
            return []
        
        # Build context
        context = SuggestionContext(
            user_id=user_id,
            template_name=template_name,
            template_version=template.version,
            previous_executions=0,  # Would query from DB
        )
        
        # Get suggestions
        suggestions = await self.adaptive_engine.suggest_parameters(
            template=template,
            context=context,
            current_input=current_input,
        )
        
        # Convert to dict for API
        return [
            {
                "parameter": s.parameter_name,
                "value": s.suggested_value,
                "confidence": s.confidence,
                "source": s.source,
                "success_rate": s.success_rate,
                "sample_size": s.sample_size,
            }
            for s in suggestions
        ]
    
    async def execute(
        self,
        template_name: str,
        parameters: Optional[Dict[str, Any]] = None,
        user: Optional[User] = None,
        dry_run: bool = False,
    ) -> TemplateExecutionResult:
        """
        Execute template with production features.
        
        Args:
            template_name: Template to execute
            parameters: Template parameters
            user: Authenticated user
            dry_run: Validate only
            
        Returns:
            Execution result
        """
        parameters = parameters or {}
        user_id = user.id if user else "anonymous"
        
        # Rate limiting
        if not self.rate_limiter.is_allowed(user_id, "execute"):
            return TemplateExecutionResult(
                success=False,
                template_name=template_name,
                parameters=parameters,
                error="Rate limit exceeded. Please try again later.",
            )
        
        # Authorization
        if user and not self.authenticator.authorize(user, "template:execute"):
            return TemplateExecutionResult(
                success=False,
                template_name=template_name,
                parameters=parameters,
                error="Insufficient permissions.",
            )
        
        # Check cache for identical execution
        if self.cache and not dry_run:
            cache_key = f"{template_name}:{hashlib.sha256(json.dumps(parameters, sort_keys=True).encode()).hexdigest()}"
            cached = self.cache.get_execution_result(cache_key)
            if cached:
                _log.info(f"Cache hit for {template_name}")
                return cached
        
        # Execute
        result = self.engine.execute(template_name, parameters, dry_run)
        
        # Persist to database
        if self.db and not dry_run:
            execution_id = hashlib.sha256(
                f"{template_name}:{user_id}:{datetime.now().isoformat()}".encode()
            ).hexdigest()[:16]
            
            await self.db.record_execution(
                execution_id=execution_id,
                template_name=template_name,
                template_version="1.0.0",  # TODO: Get from template
                user_id=user_id,
                parameters=parameters,
                result=result,
            )
            
            # Audit log
            await self.db.log_audit(
                execution_id=execution_id,
                action="EXECUTE",
                user_id=user_id,
                details={"dry_run": dry_run, "success": result.success},
            )
        
        # Cache result
        if self.cache and result.success and not dry_run:
            self.cache.set_execution_result(cache_key, result, ttl=300)
        
        # Record for adaptive learning (NEW)
        if self.adaptive_engine and not dry_run:
            try:
                template = self.engine.registry.get(template_name)
                if template:
                    await self.adaptive_engine.record_execution_outcome(
                        template=template,
                        user_id=user_id,
                        parameters=parameters,
                        success=result.success,
                        execution_time_ms=result.execution_time_ms or 0,
                        user_satisfaction=None,  # Could collect via feedback
                    )
            except Exception as e:
                _log.warning(f"Failed to record adaptive outcome: {e}")
                # Don't fail execution if adaptive recording fails
        
        return result
    
    async def health_check(self) -> Dict[str, Any]:
        """Run health checks."""
        return await self.health.check_all()
    
    async def get_adaptive_stats(
        self,
        template_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get adaptive suggestion statistics."""
        if not self.adaptive_engine:
            return {"enabled": False}
        
        stats = await self.adaptive_engine.get_suggestion_stats(template_name)
        stats["enabled"] = True
        return stats
    
    async def purge_adaptive_data(self, days: int = 30):
        """Purge old adaptive data (GDPR compliance)."""
        if self.adaptive_engine:
            await self.adaptive_engine.purge_old_data(days)
            _log.info(f"Purged adaptive data older than {days} days")
