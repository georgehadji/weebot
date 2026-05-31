"""Browser session persistence manager."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class BrowserSessionManager:
    """Manage persistent browser sessions.

    Saves and restores:
    - Cookies
    - localStorage
    - sessionStorage

    Sessions are stored as JSON files in the configured directory.
    """

    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        """Initialize session manager.

        Args:
            storage_dir: Directory for session files. Defaults to ./data/browser_sessions
        """
        if storage_dir is None:
            storage_dir = Path(__file__).parent.parent.parent.parent / "data" / "browser_sessions"
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _get_session_path(self, name: str) -> Path:
        """Get file path for session."""
        # Sanitize name to prevent path traversal
        safe_name = "".join(c for c in name if c.isalnum() or c in "-_")
        if not safe_name:
            safe_name = "default"
        # Additional safety: ensure no path separators remain
        safe_name = safe_name.replace("..", "")
        return self.storage_dir / f"{safe_name}.json"

    async def save_session(self, name: str, context) -> bool:
        """Save browser session state.

        Args:
            name: Session identifier
            context: Playwright browser context

        Returns:
            True if saved successfully
        """
        try:
            path = self._get_session_path(name)
            storage_state = await context.storage_state()

            session_data = {
                "version": 1,
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "storage_state": storage_state,
            }

            path.write_text(json.dumps(session_data, indent=2), encoding="utf-8")
            logger.info(f"Saved browser session '{name}' to {path}")
            return True

        except Exception as e:
            logger.error(f"Failed to save session '{name}': {e}")
            return False

    async def load_session(self, name: str, context) -> bool:
        """Restore browser session state.

        Args:
            name: Session identifier
            context: Playwright browser context

        Returns:
            True if loaded successfully
        """
        try:
            path = self._get_session_path(name)
            if not path.exists():
                logger.debug(f"Session '{name}' not found at {path}")
                return False

            session_data = json.loads(path.read_text(encoding="utf-8"))
            storage_state = session_data.get("storage_state", {})

            # Restore cookies
            cookies = storage_state.get("cookies", [])
            if cookies:
                await context.add_cookies(cookies)
                logger.debug(f"Restored {len(cookies)} cookies for session '{name}'")

            # Restore origins (localStorage, sessionStorage)
            origins = storage_state.get("origins", [])
            if origins:
                page = context.pages[0] if context.pages else await context.new_page()

                for origin_data in origins:
                    origin = origin_data.get("origin", "")
                    local_storage = origin_data.get("localStorage", [])
                    session_storage = origin_data.get("sessionStorage", [])

                    if local_storage or session_storage:
                        # Navigate to origin first
                        try:
                            await page.goto(origin, timeout=10000)
                        except Exception as e:
                            logger.warning(f"Failed to navigate to {origin} for storage restore: {e}")
                            continue

                        # Restore localStorage
                        for item in local_storage:
                            key = item.get("name", "")
                            value = item.get("value", "")
                            if key:
                                try:
                                    escaped_key = json.dumps(key)
                                    escaped_value = json.dumps(value)
                                    await page.evaluate(f"localStorage.setItem({escaped_key}, {escaped_value})")
                                except Exception as e:
                                    logger.debug(f"Failed to restore localStorage item {key}: {e}")

                        # Restore sessionStorage
                        for item in session_storage:
                            key = item.get("name", "")
                            value = item.get("value", "")
                            if key:
                                try:
                                    escaped_key = json.dumps(key)
                                    escaped_value = json.dumps(value)
                                    await page.evaluate(f"sessionStorage.setItem({escaped_key}, {escaped_value})")
                                except Exception as e:
                                    logger.debug(f"Failed to restore sessionStorage item {key}: {e}")

            logger.info(f"Loaded browser session '{name}' from {path}")
            return True

        except Exception as e:
            logger.error(f"Failed to load session '{name}': {e}")
            return False

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all saved sessions with metadata."""
        sessions = []
        for path in self.storage_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                sessions.append({
                    "name": path.stem,
                    "saved_at": data.get("saved_at", "unknown"),
                    "path": str(path),
                })
            except Exception:
                pass
        return sorted(sessions, key=lambda x: x["saved_at"], reverse=True)

    def delete_session(self, name: str) -> bool:
        """Delete a saved session."""
        path = self._get_session_path(name)
        if path.exists():
            path.unlink()
            logger.info(f"Deleted session '{name}'")
            return True
        return False

    def session_exists(self, name: str) -> bool:
        """Check if a session exists."""
        path = self._get_session_path(name)
        return path.exists()
