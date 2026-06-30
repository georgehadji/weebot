"""Egress Guard — gates outbound data sends before they execute.

Addresses the Varonis/OpenClaw finding (2026): an agent that can read private data,
ingest untrusted content, and send data out (the "lethal trifecta") can be social-
engineered into forwarding credentials or PII with a single plain request.

This module sits in execute_tool() *before* the tool runs and returns a blocking
ToolResult when:
  - the tool is an outbound/egress vector (bash curl/POST, browser form-submit,
    telegram send, etc.), AND
  - the payload or recent context contains sensitive patterns OR the recipient is new.

Recipient allowlisting keys on a *stable identifier* (host/domain, email address,
chat_id) — never a display name — closing the InfoSec Write-ups display-name
spoofing variant.

Set WEEBOT_EGRESS_ENFORCE=false to run in detect-only mode (logs but doesn't block).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_ENFORCE: bool = os.environ.get("WEEBOT_EGRESS_ENFORCE", "true").lower() not in ("false", "0", "no")

# Allowlist file location (reuses the existing persistence dir convention)
_ALLOWLIST_PATH: Path = Path(os.environ.get(
    "WEEBOT_EGRESS_ALLOWLIST",
    Path(__file__).parent.parent.parent / "weebot_egress_allowlist.json",
))

# ---------------------------------------------------------------------------
# Sensitive-payload patterns (extends AgentMemorySanitizer credential patterns)
# ---------------------------------------------------------------------------

_SENSITIVE_PATTERNS: list[re.Pattern] = [
    re.compile(r'api\s*[_-]?\s*key["\s:=]+[A-Za-z0-9_\-]{20,}', re.IGNORECASE),
    re.compile(r'secret["\s:=]+[A-Za-z0-9_\-]{20,}', re.IGNORECASE),
    re.compile(r'password["\s:=]+\S{8,}', re.IGNORECASE),
    re.compile(r'token["\s:=]+[A-Za-z0-9_\-\.]{20,}', re.IGNORECASE),
    re.compile(r'Bearer\s+[A-Za-z0-9_\-\.]+', re.IGNORECASE),
    re.compile(r'ghp_[A-Za-z0-9]{36}', re.IGNORECASE),
    re.compile(r'sk-[A-Za-z0-9]{48,}', re.IGNORECASE),
    # AWS-specific
    re.compile(r'AKIA[A-Z0-9]{16}', re.IGNORECASE),
    re.compile(r'-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----'),
    # DB connection strings
    re.compile(r'(?:postgres|mysql|mongodb|redis|valkey)://[^\s<>"]+', re.IGNORECASE),
    # Bulk PII heuristic: CSV-ish row with email + number combo repeated ≥5 times
    re.compile(r'(?:[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}[,;\t][^\n]{0,80}\n){5,}'),
]

# ---------------------------------------------------------------------------
# Egress-verb detection per tool type
# ---------------------------------------------------------------------------

# bash / powershell — patterns indicating outbound send with a payload
_BASH_EGRESS_RE = re.compile(
    r"""
    (?:
        # curl/wget with data payload
        \bcurl\b [^#\n]* (?:-d|--data|-F|--form|-T|--upload-file|@\S)
        |
        \bwget\b [^#\n]* (?:--post-(?:data|file)|--body-(?:data|file))
        |
        # Invoke-WebRequest / iwr / irm with body or post
        \b(?:Invoke-WebRequest|iwr|Invoke-RestMethod|irm)\b [^#\n]*
            (?:-Method\s+(?:POST|PUT|PATCH)|Body|-InFile)
        |
        # netcat send, scp, ftp, sftp push
        \bnc\b [^#\n]+ \d+
        |
        \bscp\b [^#\n]+
        |
        \bsftp\b [^#\n]+
        |
        # Send-MailMessage
        \bSend-MailMessage\b
        |
        # git push to a remote
        \bgit\s+push\b [^#\n]* (?:https?://|git@)
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

# browser tools indicating form-submit or navigation with POST data
_BROWSER_EGRESS_TOOLS: frozenset[str] = frozenset({
    "advanced_browser",
    "browser_tool",
    "computer_use",
})
_BROWSER_EGRESS_ACTIONS: frozenset[str] = frozenset({
    "submit", "click_submit", "navigate_post", "fill_and_submit",
    "form_submit", "post",
})

# notification / messaging tools that always send outbound
_NOTIFICATION_TOOLS: frozenset[str] = frozenset({
    "telegram_send",
    "windows_toast",
    "notification",
    "schedule_tool",   # can dispatch external webhooks
})


# ---------------------------------------------------------------------------
# Decision types
# ---------------------------------------------------------------------------

class EgressReason(Enum):
    SENSITIVE_PAYLOAD = "sensitive_payload"
    FIRST_TIME_RECIPIENT = "first_time_recipient"
    UNTRUSTED_CONTEXT = "untrusted_context"  # trifecta escalation


@dataclass
class EgressDecision:
    is_egress: bool = False
    requires_approval: bool = False
    reasons: list[EgressReason] = field(default_factory=list)
    recipient: Optional[str] = None
    tool_name: str = ""
    detected_patterns: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        parts = [f"tool={self.tool_name}"]
        if self.recipient:
            parts.append(f"recipient={self.recipient}")
        if self.reasons:
            parts.append("reasons=" + ",".join(r.value for r in self.reasons))
        if self.detected_patterns:
            parts.append("patterns=" + ",".join(self.detected_patterns[:3]))
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Allowlist (persisted as JSON, keyed on stable IDs)
# ---------------------------------------------------------------------------

class RecipientAllowlist:
    """Persistent allowlist of previously approved egress recipients.

    Keys are *stable* identifiers (host/domain, email address, Telegram chat_id).
    Display names are never used as keys — closing the InfoSec display-name-spoof
    vulnerability described in the OpenClaw analysis.
    """

    def __init__(self, path: Path = _ALLOWLIST_PATH) -> None:
        self._path = path
        self._allowed: dict[str, float] = {}  # stable_id → epoch timestamp approved
        self._load()

    def is_known(self, stable_id: str) -> bool:
        return stable_id.lower() in self._allowed

    def approve(self, stable_id: str) -> None:
        self._allowed[stable_id.lower()] = time.time()
        self._save()

    def _load(self) -> None:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._allowed = {k.lower(): float(v) for k, v in data.items()}
        except Exception:
            _log.debug("egress_guard: allowlist load failed, starting empty", exc_info=True)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._allowed, indent=2), encoding="utf-8")
        except Exception:
            _log.warning("egress_guard: allowlist save failed", exc_info=True)


# ---------------------------------------------------------------------------
# Main guard
# ---------------------------------------------------------------------------

class EgressGuard:
    """Classifies a pending tool call and decides whether it needs approval.

    Usage in execute_tool() before the actual tool.execute() call:
        decision = _egress_guard.classify(name, args, untrusted_context_active)
        if decision.requires_approval:
            return ToolResult.error_result(...)
    """

    def __init__(self, allowlist: Optional[RecipientAllowlist] = None) -> None:
        self._allowlist = allowlist or RecipientAllowlist()

    def classify(
        self,
        tool_name: str,
        args: dict[str, Any],
        untrusted_context_active: bool = False,
    ) -> EgressDecision:
        """Return an EgressDecision for the proposed tool call.

        Args:
            tool_name: The tool being invoked.
            args: The parsed arguments dict.
            untrusted_context_active: True if any untrusted-output tool has already
                run in the current step/session (trifecta escalation).
        """
        decision = EgressDecision(tool_name=tool_name)

        # 1. Is this an egress vector?
        recipient, is_egress = self._detect_egress(tool_name, args)
        if not is_egress:
            return decision

        decision.is_egress = True
        decision.recipient = recipient

        # 2. Collect the payload text to scan
        payload = self._extract_payload(tool_name, args)

        # 3. Sensitive-payload scan
        matched = self._scan_sensitive(payload)
        if matched:
            decision.reasons.append(EgressReason.SENSITIVE_PAYLOAD)
            decision.detected_patterns = matched

        # 4. First-time recipient check (stable-ID keyed).
        # If recipient is None (e.g. Send-MailMessage with no extractable URL),
        # treat it as an unknown destination and require approval.
        recipient_is_unknown = (not recipient) or (not self._allowlist.is_known(recipient))
        if recipient_is_unknown:
            decision.reasons.append(EgressReason.FIRST_TIME_RECIPIENT)

        # 5. Trifecta escalation: any egress from a session that has ingested
        # untrusted content always requires approval, regardless of recipient history
        # or payload sensitivity — the injected content itself is the payload.
        if untrusted_context_active:
            if EgressReason.UNTRUSTED_CONTEXT not in decision.reasons:
                decision.reasons.append(EgressReason.UNTRUSTED_CONTEXT)

        decision.requires_approval = bool(decision.reasons)
        return decision

    def approve_recipient(self, stable_id: str) -> None:
        """Persist a recipient as approved (called after human approval)."""
        self._allowlist.approve(stable_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _detect_egress(
        self, tool_name: str, args: dict[str, Any]
    ) -> tuple[Optional[str], bool]:
        """Return (stable_recipient_id, is_egress)."""

        # Bash / powershell: check command string
        if tool_name in ("bash_execute", "powershell", "bash", "shell"):
            cmd = str(args.get("command", ""))
            if _BASH_EGRESS_RE.search(cmd):
                recipient = self._extract_host_from_cmd(cmd)
                return recipient, True
            return None, False

        # Browser form-submit actions
        if tool_name in _BROWSER_EGRESS_TOOLS:
            action = str(args.get("action", args.get("operation", ""))).lower()
            if action in _BROWSER_EGRESS_ACTIONS:
                url = str(args.get("url", args.get("target", "")))
                return self._normalize_host(url), True
            # Navigation carrying POST data
            if args.get("data") or args.get("body") or args.get("post_data"):
                url = str(args.get("url", ""))
                return self._normalize_host(url), True
            return None, False

        # Notification / messaging tools always send outbound
        if tool_name in _NOTIFICATION_TOOLS:
            # For telegram, stable ID is the chat_id (numeric, not display name)
            chat_id = str(args.get("chat_id", args.get("recipient", "")))
            return chat_id or "notification_channel", True

        return None, False

    def _extract_payload(self, tool_name: str, args: dict[str, Any]) -> str:
        """Concatenate all string values from args into one text blob for scanning."""
        parts: list[str] = []
        for v in args.values():
            if isinstance(v, str):
                parts.append(v)
            elif isinstance(v, (list, dict)):
                parts.append(json.dumps(v))
        return "\n".join(parts)

    def _scan_sensitive(self, text: str) -> list[str]:
        """Return list of matched pattern descriptions (or empty if clean)."""
        if not text:
            return []
        matched: list[str] = []
        for p in _SENSITIVE_PATTERNS:
            if p.search(text):
                matched.append(p.pattern[:60])
        return matched

    def _extract_host_from_cmd(self, cmd: str) -> Optional[str]:
        url_re = re.compile(r'https?://([^/\s"\']+)', re.IGNORECASE)
        m = url_re.search(cmd)
        return m.group(1).lower() if m else None

    def _normalize_host(self, url: str) -> Optional[str]:
        m = re.match(r'https?://([^/\s"\']+)', url, re.IGNORECASE)
        return m.group(1).lower() if m else (url.lower() or None)


# ---------------------------------------------------------------------------
# Note: singleton is managed by the DI container.
# See `weebot.application.di._factories._create_egress_guard`.
# Direct `EgressGuard()` construction is supported for testing.
# ---------------------------------------------------------------------------
