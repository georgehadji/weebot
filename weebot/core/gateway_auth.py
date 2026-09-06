"""Gateway Auth — allowlist/blocklist for gateway access control.

Controls which users, chats, and platforms can interact with Weebot
through gateway interfaces.  Supports DM-pairing and admin restrictions.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from weebot.core.durable_state import preserve_unreadable, write_text_atomic
from weebot.domain.models.gateway_session import GatewaySessionKey

logger = logging.getLogger(__name__)


class GatewayAuth:
    """Access control for gateway messages.

    Supports:
    - Platform-level enable/disable
    - Chat-level allowlist
    - User-level allowlist/blocklist
    - Admin user IDs
    """

    def __init__(self, config_path: str | Path | None = None) -> None:
        self._config_path = (
            Path(config_path) if config_path else Path.home() / ".weebot" / "gateway_auth.json"
        )
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._rules: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        """Load auth rules from disk, preserving a file that will not parse.

        Falling back to defaults is the right *decision* -- the defaults deny by
        default, so a damaged config cannot admit anyone. But the damaged file
        is the only remaining record of the allowlist and blocklist an operator
        built, and the next administrative action saves over it. It is moved
        aside first, and the loss is reported at ERROR: an access-control list
        disappearing is not a warning.
        """
        if self._config_path.exists():
            try:
                return self._normalized(json.loads(self._config_path.read_text(encoding="utf-8")))
            except Exception as exc:
                kept = preserve_unreadable(self._config_path)
                logger.error(
                    "Gateway auth config could not be parsed (%s); falling back to "
                    "deny-by-default rules. The unreadable file was kept at %s. "
                    "Any allowlist or blocklist it held is NOT in effect.",
                    exc,
                    kept if kept is not None else "<could not be preserved>",
                )
        return {
            "allowed_platforms": ["telegram", "discord", "slack", "whatsapp", "signal", "email"],
            "allowed_chats": {},  # platform -> [chat_id]
            "allowed_users": {},  # platform -> [user_id]
            "blocked_users": {},  # platform -> [user_id]
            "admin_ids": {},  # platform -> [user_id]
            "allow_all_by_default": False,
        }

    @staticmethod
    def _normalized(raw: Any) -> dict[str, Any]:
        """Coerce a parsed config to the shape the accessors assume.

        JSON that parses is not JSON that is *shaped* right. ``[]``, ``"text"``
        and ``null`` are all valid JSON and all made ``self._rules.get(...)``
        raise AttributeError out of the authorization decision; a well-formed
        object with ``"allowed_platforms": null`` made ``in`` raise TypeError.
        An access-control gate must not be crashable by editing its own config
        file, so anything of the wrong type falls back to its default -- which
        denies -- rather than propagating.
        """
        if not isinstance(raw, dict):
            raise TypeError(f"expected a JSON object, got {type(raw).__name__}")
        shape: dict[str, type] = {
            "allowed_platforms": list,
            "allowed_chats": dict,
            "allowed_users": dict,
            "blocked_users": dict,
            "admin_ids": dict,
            "allow_all_by_default": bool,
        }
        rules: dict[str, Any] = {}
        for key, expected in shape.items():
            value = raw.get(key)
            if isinstance(value, expected):
                rules[key] = value
            elif key in raw:
                logger.error(
                    "Gateway auth config: %r is %s, expected %s — using the "
                    "deny-by-default value for it.",
                    key,
                    type(value).__name__,
                    expected.__name__,
                )
        # Only keys this class does not interpret are carried through verbatim.
        # `setdefault` over the whole payload would put a rejected value straight
        # back -- the recovery path re-admitting exactly what it just rejected.
        for key, value in raw.items():
            if key not in shape:
                rules[key] = value
        return rules

    def _save(self) -> None:
        """Persist auth rules to disk, atomically.

        A write that dies partway must not destroy the rules it was replacing:
        `block_user` is durable by contract, and a truncated config reads as no
        blocklist at all.
        """
        write_text_atomic(
            self._config_path, json.dumps(self._rules, indent=2, default=str)
        )

    def is_platform_allowed(self, platform: str) -> bool:
        """Check if a platform is enabled."""
        return platform in self._rules.get("allowed_platforms", [])

    def is_chat_allowed(self, key: GatewaySessionKey) -> bool:
        """Check if a chat is allowed.

        If an explicit allowlist exists for the platform, the chat must be on it.
        If allow_all_by_default is True, all chats are allowed unless blocked.
        """
        platform = key.platform

        # Check blocked users first
        blocked = self._rules.get("blocked_users", {}).get(platform, [])
        if key.chat_id in blocked:
            return False

        allowed = self._rules.get("allowed_chats", {}).get(platform, [])
        if allowed:
            return key.chat_id in allowed

        # No explicit allowlist — check default policy
        return self._rules.get("allow_all_by_default", False)

    def is_user_allowed(self, platform: str, user_id: str) -> bool:
        """Check if a user is allowed to interact."""
        blocked = self._rules.get("blocked_users", {}).get(platform, [])
        if user_id in blocked:
            return False

        allowed = self._rules.get("allowed_users", {}).get(platform, [])
        if allowed:
            return user_id in allowed

        return self._rules.get("allow_all_by_default", False)

    def is_admin(self, platform: str, user_id: str) -> bool:
        """Check if a user is an admin on this platform."""
        admins = self._rules.get("admin_ids", {}).get(platform, [])
        return user_id in admins

    def allow_chat(self, platform: str, chat_id: str) -> None:
        """Add a chat to the allowlist."""
        allowed = self._rules.setdefault("allowed_chats", {}).setdefault(platform, [])
        if chat_id not in allowed:
            allowed.append(chat_id)
            self._save()

    def block_chat(self, platform: str, chat_id: str) -> None:
        """Remove a chat from the allowlist (or add to blocklist)."""
        allowed = self._rules.setdefault("allowed_chats", {}).get(platform, [])
        if chat_id in allowed:
            allowed.remove(chat_id)
        blocked = self._rules.setdefault("blocked_users", {}).setdefault(platform, [])
        if chat_id not in blocked:
            blocked.append(chat_id)
        self._save()

    def allow_user(self, platform: str, user_id: str) -> None:
        """Add a user to the allowlist."""
        allowed = self._rules.setdefault("allowed_users", {}).setdefault(platform, [])
        if user_id not in allowed:
            allowed.append(user_id)
            self._save()

    def block_user(self, platform: str, user_id: str) -> None:
        """Block a user."""
        allowed = self._rules.setdefault("allowed_users", {}).get(platform, [])
        if user_id in allowed:
            allowed.remove(user_id)
        blocked = self._rules.setdefault("blocked_users", {}).setdefault(platform, [])
        if user_id not in blocked:
            blocked.append(user_id)
        self._save()

    def get_config(self) -> dict[str, Any]:
        """Return the full auth config (for CLI display)."""
        return dict(self._rules)
