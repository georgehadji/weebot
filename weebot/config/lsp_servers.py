"""Which language servers H20 can use, and which of them are installed."""

from __future__ import annotations

import shutil
from collections.abc import Callable

# language -> server argv candidates, first one found on PATH wins.
SERVERS: dict[str, tuple[tuple[str, ...], ...]] = {
    "python": (("pyright-langserver", "--stdio"), ("ruff", "server")),
    "typescript": (("typescript-language-server", "--stdio"),),
}
# suffix -> (server language, LSP languageId)
LANGUAGES: dict[str, tuple[str, str]] = {
    ".py": ("python", "python"),
    ".ts": ("typescript", "typescript"),
    ".tsx": ("typescript", "typescriptreact"),
    ".js": ("typescript", "javascript"),
    ".jsx": ("typescript", "javascriptreact"),
}


def installed_servers(which: Callable[[str], str | None] = shutil.which) -> dict[str, str | None]:
    """For each language, the server command that would run (None if none is installed)."""
    return {
        language: next((c[0] for c in candidates if which(c[0])), None)
        for language, candidates in SERVERS.items()
    }
