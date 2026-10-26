"""User-chosen model per agent role, set from the web UI.

A JSON file (``.weebot/role_models.json`` under the workspace, git-ignored) holds
``{role: model_id}``. ``model_refs.get_model_cascade_for_role`` puts the override first and
keeps the built-in cascade behind it, so a spent quota or a dead model still falls through.
The file is re-read when its mtime changes, so a change applies to the next call without a restart
(services the DI container builds once at startup keep the model they were built with).
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

_log = logging.getLogger(__name__)
_lock = threading.Lock()
_cache: tuple[float, dict[str, str]] | None = None


def overrides_path() -> Path:
    from weebot.config.settings import WORKSPACE_ROOT

    return WORKSPACE_ROOT / ".weebot" / "role_models.json"


def get_overrides() -> dict[str, str]:
    """``{role: model_id}``; empty when the file is missing or unreadable."""
    global _cache
    path = overrides_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    with _lock:
        if _cache is not None and _cache[0] == mtime:
            return dict(_cache[1])
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            data = {str(k): str(v) for k, v in raw.items() if v} if isinstance(raw, dict) else {}
        except (OSError, ValueError) as exc:
            _log.warning("role model overrides unreadable (%s): %s", path, exc)
            data = {}
        _cache = (mtime, data)
        return dict(data)


def _write(data: dict[str, str]) -> None:
    global _cache
    path = overrides_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    _cache = None


def set_override(role: str, model_id: str) -> None:
    with _lock:
        data = _read_unlocked()
        data[role] = model_id
        _write(data)


def clear_override(role: str) -> None:
    with _lock:
        data = _read_unlocked()
        if data.pop(role, None) is not None:
            _write(data)


def _read_unlocked() -> dict[str, str]:
    try:
        raw = json.loads(overrides_path().read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}
