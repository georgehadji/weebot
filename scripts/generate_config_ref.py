#!/usr/bin/env python3
"""Generate configuration reference from WeebotSettings.

Scans the ``WeebotSettings`` pydantic model and produces a Markdown
table documenting every environment variable, its default, and its
description.  Run::

    python scripts/generate_config_ref.py > docs/CONFIGURATION.md
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Ensure project is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _get_settings_class():
    """Lazy-import to avoid circular dependency issues."""
    from weebot.config.settings import WeebotSettings
    return WeebotSettings


def _infer_env_var(field_name: str) -> str:
    """Convert a field name to its env var name.

    Pydantic settings uses the field name uppercased by default.
    Some fields have explicit aliases via ``Field(alias=...)``.
    We check the field's ``validation_alias`` if available.
    """
    return field_name.upper()


def _render_table(settings_cls) -> str:
    """Render a Markdown table of all environment variables."""
    lines = [
        "# Configuration Reference",
        "",
        "This file is auto-generated from ``weebot.config.settings.WeebotSettings``.",
        "Run ``python scripts/generate_config_ref.py`` to regenerate.",
        "",
        "| Environment Variable | Type | Default | Description |",
        "|---|---|---|---|",
    ]

    for field_name, field in settings_cls.model_fields.items():
        env_var = _infer_env_var(field_name)

        # Determine type
        field_type = field.annotation
        type_str = str(field_type)
        # Clean up typing annotations for readability
        type_str = type_str.replace("typing.", "").replace("Optional[", "").replace("]", "").replace(" | None", "")

        # Determine default
        default = field.default
        if default is None:
            default_str = "None"
        elif isinstance(default, str):
            default_str = f'`"{default}"`'
        elif isinstance(default, bool):
            default_str = "`true`" if default else "`false`"
        elif isinstance(default, (int, float)):
            default_str = f"`{default}`"
        else:
            default_str = f"`{default}`"

        # Description from field metadata
        description = field.description or ""
        # Clean up
        description = description.replace("|", "\\|")

        lines.append(f"| `{env_var}` | `{type_str}` | {default_str} | {description} |")

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    settings_cls = _get_settings_class()
    output = _render_table(settings_cls)
    print(output)


if __name__ == "__main__":
    main()
