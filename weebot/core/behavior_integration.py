#!/usr/bin/env python3
"""Behavior tracking integration with Weebot sessions.

Automatically starts/stops behavior tracking when sessions start/end.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from weebot.core.behavior_tracker import BehaviorTracker, create_tracker, stop_tracker
from weebot.config.settings import WeebotSettings

logger = logging.getLogger(__name__)


class BehaviorIntegration:
    """Integrates behavior tracking with Weebot sessions."""
    
    def __init__(self):
        self.settings = WeebotSettings()
        self._enabled = self._check_enabled()
    
    def _check_enabled(self) -> bool:
        """Check if behavior tracking is enabled in settings."""
        # Check environment variable first
        import os
        if os.getenv("WEEBOT_BEHAVIOR_TRACKING", "true").lower() in ("false", "0", "no", "off"):
            return False
        return True
    
    @property
    def enabled(self) -> bool:
        """Whether behavior tracking is enabled."""
        return self._enabled
    
    async def on_session_start(
        self,
        session_id: str,
        working_dir: Optional[Path] = None,
        user_id: str = "default"
    ) -> Optional[BehaviorTracker]:
        """Called when a session starts. Starts behavior tracking.
        
        Args:
            session_id: The session identifier
            working_dir: Directory to watch (defaults to current working directory)
            user_id: User identifier for the session
            
        Returns:
            BehaviorTracker instance if started, None if disabled
        """
        if not self._enabled:
            logger.debug("Behavior tracking is disabled")
            return None
        
        watch_dir = working_dir or Path.cwd()
        
        # Don't track system directories
        if self._is_system_dir(watch_dir):
            logger.warning(f"Refusing to track system directory: {watch_dir}")
            return None
        
        try:
            tracker = create_tracker(
                session_id=session_id,
                watch_dir=watch_dir
            )
            tracker.start()
            
            logger.info(f"Started behavior tracking for session {session_id}")
            logger.info(f"Watching directory: {watch_dir}")
            
            return tracker
            
        except Exception as e:
            logger.warning(f"Failed to start behavior tracking: {e}")
            return None
    
    async def on_session_end(
        self,
        session_id: str,
        generate_report: bool = True
    ) -> Optional[dict]:
        """Called when a session ends. Stops behavior tracking.
        
        Args:
            session_id: The session identifier
            generate_report: Whether to generate a final report
            
        Returns:
            Session stats if tracking was active, None otherwise
        """
        tracker = None
        try:
            from weebot.core.behavior_tracker import get_tracker
            tracker = get_tracker(session_id)
        except Exception:
            pass
        
        if tracker is None:
            logger.debug(f"No active behavior tracker for session {session_id}")
            return None
        
        try:
            # Get final stats
            stats = tracker.get_stats()
            
            # Stop tracking
            tracker.stop()
            stop_tracker(session_id)
            
            logger.info(f"Stopped behavior tracking for session {session_id}")
            logger.info(f"Final trust score: {stats['trust_score']}%")
            
            # Generate self-knowledge if significant activity
            if generate_report and stats.get('trust_details', {}).get('total_actions', 0) > 0:
                try:
                    from weebot.core.behavior_reporting import SelfKnowledgeGenerator
                    gen = SelfKnowledgeGenerator()
                    gen.save()
                    logger.info("Updated self-knowledge file")
                except Exception as e:
                    logger.warning(f"Failed to generate self-knowledge: {e}")
            
            return stats
            
        except Exception as e:
            logger.warning(f"Error stopping behavior tracking: {e}")
            return None
    
    def _is_system_dir(self, path: Path) -> bool:
        """Check if path is a system directory that shouldn't be tracked."""
        system_paths = [
            "/", "/bin", "/boot", "/dev", "/etc", "/lib", "/proc",
            "/root", "/sbin", "/sys", "/usr", "/var",
            "C:\\Windows", "C:\\Program Files", "C:\\ProgramData",
            str(Path.home()),  # Don't track home root
        ]
        
        path_str = str(path.resolve())
        for system_path in system_paths:
            if path_str == system_path or path_str.startswith(system_path + "/") or path_str.startswith(system_path + "\\"):
                return True
        
        return False


# Global integration instance
_behavior_integration = BehaviorIntegration()


def get_behavior_integration() -> BehaviorIntegration:
    """Get the global behavior integration instance."""
    return _behavior_integration


# Convenience functions for use in AgentRunner
def start_session_tracking(
    session_id: str,
    working_dir: Optional[Path] = None,
    user_id: str = "default"
) -> Optional[BehaviorTracker]:
    """Start behavior tracking for a session."""
    import asyncio
    return asyncio.run(_behavior_integration.on_session_start(session_id, working_dir, user_id))


async def start_session_tracking_async(
    session_id: str,
    working_dir: Optional[Path] = None,
    user_id: str = "default"
) -> Optional[BehaviorTracker]:
    """Async version: Start behavior tracking for a session."""
    return await _behavior_integration.on_session_start(session_id, working_dir, user_id)


def stop_session_tracking(
    session_id: str,
    generate_report: bool = True
) -> Optional[dict]:
    """Stop behavior tracking for a session."""
    import asyncio
    return asyncio.run(_behavior_integration.on_session_end(session_id, generate_report))


async def stop_session_tracking_async(
    session_id: str,
    generate_report: bool = True
) -> Optional[dict]:
    """Async version: Stop behavior tracking for a session."""
    return await _behavior_integration.on_session_end(session_id, generate_report)
