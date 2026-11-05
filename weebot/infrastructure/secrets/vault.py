"""A credential vault read from a JSON file, backed by secret sources (H19).

The file lists handles; it holds references, not secrets::

    {"credentials": [
      {"id": "github", "origin": "https://github.com", "label": "GitHub",
       "username": "me@example.com", "password": "op://Private/GitHub/password"}
    ]}

``password`` must be a reference a source can read (``op://``, ``bws://``, ``env://``): a plain
value there is refused when the file loads, so the vault file is safe to keep in a repository
and to show to the model. ``username`` may be a plain value. Secrets are read when a field is
filled, not at startup, and are not cached.

A handle is bound to one origin. Filling on a page whose origin differs, such as a look-alike
domain the model was sent to, is refused (anti-phishing).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from weebot.application.ports.credential_vault_port import (
    CredentialError,
    CredentialHandle,
    CredentialVaultPort,
)
from weebot.application.ports.secret_source_port import SecretSourceError, SecretSourcePort

logger = logging.getLogger(__name__)

_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_REF = re.compile(r"^([a-z][a-z0-9+.-]*)://\S+$")
_DEFAULT_PORTS = {"http": 80, "https": 443}
_MIN_REDACTED = 4  # a shorter value would blank ordinary words from page text
MARKER = "[VAULT]"


def origin_of(url: str) -> str:
    """``scheme://host[:port]`` of *url*, lowercase, default port dropped; '' when it has none."""
    parts = urlsplit(url.strip())
    if parts.scheme not in _DEFAULT_PORTS or not parts.hostname:
        return ""
    port = f":{parts.port}" if parts.port and parts.port != _DEFAULT_PORTS[parts.scheme] else ""
    return f"{parts.scheme}://{parts.hostname.lower()}{port}"


@dataclass(frozen=True)
class _Entry:
    handle: CredentialHandle
    username: str
    password: str


class ConfiguredVault(CredentialVaultPort):
    def __init__(self, entries: Sequence[_Entry], sources: Sequence[SecretSourcePort]) -> None:
        self._entries = {e.handle.id: e for e in entries}
        self._sources = {s.scheme: s for s in sources}
        self._filled: set[str] = set()

    @classmethod
    def from_file(cls, path: str | Path, sources: Sequence[SecretSourcePort]) -> ConfiguredVault:
        """Load the file. Raises ValueError if any entry is unusable; nothing half-loads."""
        known = {s.scheme for s in sources}
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        entries: list[_Entry] = []
        for item in raw.get("credentials", []):
            ident = str(item.get("id", ""))
            origin = origin_of(str(item.get("origin", "")))
            password = str(item.get("password", ""))
            match = _REF.match(password)
            if not _ID.match(ident):
                raise ValueError(f"credential id {ident!r} must be letters, digits, - or _")
            if not origin:
                raise ValueError(f"credential {ident!r} needs an http(s) origin")
            if not match or match.group(1) not in known:
                raise ValueError(
                    f"credential {ident!r}: password must be a reference "
                    f"({', '.join(sorted(known))}://...), not a plain value"
                )
            if ident in {e.handle.id for e in entries}:
                raise ValueError(f"credential id {ident!r} is listed twice")
            entries.append(
                _Entry(
                    CredentialHandle(ident, origin, str(item.get("label", ""))),
                    str(item.get("username", "")),
                    password,
                )
            )
        return cls(entries, sources)

    def list_handles(self, origin: str) -> list[CredentialHandle]:
        wanted = origin_of(origin)
        return [e.handle for e in self._entries.values() if e.handle.origin == wanted]

    async def fill(
        self,
        handle_id: str,
        page: Any,
        *,
        selector: str,
        field: Literal["username", "password"] = "password",
        timeout_ms: int = 30000,
    ) -> None:
        entry = self._entries.get(handle_id)
        if entry is None:
            raise CredentialError(f"unknown credential handle {handle_id!r}")
        here = origin_of(str(page.url))
        if here != entry.handle.origin:
            raise CredentialError(
                f"handle {handle_id!r} is for {entry.handle.origin}; "
                f"this page is {here or 'not http(s)'}"
            )
        value = await asyncio.to_thread(self._read, getattr(entry, field))
        try:
            await page.fill(selector, value, timeout=timeout_ms)
        except Exception as exc:
            # Playwright may echo the call; say only what kind of failure it was.
            raise CredentialError(f"could not fill {selector!r}: {type(exc).__name__}") from None
        if field == "password" and len(value) >= _MIN_REDACTED:
            self._filled.add(value)

    def _read(self, stored: str) -> str:
        match = _REF.match(stored)
        source = self._sources.get(match.group(1)) if match else None
        if source is None:
            return stored  # a plain username
        try:
            secret = source.resolve(stored)
        except SecretSourceError as exc:
            raise CredentialError(str(exc)) from None
        if secret is None:
            raise CredentialError(f"{source.name} has no value for that reference")
        return secret.value

    def redact(self, text: str) -> str:
        for value in sorted(self._filled, key=len, reverse=True):
            text = text.replace(value, MARKER)
        return text
