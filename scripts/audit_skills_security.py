"""Security audit for downloaded awesome-agent-skills SKILL.md files.

Scans for:
  1. Prompt injection / system prompt override attempts
  2. Credential harvesting (API keys, tokens, env vars exfiltration)
  3. Data exfiltration (sending data to external URLs/webhooks)
  4. Unsafe shell commands (rm -rf, chmod 777, curl|bash, etc.)
  5. Sensitive file access (.env, .ssh, /etc/passwd, etc.)
  6. Social engineering / deception instructions
  7. Hidden payloads (base64, zero-width chars, encoded commands)
  8. Privilege escalation (sudo, admin, registry edits)
  9. Network listeners / reverse shells
  10. Cryptocurrency / wallet address patterns
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ── Skills to audit ──────────────────────────────────────────────
AWESOME_SKILLS = [
    "docx", "doc-coauthoring", "pptx", "xlsx", "pdf", "algorithmic-art",
    "canvas-design", "frontend-design", "slack-gif-creator", "theme-factory",
    "web-artifacts-builder", "mcp-builder", "webapp-testing", "brand-guidelines",
    "internal-comms", "skill-creator", "template", "agents-sdk", "wrangler",
    "durable-objects", "web-perf", "agents-md", "code-review", "find-bugs",
    "composio", "remotion", "create-voltagent", "voltagent-best-practices",
    "voltagent-core-reference", "voltagent-docs-bundle", "frontend-dev",
    "minimax-pdf", "hf-cli", "react-best-practices", "web-design-guidelines",
    "react-native-skills", "neon-postgres", "claimable-postgres",
    "neon-postgres-egress-optimizer", "clickhouse-best-practices",
    "react-native-best-practices", "github", "upgrading-react-native",
    "typefully", "resend", "react-email", "email-best-practices", "ai-seo",
    "copywriting", "epic-hypothesis", "opportunity-solution-tree",
    "prd-development", "roadmap-planning", "taste-skill", "data-structure-protocol",
]


@dataclass
class Finding:
    skill: str
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW, INFO
    category: str
    description: str
    evidence: str
    line_num: int = 0


@dataclass
class AuditReport:
    findings: list[Finding] = field(default_factory=list)
    skills_scanned: int = 0
    clean_skills: list[str] = field(default_factory=list)


# ── Pattern definitions ──────────────────────────────────────────

PATTERNS: list[tuple[str, str, str, re.Pattern]] = []

def p(severity: str, category: str, desc: str, pattern: str, flags: int = re.IGNORECASE):
    PATTERNS.append((severity, category, desc, re.compile(pattern, flags)))

# 1. Prompt injection / override
p("CRITICAL", "PROMPT_INJECTION", "System prompt override attempt",
  r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|rules)")
p("CRITICAL", "PROMPT_INJECTION", "Role hijacking attempt",
  r"you\s+are\s+now\s+(a|an)\s+(unrestricted|unfiltered|jailbroken|DAN)")
p("HIGH", "PROMPT_INJECTION", "Instruction boundary break",
  r"</?system>|</?user>|</?assistant>|<<SYS>>|<<\/SYS>>")
p("HIGH", "PROMPT_INJECTION", "Override safety guardrails",
  r"(bypass|disable|ignore|override)\s+(safety|guardrails?|restrictions?|filters?|moderation)")
p("MEDIUM", "PROMPT_INJECTION", "Hidden instructions marker",
  r"(BEGIN|START)\s+(HIDDEN|SECRET|PRIVATE)\s+(INSTRUCTIONS?|PROMPT|SECTION)")

# 2. Credential harvesting
p("CRITICAL", "CREDENTIAL_HARVEST", "Exfiltrate API keys via curl/wget",
  r"(curl|wget|fetch|http)\s+.*\b(api[_-]?key|token|secret|password|credential)")
p("CRITICAL", "CREDENTIAL_HARVEST", "Read and send environment variables",
  r"(echo|print|cat|send|post|upload)\s+.*\$\{?(API_KEY|SECRET|TOKEN|PASSWORD|OPENAI|ANTHROPIC|AWS_)")
p("HIGH", "CREDENTIAL_HARVEST", "Access .env file",
  r"(cat|type|read|open|load)\s+\.env\b")
p("HIGH", "CREDENTIAL_HARVEST", "Access SSH keys",
  r"(cat|type|read|open)\s+.*[/\\]\.ssh[/\\]")
p("HIGH", "CREDENTIAL_HARVEST", "Access credentials file",
  r"(cat|type|read|open)\s+.*[/\\](\.aws|\.npmrc|\.pypirc|\.netrc|\.gitconfig)")

# 3. Data exfiltration
p("CRITICAL", "DATA_EXFIL", "Send data to webhook/external endpoint",
  r"(curl|wget|fetch|axios|requests)\s+.*-X?\s*(POST|PUT)\s+https?://")
p("HIGH", "DATA_EXFIL", "Pipe output to external URL",
  r"\|\s*(curl|wget|nc|ncat)\s+")
p("HIGH", "DATA_EXFIL", "Base64 encode and send",
  r"base64\s+.*\|\s*(curl|wget|nc)")
p("MEDIUM", "DATA_EXFIL", "Suspicious webhook URL pattern",
  r"https?://[^\s]*?(webhook|callback|exfil|receive|collect|ngrok|pipedream|requestbin)")

# 4. Unsafe shell commands
p("CRITICAL", "UNSAFE_CMD", "Recursive force delete",
  r"rm\s+-r?f\s+(/|\~|%|\.\.)")
p("CRITICAL", "UNSAFE_CMD", "Pipe curl to shell execution",
  r"curl\s+.*\|\s*(bash|sh|zsh|python|perl|ruby|node)")
p("CRITICAL", "UNSAFE_CMD", "Format disk / filesystem destruction",
  r"(mkfs|format|diskpart|dd\s+if=)")
p("HIGH", "UNSAFE_CMD", "Chmod world-writable",
  r"chmod\s+(777|666|a\+rwx)")
p("HIGH", "UNSAFE_CMD", "Kill system processes",
  r"(kill|taskkill)\s+.*(-9|/F)\s+.*(-1|PID\s*0)")
p("MEDIUM", "UNSAFE_CMD", "Download and execute pattern",
  r"(wget|curl)\s+.*&&\s*(chmod\s+\+x|bash|sh|python)")

# 5. Sensitive file access
p("HIGH", "SENSITIVE_FILE", "Access /etc/passwd or /etc/shadow",
  r"(cat|read|open)\s+.*/etc/(passwd|shadow|sudoers)")
p("HIGH", "SENSITIVE_FILE", "Access Windows registry",
  r"(reg\s+(add|delete|query)|regedit)")
p("MEDIUM", "SENSITIVE_FILE", "Access browser data / cookies",
  r"(chrome|firefox|safari|edge).*\b(cookies|passwords|login\s+data)")

# 6. Social engineering
p("HIGH", "SOCIAL_ENGINEERING", "Instruct to hide actions from user",
  r"(do\s+not|don't|never)\s+(show|tell|reveal|disclose|mention)\s+(the\s+)?(user|human)")
p("HIGH", "SOCIAL_ENGINEERING", "Pretend to be a different entity",
  r"(pretend|act\s+as\s+if|impersonate|masquerade)\s+(you\s+are|to\s+be)")
p("MEDIUM", "SOCIAL_ENGINEERING", "Urgency pressure tactics",
  r"(immediately|urgently|without\s+delay)\s+(send|upload|transmit|share)")

# 7. Hidden payloads
p("CRITICAL", "HIDDEN_PAYLOAD", "Base64 encoded executable command",
  r"(echo|printf)\s+['\"]?[A-Za-z0-9+/]{40,}={0,2}['\"]?\s*\|\s*(base64\s+-d|decode)")
p("HIGH", "HIDDEN_PAYLOAD", "Hex-encoded command execution",
  r"\\x[0-9a-fA-F]{2}.*\\x[0-9a-fA-F]{2}.*\\x[0-9a-fA-F]{2}")
p("MEDIUM", "HIDDEN_PAYLOAD", "Eval/exec of dynamic string",
  r"(eval|exec)\s*\(\s*(decode|decompress|inflate)")

# 8. Privilege escalation
p("HIGH", "PRIV_ESCALATION", "Sudo without password",
  r"sudo\s+(-n|--non-interactive|NOPASSWD)")
p("MEDIUM", "PRIV_ESCALATION", "Run as administrator",
  r"(runas\s+/user:administrator|Start-Process.*-Verb\s+RunAs)")

# 9. Network listeners / reverse shells
p("CRITICAL", "REVERSE_SHELL", "Reverse shell pattern",
  r"(bash\s+-i|/dev/tcp/|nc\s+-[elp]|ncat\s+--exec|python\s+-c\s+.*socket.*connect)")
p("HIGH", "NETWORK_LISTENER", "Start a network listener",
  r"(nc\s+-l|ncat\s+-l|python\s+-m\s+http\.server|SimpleHTTPServer)")

# 10. Cryptocurrency
p("MEDIUM", "CRYPTO", "Cryptocurrency wallet address",
  r"\b(0x[a-fA-F0-9]{40}|[13][a-km-zA-HJ-NP-Z1-9]{25,34}|bc1[a-zA-HJ-NP-Z0-9]{39,59})\b")
p("MEDIUM", "CRYPTO", "Mining script reference",
  r"(coinhive|crypto-?loot|coin-?hive|mineralt|coinimp)")

# 11. Overly broad file operations
p("MEDIUM", "FILE_OPS", "Wildcard delete pattern",
  r"(rm|del|Remove-Item)\s+.*\*\.\*")
p("MEDIUM", "FILE_OPS", "Read all files recursively",
  r"find\s+/\s+-name\s+\*")


def audit_skill(skill_name: str, content: str) -> list[Finding]:
    """Scan one skill's content against all patterns."""
    findings: list[Finding] = []
    lines = content.split("\n")
    for line_num, line in enumerate(lines, 1):
        for severity, category, desc, regex in PATTERNS:
            if regex.search(line):
                evidence = line.strip()[:120]
                findings.append(Finding(
                    skill=skill_name,
                    severity=severity,
                    category=category,
                    description=desc,
                    evidence=evidence,
                    line_num=line_num,
                ))
    # Check for zero-width characters (hidden text)
    zwc = re.findall(r"[\u200b\u200c\u200d\u2060\ufeff]", content)
    if len(zwc) > 3:
        findings.append(Finding(
            skill=skill_name,
            severity="HIGH",
            category="HIDDEN_PAYLOAD",
            description=f"Contains {len(zwc)} zero-width characters (possible hidden instructions)",
            evidence=f"{len(zwc)} zero-width chars found across content",
        ))
    return findings


def main():
    base = Path.home() / ".weebot" / "skills"
    report = AuditReport()

    for name in sorted(AWESOME_SKILLS):
        skill_md = base / name / "SKILL.md"
        if not skill_md.exists():
            continue
        report.skills_scanned += 1
        content = skill_md.read_text(encoding="utf-8", errors="replace")
        findings = audit_skill(name, content)
        if findings:
            report.findings.extend(findings)
        else:
            report.clean_skills.append(name)

    # Print report
    print("=" * 70)
    print("  SECURITY AUDIT REPORT — awesome-agent-skills downloads")
    print("=" * 70)
    print(f"\n  Skills scanned: {report.skills_scanned}")
    print(f"  Clean skills:   {len(report.clean_skills)}")
    print(f"  Total findings: {len(report.findings)}")

    if report.findings:
        # Group by severity
        by_sev: dict[str, list[Finding]] = {}
        for f in report.findings:
            by_sev.setdefault(f.severity, []).append(f)

        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
            if sev not in by_sev:
                continue
            items = by_sev[sev]
            print(f"\n{'=' * 70}")
            print(f"  [{sev}] — {len(items)} finding(s)")
            print(f"{'=' * 70}")
            for f in items:
                print(f"\n  Skill:    {f.skill}")
                print(f"  Category: {f.category}")
                print(f"  Issue:    {f.description}")
                if f.line_num:
                    print(f"  Line:     {f.line_num}")
                print(f"  Evidence: {f.evidence}")
    else:
        print("\n  *** ALL SKILLS CLEAN — no security issues found ***")

    if report.clean_skills:
        print(f"\n{'=' * 70}")
        print(f"  CLEAN SKILLS ({len(report.clean_skills)}/{report.skills_scanned})")
        print(f"{'=' * 70}")
        for name in report.clean_skills:
            print(f"  [OK] {name}")

    print()


if __name__ == "__main__":
    main()
