"""Build the Ponytail skill prompt addendum for agent flows.

This helper lives in the Application layer so both CLI and web interfaces can
reuse it without the Application layer depending on Interface code.
"""
from __future__ import annotations

from pathlib import Path


_ALLOWED_MODES = {"off", "lite", "full", "ultra"}


def _read_persisted_mode() -> str:
    """Read the project-local Ponytail mode file if it exists."""
    mode_file = Path.cwd() / ".weebot" / "ponytail_mode.json"
    if not mode_file.exists():
        return "off"
    try:
        import json
        data = json.loads(mode_file.read_text(encoding="utf-8"))
        mode = str(data.get("mode", "off")).strip().lower()
        return mode if mode in _ALLOWED_MODES else "off"
    except Exception:
        return "off"


def get_ponytail_mode(mode: str | None = None) -> str:
    """Resolve the effective Ponytail mode.

    Priority:
    1. Explicit *mode* argument.
    2. ``WeebotSettings().ponytail_mode`` (from .env / environment).
    3. Project-local ``.weebot/ponytail_mode.json`` (written by CLI/web).

    Returns:
        One of ``"off"``, ``"lite"``, ``"full"``, ``"ultra"``.
    """
    resolved_mode = mode
    if resolved_mode is None:
        try:
            from weebot.config.settings import WeebotSettings

            resolved_mode = WeebotSettings().ponytail_mode
        except Exception:
            resolved_mode = "off"

    if resolved_mode == "off":
        resolved_mode = _read_persisted_mode()

    return resolved_mode if resolved_mode in _ALLOWED_MODES else "off"


def build_ponytail_skill_prompt(
    existing: str | None = None,
    mode: str | None = None,
) -> str | None:
    """Append Ponytail skill instructions when *mode* is active.

    Args:
        existing: Existing skill prompt to append to, if any.
        mode: Explicit Ponytail mode. If None, the mode is resolved from
            ``WeebotSettings`` and falls back to the project-local
            ``.weebot/ponytail_mode.json`` file.

    Returns:
        The updated skill prompt, or *existing* when Ponytail is off or the
        skill cannot be loaded.
    """
    resolved_mode = get_ponytail_mode(mode)

    if resolved_mode not in {"lite", "full", "ultra"}:
        return existing

    try:
        from weebot.application.skills.skill_registry import SkillRegistry

        registry = SkillRegistry()
        registry.load_all()
        skill = registry.get("ponytail")
        if skill is None:
            return existing
    except Exception:
        return existing

    header = f"[Ponytail mode: {resolved_mode}]\n\n"
    ponytail_text = header + skill.content

    if existing:
        return f"{existing}\n\n{ponytail_text}"
    return ponytail_text
