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

import ipaddress
import json
import logging
import re
import socket
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from weebot.config.secret_accessor import SecretAccessor
from weebot.core.durable_state import preserve_unreadable, write_text_atomic
from weebot.core.jmap_ops import sends_mail

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def is_enforcing() -> bool:
    """Return True when a blocking decision should actually block the call.

    Read at call time rather than import time so the toggle takes effect for
    already-imported callers (and so tests can flip it via monkeypatch).
    """
    return SecretAccessor.get("WEEBOT_EGRESS_ENFORCE", "true").lower() not in ("false", "0", "no")


# Allowlist file location (reuses the existing persistence dir convention)
_ALLOWLIST_PATH: Path = Path(
    SecretAccessor.get(
        "WEEBOT_EGRESS_ALLOWLIST",
        str(Path(__file__).parent.parent.parent / "weebot_egress_allowlist.json"),
    )
    or str(Path(__file__).parent.parent.parent / "weebot_egress_allowlist.json")
)

# ---------------------------------------------------------------------------
# Sensitive-payload patterns (extends AgentMemorySanitizer credential patterns)
# ---------------------------------------------------------------------------

_SENSITIVE_PATTERNS: list[re.Pattern] = [
    re.compile(r'api\s*[_-]?\s*key["\s:=]+[A-Za-z0-9_\-]{20,}', re.IGNORECASE),
    re.compile(r'secret["\s:=]+[A-Za-z0-9_\-]{20,}', re.IGNORECASE),
    re.compile(r'password["\s:=]+\S{8,}', re.IGNORECASE),
    re.compile(r'token["\s:=]+[A-Za-z0-9_\-\.]{20,}', re.IGNORECASE),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]+", re.IGNORECASE),
    re.compile(r"ghp_[A-Za-z0-9]{36}", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9]{48,}", re.IGNORECASE),
    # AWS-specific
    re.compile(r"AKIA[A-Z0-9]{16}", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----"),
    # DB connection strings
    re.compile(r'(?:postgres|mysql|mongodb|redis|valkey)://[^\s<>"]+', re.IGNORECASE),
    # Bulk PII heuristic: CSV-ish row with email + number combo repeated ≥5 times
    re.compile(r"(?:[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}[,;\t][^\n]{0,80}\n){5,}"),
]

# ---------------------------------------------------------------------------
# Egress-verb detection per tool type
# ---------------------------------------------------------------------------

# bash / powershell — patterns indicating outbound send with a payload
_BASH_EGRESS_RE = re.compile(
    r"""
    (?:
        # curl/wget with data payload (--data, --data-binary, --data-raw, --data-urlencode)
        \bcurl\b [^#\n]* (?:-d|--data(?:-[a-z]+)?|-F|--form|-T|--upload-file|@\S)
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
        # git push to a remote (with or without explicit URL)
        \bgit\s+push\b
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

# python_execute code that imports a network library (ICM fix plan W3.8, F09).
# The sandbox does not stop it (Sandbox card), so the code itself is the signal.
_PYTHON_NETWORK_RE = re.compile(
    r"""
    ^\s*(?:import|from)\s+
        (?:requests|httpx|urllib3?|aiohttp|socket|http\.client|ftplib|smtplib|
           websockets?|paramiko|boto3|pycurl|grpc)\b
    |
    __import__\(\s*['"](?:requests|httpx|urllib|socket|http\.client|aiohttp)
    """,
    re.VERBOSE | re.MULTILINE,
)

# The same Python run from a shell: `python -c "import urllib.request; ..."`.
# Neither _BASH_EGRESS_RE nor the line-anchored pattern above saw it, and a real
# web run showed the planner picking this form (found in plan B2c).
_SHELL_PYTHON_NETWORK_RE = re.compile(
    r"""
    \b(?:python3?|py)(?:\.exe)?\s+(?:-\w+\s+)*-c\b
    .*?\b(?:import|from)\s+
        (?:requests|httpx|urllib3?|aiohttp|socket|http\.client|ftplib|smtplib|
           websockets?|paramiko|boto3|pycurl|grpc)\b
    """,
    re.VERBOSE | re.IGNORECASE | re.DOTALL,
)

# Shell commands that reach the network without necessarily sending a payload
# (downloads, package installs, git remotes). Not egress by themselves; used
# only while the sandbox network is off (W3.9, decision 7) so the first host a
# call needs is approved before that call gets network.
_SHELL_NETWORK_RE = re.compile(
    r"""
    \b(?P<fetch>curl|wget|Invoke-WebRequest|iwr|Invoke-RestMethod|irm|Start-BitsTransfer)\b
    | \b(?P<pypi>pip3?|uv|poetry|pipx)\s+(?:install|add|download|sync)\b
    | \b(?P<npm>npm|pnpm|yarn|npx)\s+(?:install|i|add|ci|exec|dlx)\b
    | \bgit\s+(?:clone|fetch|pull|push|ls-remote|submodule)\b
    | \b(?P<docker>docker)\s+pull\b
    """,
    re.VERBOSE | re.IGNORECASE,
)
_DEFAULT_HOSTS = {"pypi": "pypi.org", "npm": "registry.npmjs.org", "docker": "docker.io"}

# Other shell ways onto the network: lookups, .NET clients, raw sockets (A21). Egress only
# in a session that has read untrusted content, where any of them can carry data out.
_SHELL_ANY_NETWORK_RE = re.compile(
    r"""
    \b(?:nslookup|Resolve-DnsName|dig|ping|Test-NetConnection|tnc|Test-Connection|ssh|ftp|
         telnet|ncat|socat|certutil|bitsadmin)\b
    | \bNet\.(?:WebClient|Http|Sockets|Dns|WebRequest)
    """,
    re.VERBOSE | re.IGNORECASE,
)

# browser tools indicating form-submit or navigation with POST data.
# Entries are ``BaseTool.name`` values — the identifier ``classify()`` receives.
# "browser_tool" is the module file name of the tool registered as
# "browser_navigator", so it matched nothing and form submissions from the real
# browser tool were never classified as egress.
_BROWSER_EGRESS_TOOLS: frozenset[str] = frozenset(
    {"advanced_browser", "browser_navigator", "browser_tool", "computer_use"}
)
_BROWSER_EGRESS_ACTIONS: frozenset[str] = frozenset(
    {
        "submit",
        "click_submit",
        "navigate_post",
        "fill_and_submit",
        "form_submit",
        "post",
        "send_form",
    }
)

# Browser calls that can carry data out without a form submit (F41). A URL whose
# text holds a secret is egress anywhere; writing into a page (typed text, JS)
# is egress once the session has read untrusted content. Plain browsing is not.
_BROWSER_NAV_TOOLS: frozenset[str] = frozenset(
    {"advanced_browser", "browser_inspector", "web_scraper"}
)
_BROWSER_PAGE_WRITE_ACTIONS: frozenset[str] = frozenset({"fill", "type", "select", "evaluate"})

# notification / messaging tools that always send outbound
_NOTIFICATION_TOOLS: frozenset[str] = frozenset(
    {
        "telegram_send",
        "windows_toast",
        "notification",
        "schedule_tool",  # can dispatch external webhooks
    }
)

# atomic_mail JMAP presets that only read. Deliberately an allowlist of reads
# rather than a denylist of sends: ops_file resolves absolute and
# credential-dir-relative paths before falling back to bundled presets
# (adapters/atomicmail/vendor/.../jmap_request.py), so a denylist on the
# send_mail/reply names would be bypassed by writing the same JSON elsewhere.
_JMAP_READ_PRESETS: frozenset[str] = frozenset({"list_inbox"})


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
    recipient: str | None = None
    tool_name: str = ""
    detected_patterns: list[str] = field(default_factory=list)
    # Egress only because the call can reach the network in a tainted session (A21): it may
    # be a plain read, so the effect ledger does not treat a repeat as a resend.
    network_only: bool = False

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
# Network targets: what a host name or address points at
# ---------------------------------------------------------------------------


class HostClass(Enum):
    PUBLIC = "public"
    LOOPBACK = "loopback"
    LINK_LOCAL = "link_local"  # includes 169.254.169.254, the cloud metadata address
    PRIVATE = "private"  # RFC1918, unique-local


def _host_only(host: str) -> str:
    """``user:pw@[::1]:80`` -> ``::1``; ``127.0.0.1:8000`` -> ``127.0.0.1``."""
    host = host.rsplit("@", 1)[-1].strip().lower()
    if host.startswith("["):
        return host[1:].split("]", 1)[0]
    if host.count(":") == 1:  # host:port; two or more colons is a bare IPv6 literal
        host = host.split(":", 1)[0]
    return host.rstrip(".")


def _literal_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        _log.debug("egress_guard: %r is not a plain IP literal", host)
    try:  # the resolver also takes 127.1, 0x7f000001 and 2130706433
        return ipaddress.IPv4Address(socket.inet_aton(host))
    except OSError:
        return None


def _classify_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> HostClass:
    mapped = getattr(ip, "ipv4_mapped", None)
    ip = mapped or ip
    if ip.is_loopback or ip.is_unspecified:
        return HostClass.LOOPBACK
    if ip.is_link_local:
        return HostClass.LINK_LOCAL
    if ip.is_private:
        return HostClass.PRIVATE
    return HostClass.PUBLIC


def classify_host(host: str, resolve: bool = False) -> HostClass:
    """What *host* points at, from the address itself, never from the spelling.

    ``resolve=True`` also looks the name up and returns the most internal answer; it blocks
    on DNS, so async callers run it in a thread. A name that does not resolve is PUBLIC:
    nothing internal answers it. Resolution is a point-in-time check, not a defence against
    a name that changes its answer afterwards.
    """
    name = _host_only(host)
    ip = _literal_ip(name)
    if ip is not None:
        return _classify_ip(ip)
    if name == "localhost" or name.endswith(".localhost"):
        return HostClass.LOOPBACK
    if not resolve or not name:
        return HostClass.PUBLIC
    try:
        answers = {a[4][0] for a in socket.getaddrinfo(name, None)}
    except OSError:
        return HostClass.PUBLIC
    classes = {_classify_ip(ipaddress.ip_address(a.split("%")[0])) for a in answers}
    for internal in (HostClass.LOOPBACK, HostClass.LINK_LOCAL, HostClass.PRIVATE):
        if internal in classes:
            return internal
    return HostClass.PUBLIC


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
            kept = preserve_unreadable(self._path)
            _log.warning(
                "egress_guard: allowlist could not be parsed; starting empty and keeping "
                "the unreadable file at %s. Previously approved recipients will be "
                "prompted for again.",
                kept if kept is not None else "<could not be preserved>",
                exc_info=True,
            )

    def _save(self) -> None:
        try:
            write_text_atomic(self._path, json.dumps(self._allowed, indent=2))
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

    def __init__(self, allowlist: RecipientAllowlist | None = None) -> None:
        self._allowlist = allowlist or RecipientAllowlist()

    def classify(
        self, tool_name: str, args: dict[str, Any], untrusted_context_active: bool = False
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
            recipient, is_egress = self._browser_egress(tool_name, args, untrusted_context_active)
        if not is_egress and untrusted_context_active:
            recipient, is_egress = self._network_capable(tool_name, args)
            decision.network_only = is_egress
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

    def _browser_egress(
        self, tool_name: str, args: dict[str, Any], tainted: bool
    ) -> tuple[str | None, bool]:
        """(recipient, is_egress) for browser calls _detect_egress does not cover (F41)."""
        if tool_name not in _BROWSER_NAV_TOOLS:
            return None, False
        url = str(args.get("url", ""))
        if url and self._scan_sensitive(url):
            return self._normalize_host(url), True
        action = str(args.get("action", "")).lower()
        if tainted and tool_name == "advanced_browser" and action in _BROWSER_PAGE_WRITE_ACTIONS:
            return None, True  # the page's scripts see it; the host is the tab's, unknown here
        return None, False

    def _network_capable(self, tool_name: str, args: dict[str, Any]) -> tuple[str | None, bool]:
        """(recipient, is_egress) for a call that can reach the network at all (A21).

        Asked only for a session that has read untrusted content. There a GET with data in
        the query, a DNS lookup or a .NET client carries data out as well as a POST does, and
        Python reaches the network in ways no import list covers (importlib, subprocess).
        """
        tool_lower = tool_name.lower()
        if tool_lower in ("bash_execute", "powershell", "bash", "shell", "cmd", "terminal"):
            cmd = str(args.get("command", ""))
            if _SHELL_NETWORK_RE.search(cmd) or _SHELL_ANY_NETWORK_RE.search(cmd):
                return self._extract_host_from_cmd(cmd), True
        elif tool_lower in ("python_execute", "python") and str(args.get("code", "")).strip():
            return self._extract_host_from_cmd(str(args["code"])), True
        return None, False

    def network_use(self, tool_name: str, args: dict[str, Any]) -> tuple[bool, str | None]:
        """Does this shell call reach the network, and which host? (W3.9)

        Covers downloads and package installs that ``classify`` does not treat
        as egress. Returns ``(uses_network, host)``; host is the first URL
        host, else the registry the command implies, else None (unknown).
        """
        if tool_name.lower() not in ("bash_execute", "powershell", "bash", "shell", "cmd"):
            return False, None
        cmd = str(args.get("command", ""))
        match = _SHELL_NETWORK_RE.search(cmd)
        if not match:
            return False, None
        host = self._extract_host_from_cmd(cmd)
        if host is None:
            scp_like = re.search(r"\bgit@([\w.-]+):", cmd)
            host = scp_like.group(1).lower() if scp_like else None
        if host is None:
            kind = next((k for k in _DEFAULT_HOSTS if match.group(k)), None)
            host = _DEFAULT_HOSTS.get(kind) if kind else None
        return True, host

    @staticmethod
    def _is_internal(stable_id: str) -> bool:
        """A host id that points inside the machine or network; an address (``@``) is not."""
        return "@" not in stable_id and classify_host(stable_id) is not HostClass.PUBLIC

    def is_known_recipient(self, stable_id: str | None) -> bool:
        """Internal targets are never known: an "always" there is one prompt-injection from SSRF."""
        if not stable_id or self._is_internal(stable_id):
            return False
        return self._allowlist.is_known(stable_id)

    def approve_recipient(self, stable_id: str) -> None:
        """Persist a recipient as approved (called after human approval)."""
        if self._is_internal(stable_id):
            _log.warning("egress_guard: %s is an internal target, not stored as always", stable_id)
            return
        self._allowlist.approve(stable_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _detect_egress(self, tool_name: str, args: dict[str, Any]) -> tuple[str | None, bool]:
        """Return (stable_recipient_id, is_egress)."""

        # Bash / powershell / terminal: check command string (case-insensitive)
        tool_lower = tool_name.lower()
        if tool_lower in ("bash_execute", "powershell", "bash", "shell", "cmd", "terminal"):
            cmd = str(args.get("command", ""))
            if _BASH_EGRESS_RE.search(cmd) or _SHELL_PYTHON_NETWORK_RE.search(cmd):
                recipient = self._extract_host_from_cmd(cmd)
                return recipient, True
            return None, False

        # camofox_browser: typed text reaches the page (its scripts see each key).
        # The tool knows the tab's host, the guard does not, so the recipient is unknown.
        if tool_name == "camofox_browser":
            return None, str(args.get("action", "")).lower() == "type"

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

        # Atomic Mail — outbound send is the JMAP submission path only.
        # EmailSubmission/set is JMAP's only transmit verb; Email/set alone just
        # creates a draft, so gating on it would over-block. register/help,
        # dry runs and read presets are not egress.
        if tool_lower == "atomic_mail":
            if args.get("action") != "jmap_request" or args.get("dry_run"):
                return None, False
            ops_file = str(args.get("ops_file", "")).strip()
            if ops_file:
                if ops_file.removesuffix(".json") in _JMAP_READ_PRESETS:
                    return None, False
            elif not sends_mail(args.get("ops", ""), args.get("vars")):
                return None, False  # judged after $VAR substitution, as sent (R02)
            # $TO is the send_mail preset's recipient var. reply.json has no
            # extractable recipient -> None -> classify() treats an unknown
            # destination as first-time and requires approval (fails closed).
            recipient = str((args.get("vars") or {}).get("TO", "")).strip().lower()
            return recipient or None, True

        # python_execute: code that imports a network library (W3.8, F09).
        # Recipient: the first URL host in the code, else unknown -> approval.
        if tool_lower in ("python_execute", "python"):
            code = str(args.get("code", ""))
            if _PYTHON_NETWORK_RE.search(code):
                return self._extract_host_from_cmd(code), True
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

    def _extract_host_from_cmd(self, cmd: str) -> str | None:
        url_re = re.compile(r'https?://([^/\s"\']+)', re.IGNORECASE)
        m = url_re.search(cmd)
        return m.group(1).lower() if m else None

    def _normalize_host(self, url: str) -> str | None:
        m = re.match(r'https?://([^/\s"\']+)', url, re.IGNORECASE)
        return m.group(1).lower() if m else (url.lower() or None)


# ---------------------------------------------------------------------------
# Constructed directly by ToolExecutor (`_get_egress_guard`), one per executor.
# The instance holds only its recipient allowlist; there is no DI binding.
# ---------------------------------------------------------------------------
