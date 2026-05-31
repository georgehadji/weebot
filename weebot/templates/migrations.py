"""
Database migrations for Template Engine.

Manages schema creation and migrations for:
- Core template engine
- Production features
- Adaptive suggestions
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_log = logging.getLogger(__name__)


class SchemaManager:
    """Manages database schema for template engine."""
    
    CURRENT_VERSION = 2  # v2.2.0 schema
    
    def __init__(self, connection: AsyncConnection):
        self.conn = connection
    
    async def init_schema(self):
        """Initialize complete schema."""
        _log.info("Initializing template engine schema...")
        
        # Create core tables
        await self._create_core_tables()
        
        # Create production tables
        await self._create_production_tables()
        
        # Create adaptive tables (NEW in v2.2.0)
        await self._create_adaptive_tables()
        
        # Record schema version
        await self._set_schema_version(self.CURRENT_VERSION)
        
        _log.info(f"Schema initialized (version {self.CURRENT_VERSION})")
    
    async def migrate(self, from_version: int):
        """Migrate from old version to current."""
        _log.info(f"Migrating schema from v{from_version} to v{self.CURRENT_VERSION}...")
        
        if from_version < 2:
            await self._migrate_v1_to_v2()
        
        await self._set_schema_version(self.CURRENT_VERSION)
        _log.info("Migration complete")
    
    async def _create_core_tables(self):
        """Create core template engine tables."""
        # Template executions
        await self.conn.execute(text("""
            CREATE TABLE IF NOT EXISTS template_executions (
                id SERIAL PRIMARY KEY,
                execution_id VARCHAR(64) UNIQUE NOT NULL,
                template_name VARCHAR(255) NOT NULL,
                template_version VARCHAR(50),
                user_id VARCHAR(255) NOT NULL,
                parameters_hash VARCHAR(64),
                success BOOLEAN NOT NULL,
                error_message TEXT,
                execution_time_ms FLOAT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        
        await self.conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_executions_template_user 
            ON template_executions(template_name, user_id)
        """))
        
        await self.conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_executions_created 
            ON template_executions(created_at)
        """))
    
    async def _create_production_tables(self):
        """Create production feature tables."""
        # Audit logs
        await self.conn.execute(text("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id SERIAL PRIMARY KEY,
                execution_id VARCHAR(64) REFERENCES template_executions(execution_id),
                action VARCHAR(50) NOT NULL,
                user_id VARCHAR(255) NOT NULL,
                ip_address VARCHAR(45),
                user_agent TEXT,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        
        await self.conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_audit_user_action 
            ON audit_logs(user_id, action)
        """))
        
        # User quotas
        await self.conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_quotas (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(255) UNIQUE NOT NULL,
                executions_today INTEGER DEFAULT 0,
                executions_total INTEGER DEFAULT 0,
                last_execution_at TIMESTAMP,
                quota_reset_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                daily_limit INTEGER DEFAULT 100,
                hourly_limit INTEGER DEFAULT 20
            )
        """))
        
        # Template cache
        await self.conn.execute(text("""
            CREATE TABLE IF NOT EXISTS template_cache (
                id SERIAL PRIMARY KEY,
                template_name VARCHAR(255) UNIQUE NOT NULL,
                template_data TEXT NOT NULL,
                cache_hash VARCHAR(64),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                access_count INTEGER DEFAULT 0,
                last_accessed_at TIMESTAMP
            )
        """))
    
    async def _create_adaptive_tables(self):
        """Create adaptive suggestion tables (NEW in v2.2.0)."""
        # Parameter effectiveness
        await self.conn.execute(text("""
            CREATE TABLE IF NOT EXISTS parameter_effectiveness (
                id SERIAL PRIMARY KEY,
                template_name VARCHAR(255) NOT NULL,
                template_version VARCHAR(50),
                parameter_hash VARCHAR(64) NOT NULL,
                parameter_values_hash VARCHAR(64) NOT NULL,
                parameter_values_json TEXT NOT NULL,
                execution_count INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                avg_execution_time_ms FLOAT,
                user_satisfaction_score FLOAT,
                first_used_at TIMESTAMP,
                last_used_at TIMESTAMP,
                user_count INTEGER DEFAULT 0,
                can_be_used_for_suggestions BOOLEAN DEFAULT TRUE,
                UNIQUE(template_name, parameter_hash, parameter_values_hash)
            )
        """))
        
        await self.conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_param_eff_template 
            ON parameter_effectiveness(template_name)
        """))
        
        await self.conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_param_eff_hash 
            ON parameter_effectiveness(parameter_hash)
        """))
        
        # User preferences (anonymized)
        await self.conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_preferences_anonymized (
                id SERIAL PRIMARY KEY,
                user_hash VARCHAR(64) NOT NULL,
                template_name VARCHAR(255) NOT NULL,
                preferred_parameters_hash VARCHAR(64) NOT NULL,
                preferred_parameters_json TEXT NOT NULL,
                usage_count INTEGER DEFAULT 0,
                last_updated TIMESTAMP,
                UNIQUE(user_hash, template_name)
            )
        """))
        
        await self.conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_user_pref_hash 
            ON user_preferences_anonymized(user_hash)
        """))
        
        await self.conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_user_pref_template 
            ON user_preferences_anonymized(template_name)
        """))
    
    async def _migrate_v1_to_v2(self):
        """Migrate from v1 (Phase 3) to v2 (Phase 6 + Adaptive)."""
        _log.info("Running v1 -> v2 migration...")
        
        # Production tables
        await self._create_production_tables()
        
        # Adaptive tables
        await self._create_adaptive_tables()
        
        _log.info("v1 -> v2 migration complete")
    
    async def _set_schema_version(self, version: int):
        """Record schema version."""
        # Create version table if not exists
        await self.conn.execute(text("""
            CREATE TABLE IF NOT EXISTS template_engine_schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        
        # Insert or update version
        await self.conn.execute(text("""
            INSERT INTO template_engine_schema_version (version, applied_at)
            VALUES (:version, CURRENT_TIMESTAMP)
            ON CONFLICT (version) DO UPDATE 
            SET applied_at = CURRENT_TIMESTAMP
        """), {"version": version})
    
    async def get_schema_version(self) -> Optional[int]:
        """Get current schema version."""
        try:
            result = await self.conn.execute(text("""
                SELECT version FROM template_engine_schema_version
                ORDER BY version DESC LIMIT 1
            """))
            row = result.fetchone()
            return row[0] if row else None
        except Exception:
            return None  # No migrations table yet or other error


async def init_database(connection: AsyncConnection):
    """
    Initialize or migrate database schema.
    
    Usage:
        async with engine.begin() as conn:
            await init_database(conn)
    """
    manager = SchemaManager(connection)
    
    current_version = await manager.get_schema_version()
    
    if current_version is None:
        # Fresh install
        await manager.init_schema()
    elif current_version < SchemaManager.CURRENT_VERSION:
        # Migration needed
        await manager.migrate(current_version)
    else:
        _log.info(f"Schema up to date (version {current_version})")
