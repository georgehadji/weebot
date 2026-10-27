"""Multi-layer security analysis for bash command validation.

Defense in Depth Architecture:
    Layer 1: Syntax Patterns — Detect known dangerous constructs
    Layer 2: Behavioral Analysis — Detect download+execute chains
    Layer 3: Encoded payloads — Base64 that decodes to shell, or opaque blobs
    Layer 4: Semantic Validation — Command structure analysis (no LLM)

Rules are data (ICM fix plan W3.6, F10): each detection is a ``Rule`` with an
id, a level, a layer and the reason it exists, and the calibration is pinned by
a golden corpus of malicious and benign commands
(``tests/unit/tools/data/command_corpus.json``). Change a rule, then run the
corpus: a calibration change is a measured change, not a fudge.

Runtime Safety:
    - All analysis is stateless (no side effects)
"""

from __future__ import annotations

import base64
import binascii
import math
import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum

from weebot.core.encoded_command import LONG_FORM as ENCODED_LONG_FORM
from weebot.core.encoded_command import SHORT_FORM as ENCODED_SHORT_FORM


class CommandRiskLevel(Enum):
    """Risk classification for commands."""

    SAFE = "safe"  # No issues detected
    SUSPICIOUS = "suspicious"  # Requires confirmation
    DANGEROUS = "dangerous"  # Blocked unless explicitly allowed


@dataclass
class SecurityAssessment:
    """Result of security analysis."""

    risk_level: CommandRiskLevel
    layer_triggered: int
    reason: str
    details: dict | None = None


@dataclass(frozen=True)
class Rule:
    """One detection. ``pattern`` is a case-insensitive regex."""

    id: str
    pattern: str
    level: CommandRiskLevel
    layer: int
    rationale: str


_D = CommandRiskLevel.DANGEROUS

# ── Layer 1: known dangerous constructs ─────────────────────────────────────
LAYER1_RULES: tuple[Rule, ...] = (
    # Encoded command execution
    Rule("l1.base64-decode-pipe", r"base64\s+(-d|--decode)\s*\|", _D, 1, "base64 decode pipe"),
    Rule(
        "l1.base64-herestring",
        r"base64\s+(-d|--decode)\s+<<<",
        _D,
        1,
        "base64 here-string decode",
    ),
    Rule("l1.eval-subst", r"eval\s*\$\(", _D, 1, "eval command substitution"),
    Rule("l1.eval-backtick", r"eval\s*`", _D, 1, "eval backticks"),
    Rule("l1.backtick-base64", r"`.*base64.*`", _D, 1, "backticks with base64"),
    Rule("l1.subst-base64", r"\$\(.*base64.*\)", _D, 1, "command substitution with base64"),
    Rule("l1.echo-b64-pipe", r"echo\s+[A-Za-z0-9+/]{40,}.*\|", _D, 1, "echo base64 to pipe"),
    Rule("l1.pipe-to-shell", r"\b(echo|printf)\s+.*\|\s*(bash|sh|zsh)", _D, 1, "pipe to shell"),
    Rule("l1.process-subst", r"<\(.*\)", _D, 1, "process substitution"),
    # Remote code execution vectors
    Rule(
        "l1.download-to-shell",
        r"\b(curl|wget|Invoke-WebRequest|iwr)\s+.*[\|\;\&]\s*\b(bash|sh|zsh|cmd|powershell|pwsh)",
        _D,
        1,
        "download pipe to shell",
    ),
    Rule(
        "l1.download-stdout-pipe",
        r"\b(curl|wget)\s+.*\s+-o\s*-\s*\|",
        _D,
        1,
        "curl/wget output to pipe",
    ),
    Rule("l1.source-subst", r"\b(source|\.)\s*<\(", _D, 1, "source process substitution"),
    Rule("l1.exec-shell", r"\bexec\s+\b(bash|sh|zsh)", _D, 1, "exec to new shell"),
    # Obfuscation techniques
    Rule("l1.hex-escape", r"\\x[0-9a-fA-F]{2}", _D, 1, "hex escape sequences"),
    Rule("l1.param-expansion", r"\$\{.*:#.*\}", _D, 1, "parameter expansion obfuscation"),
    # Backtick is PowerShell's escape character (`n=newline, `t=tab).
    # Single-char escapes are syntax, not injection. Only backtick groups with
    # 3+ chars of substantive content count as potential injection.
    Rule(
        "l1.nested-backtick",
        r"`[^`]{3,}`[^`]*`[^`]{3,}`",
        _D,
        1,
        "nested backtick injection",
    ),
    Rule("l1.nested-subst", r"\$\(\$\(", _D, 1, "nested command substitution"),
    # PowerShell-specific injection vectors
    Rule(
        "l1.ps-invoke-expression",
        r"\bInvoke-Expression\b",
        _D,
        1,
        "PowerShell Invoke-Expression (arbitrary code exec)",
    ),
    Rule("l1.ps-iex", r"\biex\s+", _D, 1, "PowerShell iex alias (arbitrary code exec)"),
    Rule(
        "l1.ps-webclient-download",
        r"Net\.WebClient.*\.DownloadString",
        _D,
        1,
        "PowerShell remote download+exec",
    ),
    Rule(
        "l1.ps-hidden-process",
        r"Start-Process\s+-WindowStyle\s+Hidden",
        _D,
        1,
        "PowerShell hidden window execution",
    ),
    Rule(
        "l1.ps-tcp-client",
        r"New-Object\s+System\.Net\.Sockets\.TCPClient",
        _D,
        1,
        "PowerShell reverse shell",
    ),
    Rule(
        "l1.ps-assembly-load",
        r"\[System\.Reflection\.Assembly\]::Load",
        _D,
        1,
        "PowerShell reflective assembly load",
    ),
    Rule("l1.ps-iwr-iex", r"\bIWR?\s+.*\|.*iex", _D, 1, "PowerShell Invoke-WebRequest pipe to iex"),
    # Caught before W3.6 only because the 1.2x entropy fudge lifted UTF-16LE
    # base64 (~3.8 bits) over the threshold; named explicitly now.
    Rule("l1.ps-encoded-command", ENCODED_LONG_FORM, _D, 1, "PowerShell encoded command"),
    Rule(
        "l1.ps-encoded-command-short", ENCODED_SHORT_FORM, _D, 1, "PowerShell encoded command (-e)"
    ),
    Rule("l1.ps-curl-iex", r"curl.*\.ps1.*\|.*iex", _D, 1, "PowerShell curl-to-iex"),
)

# ── Layer 2: download-then-execute chains ───────────────────────────────────
_SHELLS = r"(bash|sh|zsh|python|python3|perl|ruby|node|cmd|powershell|pwsh)"
LAYER2_RULES: tuple[Rule, ...] = (
    Rule(
        "l2.download-then-shell",
        rf"(curl|wget|Invoke-WebRequest|iwr).*(&&|\||;).*\b{_SHELLS}\b",
        _D,
        2,
        "download followed by a shell or interpreter",
    ),
    Rule(
        "l2.shell-then-download",
        r"\b(bash|sh|zsh|python|python3|perl|ruby|node)\b.*(&&|\||;).*\b(curl|wget|Invoke-WebRequest|iwr)\b",
        _D,
        2,
        "interpreter followed by a download",
    ),
    Rule(
        "l2.download-pipe-shell",
        rf"(curl|wget|Invoke-WebRequest|iwr).*\|\s*\b{_SHELLS}\b",
        _D,
        2,
        "download piped to a shell",
    ),
    Rule(
        "l2.fetch-pipe-run",
        r"\b(download|fetch|get-content|get).*\s+.*\s+.*\|\s*\b(execute|run|start|bash|sh|zsh)\b",
        _D,
        2,
        "fetch piped to an executor",
    ),
    Rule(
        "l2.chmod-then-shell",
        rf"(chmod\s+\+x|\.\/|\./).*(&&|\||;).*\b{_SHELLS}\b",
        _D,
        2,
        "make executable, then run a shell",
    ),
    Rule(
        "l2.download-chmod-run",
        r"(curl|wget|Invoke-WebRequest|iwr).+(&&|\|).+(chmod\s+\+x).+(&&|\|).+(\./|\w+\.sh)",
        _D,
        2,
        "download, chmod +x, execute",
    ),
)

# Token co-occurrence (lower-case word tokens). The old table also listed
# "|", "." and "+x" as targets and mixed-case indicators; none of those can be
# produced by the word tokenizer below, so they never matched (F10).
LAYER2_COMBINATIONS: tuple[tuple[frozenset[str], frozenset[str], str], ...] = (
    (
        frozenset({"curl", "wget", "invoke-webrequest", "iwr"}),
        frozenset({"bash", "sh", "zsh", "chmod"}),
        "download to shell execution",
    ),
    (
        frozenset({"base64", "openssl"}),
        frozenset({"eval", "exec", "source"}),
        "decode to execution",
    ),
    (frozenset({"temp", "tmp", "mktemp"}), frozenset({"chmod", "execute"}), "temp file execution"),
)

# ── Layer 3: encoded payloads ───────────────────────────────────────────────
# Calibrated against tests/unit/tools/data/command_corpus.json. Raw Shannon
# entropy only: the former 1.2x multiplier for base64-looking strings (added
# "to match test expectations") lifted 40-char hex commit hashes (~3.6 bits)
# over the threshold, so `git checkout <sha>` was refused (F10).
ENTROPY_THRESHOLD = 4.0  # bits/char; hex cannot exceed log2(16) = 4.0
DECODE_MIN_LENGTH = 16  # shortest base64 run worth decoding
OPAQUE_MIN_LENGTH = 40  # shortest undecodable run treated as a payload
PATH_SEGMENT_MAX = 16  # a run split by "/" into parts all shorter is a path
_B64_RUN = re.compile(rf"[A-Za-z0-9+/]{{{DECODE_MIN_LENGTH},}}={{0,2}}")
_HEX_ONLY = re.compile(r"[0-9a-fA-F]+")
_DECODED_SHELL = re.compile(
    r"\b(bash|sh|zsh|exec|eval|cmd|powershell|pwsh|iex|curl|wget|nc)\b|rm\s+-rf|\bformat\s+[a-z]:",
    re.IGNORECASE,
)

# ── Layer 4: structure ──────────────────────────────────────────────────────
MAX_CHAIN_OPERATORS = 5  # non-PowerShell commands
MAX_CHAIN_OPERATORS_POWERSHELL = 20  # PowerShell pipelines are normal
_POWERSHELL_CMDLET = re.compile(
    r"\b(Get-|Write-|ForEach-Object|Select-Object|Sort-Object|Where-Object|"
    r"New-Item|Test-Path|Remove-Item|Set-Content|Add-Content|Out-File|"
    r"Format-Table|Format-List|Measure-Object)\b",
    re.IGNORECASE,
)
# Known-safe PowerShell pipelines. Matched from the start of the command and
# only when it has no ; or & — re.search let `<safe pipeline>; <anything>` in.
SAFE_POWERSHELL_PIPELINES: tuple[str, ...] = (
    r"Get-ChildItem.*\|.*Select-Object.*\|.*Format-",  # file listing
    r"Get-ChildItem.*\|.*Where-Object.*\|.*Select-",  # filtered search
    r"Get-Content.*\|.*ForEach-Object",  # content processing
    r"Get-ChildItem.*\|.*Select-String",  # grep equivalent
    r"Get-Item.*\|.*Select-Object",  # file stat
)

_COMPILED = {r.id: re.compile(r.pattern, re.IGNORECASE) for r in LAYER1_RULES + LAYER2_RULES}
_SINGLE_QUOTED = re.compile(r"'[^']*'")


def _shannon_entropy(data: str) -> float:
    if not data:
        return 0.0
    n = len(data)
    return -sum(c / n * math.log2(c / n) for c in Counter(data).values())


def _decode_base64_text(run: str) -> str | None:
    """Strictly decode *run*; return the text if it is mostly printable."""
    stripped = run.rstrip("=")
    padded = stripped + "=" * (-len(stripped) % 4)
    try:
        raw = base64.b64decode(padded, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not raw:
        return None
    # PowerShell -EncodedCommand payloads are UTF-16LE: every odd byte is 0.
    if len(raw) >= 4 and raw[1::2].count(0) >= 0.9 * (len(raw) // 2):
        raw = raw[0::2]
    printable = sum(32 <= b < 127 or b in (9, 10, 13) for b in raw)
    if printable / len(raw) < 0.9:
        return None
    return raw.decode("ascii", errors="ignore")


def _is_opaque_blob(run: str) -> bool:
    """A long run that is neither a hex digest, an identifier nor a path."""
    if len(run) < OPAQUE_MIN_LENGTH or _HEX_ONLY.fullmatch(run):
        return False
    if not any(c.isdigit() or c in "+/=" for c in run):
        return False  # CamelCase identifiers, long words
    if "/" in run and max(len(p) for p in run.split("/")) < PATH_SEGMENT_MAX:
        return False  # a path: base64 is rarely cut into short pieces by "/"
    return _shannon_entropy(run) > ENTROPY_THRESHOLD


class CommandSecurityAnalyzer:
    """Multi-layer security analyzer for shell commands.

    Each layer can independently flag a command as dangerous; the first
    DANGEROUS verdict is returned. Rules and thresholds are the module-level
    data above.
    """

    def analyze(self, command: str) -> SecurityAssessment:
        """Perform multi-layer security analysis."""
        for layer in (
            self._layer1_pattern_analysis,
            self._layer2_behavioral_analysis,
            self._layer3_entropy_analysis,
        ):
            assessment = layer(command)
            if assessment.risk_level == CommandRiskLevel.DANGEROUS:
                return assessment
        return self._layer4_semantic_analysis(command)

    @staticmethod
    def _match_rules(command: str, rules: tuple[Rule, ...]) -> SecurityAssessment | None:
        for rule in rules:
            # Inside single quotes a backtick is literal in bash and PowerShell
            # alike; markdown code spans written to a file are not injection.
            text = _SINGLE_QUOTED.sub("''", command) if rule.id == "l1.nested-backtick" else command
            match = _COMPILED[rule.id].search(text)
            if match:
                return SecurityAssessment(
                    risk_level=rule.level,
                    layer_triggered=rule.layer,
                    reason=(
                        f"Dangerous pattern detected: {rule.rationale}"
                        if rule.layer == 1
                        else "Suspicious download-execute pattern detected"
                    ),
                    details={"rule": rule.id, "pattern": rule.pattern, "match": match.group(0)},
                )
        return None

    def _layer1_pattern_analysis(self, command: str) -> SecurityAssessment:
        """Check for known dangerous patterns (Layer 1: Syntax)."""
        return self._match_rules(command, LAYER1_RULES) or SecurityAssessment(
            CommandRiskLevel.SAFE, 1, "No dangerous patterns"
        )

    def _layer2_behavioral_analysis(self, command: str) -> SecurityAssessment:
        """Detect download-execute chains and suspicious token combinations."""
        found = self._match_rules(command, LAYER2_RULES)
        if found:
            return found
        tokens = set(re.findall(r"\b[a-zA-Z][a-zA-Z0-9_-]*\b", command.lower()))
        for indicators, targets, description in LAYER2_COMBINATIONS:
            if tokens & indicators and tokens & targets:
                return SecurityAssessment(
                    risk_level=CommandRiskLevel.DANGEROUS,
                    layer_triggered=2,
                    reason=f"Suspicious behavior: {description}",
                    details={
                        "indicators_found": sorted(tokens & indicators),
                        "targets_found": sorted(tokens & targets),
                    },
                )
        return SecurityAssessment(CommandRiskLevel.SAFE, 2, "No suspicious behavior")

    def _layer3_entropy_analysis(self, command: str) -> SecurityAssessment:
        """Detect base64 that decodes to a shell command, and opaque encoded blobs."""
        for run in _B64_RUN.findall(command):
            decoded = _decode_base64_text(run)
            if decoded is not None and _DECODED_SHELL.search(decoded):
                return SecurityAssessment(
                    risk_level=CommandRiskLevel.DANGEROUS,
                    layer_triggered=3,
                    reason="High-entropy encoded shell command detected",
                    details={"rule": "l3.decodes-to-shell", "decoded_preview": decoded[:100]},
                )
            if _is_opaque_blob(run):
                return SecurityAssessment(
                    risk_level=CommandRiskLevel.DANGEROUS,
                    layer_triggered=3,
                    reason="High-entropy encoded payload detected",
                    details={
                        "rule": "l3.opaque-blob",
                        "entropy": _shannon_entropy(run),
                        "token": run[:50],
                    },
                )
        return SecurityAssessment(CommandRiskLevel.SAFE, 3, "No encoded payloads")

    def _layer4_semantic_analysis(self, command: str) -> SecurityAssessment:
        """Validate command structure."""
        stripped = command.strip()
        if not re.search(r"[;&]", command) and any(
            re.match(p, stripped, re.IGNORECASE) for p in SAFE_POWERSHELL_PIPELINES
        ):
            return SecurityAssessment(CommandRiskLevel.SAFE, 4, "Known-safe PowerShell pattern")

        powershell = bool(_POWERSHELL_CMDLET.search(command) or stripped.startswith("$"))
        limit = MAX_CHAIN_OPERATORS_POWERSHELL if powershell else MAX_CHAIN_OPERATORS
        chain_count = len(re.findall(r"[;|&]", command))
        if chain_count > limit:
            return SecurityAssessment(
                risk_level=CommandRiskLevel.SUSPICIOUS,
                layer_triggered=4,
                reason=f"Complex command chain ({chain_count} operators)",
                details={"chain_length": chain_count},
            )

        urls = re.findall(r'https?://[^\s"\']+', command)
        if urls and any(op in command for op in ["|", "&&", "||"]):
            return SecurityAssessment(
                risk_level=CommandRiskLevel.SUSPICIOUS,
                layer_triggered=4,
                reason="URL with command chaining detected",
                details={"urls_found": urls},
            )

        return SecurityAssessment(CommandRiskLevel.SAFE, 4, "Structure valid")

    def _calculate_entropy(self, data: str) -> float:
        """Shannon entropy of *data* in bits per character (no adjustment)."""
        return _shannon_entropy(data)


# Singleton instance for reuse
_analyzer: CommandSecurityAnalyzer | None = None


def get_security_analyzer() -> CommandSecurityAnalyzer:
    """Get singleton security analyzer instance."""
    global _analyzer
    if _analyzer is None:
        _analyzer = CommandSecurityAnalyzer()
    return _analyzer
