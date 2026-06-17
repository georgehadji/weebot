"""Skill Security Scanner — detects risky patterns in skill content.

Scans SKILL.md content and any bundled scripts for data exfiltration,
destructive commands, prompt injection markers, and other security risks.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from weebot.domain.models.skill import Skill, TrustTier

logger = logging.getLogger(__name__)

# Patterns that indicate high risk
HIGH_RISK_PATTERNS: list[tuple[str, str, str]] = [
    # Data exfiltration
    ("curl_to_unknown_host", r"curl\s+https?://(?!api\.)(?![a-z]+\.[a-z]{2,})[^\s]*\s", "Data exfiltration via curl to unknown host"),
    ("wget_to_unknown_host", r"wget\s+https?://(?!api\.)(?!raw\.github)[^\s]*\s", "Data exfiltration via wget"),
    ("netcat_exfiltration", r"(?:nc|netcat)\s+-[ev]+", "Potential data exfiltration via netcat"),
    ("scp_external", r"scp\s+.*@", "Unknown SCP destination"),
    # Destructive commands
    ("rm_rf", r"\brm\s+-rf\s+/", "Recursive root deletion"),
    ("dd_destructive", r"\bdd\s+if=/dev/zero\s+of=", "Destructive dd command"),
    ("mkfs", r"\bmkfs\.", "Filesystem creation (destructive)"),
    ("format_drive", r"\bformat\s+[A-Za-z]:\\", "Drive format command"),
    ("shutdown", r"\bshutdown\s+-[rh]?\s*now", "System shutdown"),
    # Secret exfiltration / injection
    ("env_var_dump", r"\bprint(?:env|env)\s*(?:\(|$|\|)", "Environment variable dump"),
    ("secret_in_curl_header", r"curl\s+.*-H\s+['\"](?:Authorization|X-API-Key):", "Secrets in HTTP headers (may be OK if target is trusted)"),
    # Prompt injection markers
    ("ignore_previous", r"ignore\s+(?:all\s+)?(?:previous|above)\s+instructions", "Prompt injection: ignore instructions"),
    ("say_yes", r"say\s+(?:yes|always)\s+to\s+(?:all|every)", "Prompt injection: unconditional compliance"),
    # Unsafe eval
    ("eval_user_input", r"\beval\s*\(\s*input\s*", "Dangerous eval of user input"),
    ("exec_user_input", r"\bexec\s*\(\s*input\s*", "Dangerous exec of user input"),
    ("os_system", r"\bos\.system\s*\(['\"](?:rm|del|format|shutdown)", "Destructive os.system call"),
    # Network to unknown
    ("unknown_webhook", r"webhook\.(?:example|test|local|internal)\.(?:com|net|org)", "Potential test/malicious webhook URL"),
]


class SkillSecurityScanner:
    """Scans skill content for security risks.

    Returns a risk tier and list of findings.
    """

    RISK_TIERS = ("safe", "low", "medium", "high", "critical")

    def __init__(self) -> None:
        self._findings: list[dict[str, Any]] = []

    def scan_skill(self, skill: Skill) -> dict[str, Any]:
        """Scan a skill's content for security risks.

        Args:
            skill: The skill to scan.

        Returns:
            Dict with risk_tier, findings list, and passed boolean.
        """
        self._findings = []
        content = skill.content

        if not content:
            return self._result("safe", [])

        # Check against known patterns
        for pattern_id, pattern, description in HIGH_RISK_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                self._findings.append({
                    "pattern_id": pattern_id,
                    "description": description,
                    "severity": "high",
                    "location": self._find_location(content, pattern),
                })

        # Heuristic: check for bundled scripts with dangerous patterns
        if skill.source_path:
            skill_dir = Path(skill.source_path).parent
            for script_file in skill_dir.rglob("*"):
                if script_file.suffix in (".py", ".sh", ".ps1", ".bat", ".js"):
                    try:
                        script_content = script_file.read_text(encoding="utf-8", errors="ignore")
                        if "rm -rf" in script_content or "os.system" in script_content:
                            self._findings.append({
                                "pattern_id": "dangerous_script",
                                "description": f"Dangerous pattern in bundled script: {script_file.name}",
                                "severity": "high",
                                "location": str(script_file),
                            })
                    except Exception:
                        pass

        # Determine risk tier
        if len(self._findings) >= 3:
            risk_tier = "critical"
        elif len(self._findings) >= 1:
            risk_tier = "high"
        elif self._heuristic_check(content):
            risk_tier = "low"
        else:
            risk_tier = "safe"

        return self._result(risk_tier, self._findings)

    def scan_content(self, content: str) -> dict[str, Any]:
        """Scan raw skill content string for security risks."""
        self._findings = []

        for pattern_id, pattern, description in HIGH_RISK_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                self._findings.append({
                    "pattern_id": pattern_id,
                    "description": description,
                    "severity": "high",
                    "location": "content",
                })

        risk_tier = "critical" if len(self._findings) >= 3 else "high" if self._findings else "safe"
        return self._result(risk_tier, self._findings)

    def _result(self, risk_tier: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
        """Build the result dict."""
        return {
            "risk_tier": risk_tier,
            "findings": findings,
            "passed": risk_tier in ("safe", "low"),
            "blocked": risk_tier in ("high", "critical"),
        }

    def _find_location(self, content: str, pattern: str) -> str:
        """Find the line number where a pattern matches."""
        for i, line in enumerate(content.split("\n"), 1):
            if re.search(pattern, line, re.IGNORECASE):
                return f"line {i}"
        return "unknown"

    @staticmethod
    def _heuristic_check(content: str) -> bool:
        """Heuristic checks for lower-risk concerns."""
        concerns = 0
        if "http://" in content and "localhost" not in content:
            concerns += 1
        if "subprocess" in content:
            concerns += 1
        if "sudo" in content:
            concerns += 1
        if "chmod 777" in content or "chmod 755" in content:
            concerns += 1
        return concerns > 0

    def assess_trust_tier(self, scan_result: dict[str, Any]) -> str:
        """Suggest a trust tier based on scan results.

        Returns:
            "quarantined" if blocked, "candidate" if passed.
        """
        if scan_result["blocked"]:
            return "quarantined"
        return "candidate"
