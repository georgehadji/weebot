#!/usr/bin/env python3
"""Fail when a text/background token pair in weebot-ui's globals.css misses WCAG AA (4.5:1).

Phase 6.1 of ``tasks/specs/ui_ux_remediation_plan.md``. Both themes are checked: ``:root`` is the
light theme, ``.dark`` overrides it. Tokens are ``H S% L%`` triples, possibly ``var(--other)``.

Usage:
    python scripts/check_ui_contrast.py            # exit 1 on any failing pair
    python scripts/check_ui_contrast.py --list     # print every ratio
"""

from __future__ import annotations

import colorsys
import pathlib
import re
import sys

_CSS = pathlib.Path(__file__).resolve().parents[1] / "weebot-ui" / "src" / "app" / "globals.css"
AA_TEXT = 4.5

# (foreground token, background token)
PAIRS: list[tuple[str, str]] = [
    ("foreground", "background"),
    ("foreground", "surface-1"),
    ("foreground", "surface-2"),
    ("foreground", "surface-3"),
    ("card-foreground", "card"),
    ("popover-foreground", "popover"),
    ("muted-foreground", "background"),
    ("muted-foreground", "surface-1"),
    ("muted-foreground", "surface-2"),
    ("muted-foreground", "surface-3"),
    ("muted-foreground", "muted"),
    ("primary-foreground", "primary"),
    ("secondary-foreground", "secondary"),
    ("accent-foreground", "accent"),
    ("destructive-foreground", "destructive"),
    ("agent-foreground", "agent"),
    ("user-bubble-foreground", "user-bubble"),
    *[(f"status-{s}-fg", bg) for s in ("live", "waiting", "error") for bg in ("background", "surface-1", "surface-2", "surface-3")],
]

_BLOCK = re.compile(r"(:root|\.dark)\s*\{([^}]*)\}", re.DOTALL)
_DECL = re.compile(r"--([\w-]+)\s*:\s*([^;]+);")
_VAR = re.compile(r"var\(--([\w-]+)\)")
_HSL = re.compile(r"^\s*([\d.]+)\s+([\d.]+)%\s+([\d.]+)%\s*$")


def parse_tokens(css: str) -> dict[str, dict[str, str]]:
    """``{"light": {...}, "dark": {...}}`` of raw token values (dark includes light as fallback)."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    themes: dict[str, dict[str, str]] = {"light": {}, "dark": {}}
    for selector, body in _BLOCK.findall(css):
        target = "light" if selector == ":root" else "dark"
        themes[target].update({name: value.strip() for name, value in _DECL.findall(body)})
    themes["dark"] = {**themes["light"], **themes["dark"]}
    return themes


def resolve(tokens: dict[str, str], name: str, seen: frozenset[str] = frozenset()) -> tuple[float, float, float]:
    """The token as sRGB floats, following ``var()`` references."""
    if name in seen or name not in tokens:
        raise KeyError(f"cannot resolve --{name}")
    value = tokens[name]
    ref = _VAR.fullmatch(value.strip())
    if ref:
        return resolve(tokens, ref.group(1), seen | {name})
    m = _HSL.match(value)
    if not m:
        raise ValueError(f"--{name}: {value!r} is not an 'H S% L%' triple")
    h, s, light = float(m[1]) / 360, float(m[2]) / 100, float(m[3]) / 100
    r, g, b = colorsys.hls_to_rgb(h, light, s)
    return r, g, b


def luminance(rgb: tuple[float, float, float]) -> float:
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg: tuple[float, float, float], bg: tuple[float, float, float]) -> float:
    hi, lo = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def check(css: str) -> list[tuple[str, str, str, float]]:
    """Every ``(theme, fg, bg, ratio)`` for the declared pairs."""
    rows = []
    for theme, tokens in parse_tokens(css).items():
        for fg, bg in PAIRS:
            if fg in tokens and bg in tokens:
                rows.append((theme, fg, bg, contrast(resolve(tokens, fg), resolve(tokens, bg))))
    return rows


def main(argv: list[str]) -> int:
    rows = check(_CSS.read_text(encoding="utf-8"))
    failing = [r for r in rows if r[3] < AA_TEXT]
    shown = rows if "--list" in argv else failing
    for theme, fg, bg, ratio in shown:
        print(f"{theme:5} {fg:24} on {bg:12} {ratio:5.2f}:1 {'FAIL' if ratio < AA_TEXT else 'ok'}")
    if failing:
        print(f"{len(failing)} pair(s) below {AA_TEXT}:1. Darken the foreground token, do not lower the bar.")
        return 1
    print(f"{len(rows)} token pairs meet {AA_TEXT}:1 in both themes.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
