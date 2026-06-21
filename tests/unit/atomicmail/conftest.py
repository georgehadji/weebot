"""Conftest for vendored atomicmail tests.

Adds the vendored package directory to sys.path so that
`from atomicmail.xxx import ...` resolves to the copy under
weebot/infrastructure/adapters/atomicmail/ rather than any installed package.
"""
from __future__ import annotations

import sys
from pathlib import Path

_VENDOR_PARENT = (
    Path(__file__).resolve().parents[3]
    / "weebot"
    / "infrastructure"
    / "adapters"
)
if str(_VENDOR_PARENT) not in sys.path:
    sys.path.insert(0, str(_VENDOR_PARENT))
