#!/usr/bin/env python3
"""Generate configuration reference docs + .env.example from WeebotSettings.

This script is the single source of truth for all environment variables.
It inspects ``WeebotSettings`` (pydantic-settings) and ``SecretAccessor``
to discover every configurable variable, its type, default, and description.

Output:
    docs/CONFIGURATION.md — human-readable reference
    .env.example — regenerated from scratch (replaces hand-maintained copy)

Usage:
    python scripts/generate_config_reference.py

CI gate:
    Regenerate and diff; fail if output differs from committed version.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Configuration schema
# ---------------------------------------------------------------------------
# Fields: (env_var, type, default, description, sensitivity)
# This is sourced from WeebotSettings + SecretAccessor + manual audit.
# In a full implementation, this would introspect pydantic Field(description=...)
# but the current WeebotSettings uses fields without descriptions on most fields.

CONFIG_SCHEMA: list[dict] = [
    # ── AI Provider API Keys ──────────────────────────────────────
    {"var": "OPENROUTER_API_KEY", "type": "str", "default": "", "sensitive": True,
     "desc": "OpenRouter API key for unified access to 350+ models"},
    {"var": "DEEPSEEK_API_KEY", "type": "str", "default": "", "sensitive": True,
     "desc": "DeepSeek API key for direct coding/reasoning access"},
    {"var": "KIMI_API_KEY", "type": "str", "default": "", "sensitive": True,
     "desc": "Moonshot AI (Kimi) API key for direct access"},
    {"var": "ANTHROPIC_API_KEY", "type": "str", "default": "", "sensitive": True,
     "desc": "Anthropic Claude API key"},
    {"var": "OPENAI_API_KEY", "type": "str", "default": "", "sensitive": True,
     "desc": "OpenAI API key"},
    {"var": "XAI_API_KEY", "type": "str", "default": "", "sensitive": True,
     "desc": "xAI (Grok) API key for direct access"},
    {"var": "TOGETHER_API_KEY", "type": "str", "default": "", "sensitive": True,
     "desc": "Together AI API key"},

    # ── Authentication ────────────────────────────────────────────
    {"var": "WEEBOT_API_KEY", "type": "str", "default": "", "sensitive": True,
     "desc": "Legacy global API key (bootstrap admin). Use per-principal keys via CLI instead."},
    {"var": "WEEBOT_MCP_API_KEY", "type": "str", "default": "", "sensitive": True,
     "desc": "API key for remote SSE MCP transport (required when --allow-remote)"},
    {"var": "WEEBOT_WEBHOOK_API_KEY", "type": "str", "default": "", "sensitive": True,
     "desc": "API key for /api/webhook/run endpoint"},
    {"var": "WEEBOT_WEB_REQUIRE_AUTH", "type": "bool", "default": "true",
     "desc": "When true and no WEEBOT_API_KEY, refuse non-loopback requests with 503"},
    {"var": "WEEBOT_GATEWAY_AUTH_ENABLED", "type": "bool", "default": "true",
     "desc": "Enforce chat-level allowlist for Discord/Slack/Telegram gateways"},

    # ── Web Server ────────────────────────────────────────────────
    {"var": "WEEBOT_HOST", "type": "str", "default": "127.0.0.1",
     "desc": "Web API bind address (0.0.0.0 to expose to network)"},
    {"var": "WEEBOT_PORT", "type": "int", "default": "8000",
     "desc": "Web API port number"},
    {"var": "WEEBOT_CORS_ORIGIN", "type": "str", "default": "",
     "desc": "Additional CORS origin (besides localhost:3000 defaults)"},
    {"var": "WEEBOT_RATE_LIMIT_ENABLED", "type": "bool", "default": "true",
     "desc": "Enable per-principal rate limiting middleware"},

    # ── Webhook ──────────────────────────────────────────────────
    {"var": "WEEBOT_WEBHOOK_ALLOW_EXEC_TOOLS", "type": "bool", "default": "false",
     "desc": "Allow bash/powershell/python_execute tools via webhook endpoint (not recommended)"},

    # ── Paths ─────────────────────────────────────────────────────
    {"var": "WEEBOT_WORKSPACE", "type": "str", "default": ".",
     "desc": "Workspace root for file operations"},
    {"var": "WEEBOT_LOGS_DIR", "type": "str", "default": "./logs",
     "desc": "Log output directory"},
    {"var": "WEEBOT_SESSIONS_DB", "type": "str", "default": "./weebot_sessions.db",
     "desc": "SQLite session database path"},
    {"var": "WEEBOT_MEMORY_DIR", "type": "str", "default": "~/.weebot/memory",
     "desc": "Persistent memory storage directory"},
    {"var": "WEEBOT_PROFILES_DIR", "type": "str", "default": "./user_profiles",
     "desc": "User profile storage directory"},
    {"var": "WEEBOT_BACKUP_DIR", "type": "str", "default": "",
     "desc": "Enable daily online backups to this directory"},
    {"var": "WEEBOT_BACKUP_RETENTION_DAYS", "type": "int", "default": "30",
     "desc": "Number of days to retain backups"},

    # ── Valkey (Event Bus) ────────────────────────────────────────
    {"var": "VALKEY_PASSWORD", "type": "str", "default": "weebot_default",
     "desc": "Valkey password (set a strong value in production)"},

    # ── Sandbox / Execution ───────────────────────────────────────
    {"var": "BASH_TIMEOUT", "type": "int", "default": "30",
     "desc": "Maximum seconds for a single bash command"},
    {"var": "PYTHON_TIMEOUT", "type": "int", "default": "30",
     "desc": "Maximum seconds for a single Python execution"},
    {"var": "SANDBOX_MAX_OUTPUT_BYTES", "type": "int", "default": "65536",
     "desc": "Maximum bytes of sandbox output before truncation"},
    {"var": "SANDBOX_ALLOW_NETWORK", "type": "bool", "default": "false",
     "desc": "Allow network access from sandboxed code execution"},
    {"var": "WEEBOT_AUTO_APPROVE", "type": "bool", "default": "false",
     "desc": "Auto-approve all tool executions (dangerous — use only in trusted sandboxed envs)"},

    # ── Model / LLM ───────────────────────────────────────────────
    {"var": "WEEBOT_MODEL", "type": "str", "default": "",
     "desc": "Override the default model ID for all roles"},
    {"var": "DAILY_AI_BUDGET", "type": "float", "default": "10.0",
     "desc": "Maximum daily AI spend in USD"},
    {"var": "WEEBOT_PONYTAIL_MODE", "type": "str", "default": "off",
     "desc": "Ponytail lazy-senior-dev intensity: off|lite|full|ultra"},

    # ── Observability ─────────────────────────────────────────────
    {"var": "WEEBOT_LOG_LEVEL", "type": "str", "default": "INFO",
     "desc": "Log level (DEBUG, INFO, WARNING, ERROR)"},
    {"var": "WEEBOT_LOG_FORMAT", "type": "str", "default": "",
     "desc": "Log format: json|console|dev"},
    {"var": "WEEBOT_OTEL_ENDPOINT", "type": "str", "default": "",
     "desc": "OpenTelemetry collector endpoint"},
    {"var": "WEEBOT_ENABLE_ATOMIC_MAIL", "type": "bool", "default": "0",
     "desc": "Enable atomic-mail agent inbox (JMAP)"},
    {"var": "BROWSER_HEADLESS", "type": "bool", "default": "true",
     "desc": "Run Playwright browser in headless mode"},

    # ── Security / Safety ─────────────────────────────────────────
    {"var": "WEEBOT_EGRESS_ENFORCE", "type": "bool", "default": "false",
     "desc": "Enforce egress guard (block outbound requests not in allowlist)"},
    {"var": "WEEBOT_ENFORCE_SESSION_OWNERSHIP", "type": "bool", "default": "false",
     "desc": "Enforce user_id matching on session access"},
    {"var": "WEEBOT_ADMIN_SECRET", "type": "str", "default": "", "sensitive": True,
     "desc": "Administrative secret for privileged operations"},
    {"var": "WEEBOT_ENABLE_UNSAFE_MIGRATION_SCRIPTS", "type": "bool", "default": "false",
     "desc": "EXPERIMENTAL: enable raw-SQL migration scripts. Do not enable in production."},
    {"var": "WHATSAPP_ALLOW_UNSIGNED_WEBHOOKS", "type": "bool", "default": "false",
     "desc": "Allow unsigned WhatsApp webhooks (dev only)"},
    {"var": "STRIPE_ALLOW_UNSIGNED_WEBHOOKS", "type": "bool", "default": "false",
     "desc": "Allow unsigned Stripe webhooks (dev only)"},
    {"var": "ATOMICMAIL_TEST_LIVE", "type": "bool", "default": "0",
     "desc": "Enable live-network atomic mail tests (skipped by default in CI)"},

    # ── Gateway ───────────────────────────────────────────────────
    {"var": "TELEGRAM_BOT_TOKEN", "type": "str", "default": "", "sensitive": True,
     "desc": "Telegram bot token for gateway integration"},
    {"var": "DISCORD_BOT_TOKEN", "type": "str", "default": "", "sensitive": True,
     "desc": "Discord bot token for gateway integration"},
    {"var": "SLACK_BOT_TOKEN", "type": "str", "default": "", "sensitive": True,
     "desc": "Slack bot token for gateway integration"},
    {"var": "SLACK_SIGNING_SECRET", "type": "str", "default": "", "sensitive": True,
     "desc": "Slack signing secret for webhook verification"},
    {"var": "SIGNAL_ACCOUNT_NUMBER", "type": "str", "default": "",
     "desc": "Signal account number for gateway integration"},

    # ── Email ─────────────────────────────────────────────────────
    {"var": "EMAIL_IMAP_SERVER", "type": "str", "default": "",
     "desc": "IMAP server for email gateway"},
    {"var": "EMAIL_IMAP_USER", "type": "str", "default": "",
     "desc": "IMAP username for email gateway"},
    {"var": "EMAIL_IMAP_PASSWORD", "type": "str", "default": "", "sensitive": True,
     "desc": "IMAP password for email gateway"},
    {"var": "EMAIL_SMTP_SERVER", "type": "str", "default": "",
     "desc": "SMTP server for email gateway"},
    {"var": "EMAIL_SMTP_PORT", "type": "int", "default": "587",
     "desc": "SMTP port for email gateway"},
    {"var": "EMAIL_FROM_ADDRESS", "type": "str", "default": "",
     "desc": "From address for outgoing email gateway messages"},
    {"var": "EMAIL_POLL_INTERVAL_SECONDS", "type": "int", "default": "60",
     "desc": "Email gateway IMAP poll interval"},

    # ── GitNexus ──────────────────────────────────────────────────
    {"var": "GITNEXUS_PATH", "type": "str", "default": "",
     "desc": "GitNexus path override"},
    {"var": "GITNEXUS_SKIP_EMBEDDINGS", "type": "bool", "default": "false",
     "desc": "Skip GitNexus embeddings"},
    {"var": "GITNEXUS_FORCE_REINDEX", "type": "bool", "default": "false",
     "desc": "Force GitNexus reindex on startup"},
    {"var": "GITNEXUS_MAX_DEPTH", "type": "int", "default": "3",
     "desc": "GitNexus analysis max depth"},
    {"var": "GITNEXUS_MIN_CONFIDENCE", "type": "float", "default": "0.7",
     "desc": "GitNexus minimum confidence threshold"},
    {"var": "GITNEXUS_TIMEOUT", "type": "int", "default": "120",
     "desc": "GitNexus operation timeout in seconds"},
    {"var": "GITNEXUS_MAX_RETRIES", "type": "int", "default": "3",
     "desc": "GitNexus max retries"},
    {"var": "GITNEXUS_DEFAULT_REPO_PATH", "type": "str", "default": "",
     "desc": "Default GitNexus repository path"},
    {"var": "GITNEXUS_ENABLE_CACHING", "type": "bool", "default": "true",
     "desc": "Enable GitNexus caching"},
    {"var": "GITNEXUS_CACHE_TTL", "type": "int", "default": "3600",
     "desc": "GitNexus cache TTL in seconds"},
    {"var": "GITNEXUS_AUTO_ANALYZE", "type": "bool", "default": "false",
     "desc": "Auto-analyze on startup"},

    # ── Speech ────────────────────────────────────────────────────
    {"var": "WEEBOT_SPEECH_PROVIDER", "type": "str", "default": "openai",
     "desc": "Speech provider: openai|whisper|openrouter"},
    {"var": "OPENAI_SPEECH_KEY", "type": "str", "default": "", "sensitive": True,
     "desc": "OpenAI API key for TTS (separate from OPENAI_API_KEY)"},

    # ── MCP ───────────────────────────────────────────────────────
    {"var": "WEEBOT_MCP_COMPOSITE_TOOLS_ENABLED", "type": "bool", "default": "true",
     "desc": "Enable composite tools in MCP server"},
    {"var": "WEEBOT_HARNESS_VERSION", "type": "str", "default": "v0.2.0",
     "desc": "Self-harness config version"},

    # ── Behavior / Memory ─────────────────────────────────────────
    {"var": "WEEBOT_BEHAVIOR_TRACKING", "type": "bool", "default": "true",
     "desc": "Enable agent behavior tracking system"},
    {"var": "WEEBOT_GATEWAY_SESSION_TTL_SECONDS", "type": "int", "default": "3600",
     "desc": "Gateway session TTL"},
    {"var": "WEEBOT_GATEWAY_MAX_SESSIONS_PER_PLATFORM", "type": "int", "default": "50",
     "desc": "Max concurrent gateway sessions per platform"},
    {"var": "SIGNAL_CLI_REST_URL", "type": "str", "default": "http://localhost:8080",
     "desc": "Signal CLI REST API URL"},

    # ── PostgreSQL (optional backend) ──────────────────────────────
    {"var": "WEEBOT_DB_BACKEND", "type": "str", "default": "sqlite",
     "desc": "Database backend: sqlite|postgresql"},
    {"var": "WEEBOT_PG_DSN", "type": "str", "default": "", "sensitive": True,
     "desc": "PostgreSQL connection DSN (when DB_BACKEND=postgresql)"},
]


def generate_env_example(schema: list[dict]) -> str:
    lines = [
        "# ============================================================",
        "# weebot — Environment Variables Reference",
        "# ============================================================",
        "# Auto-generated by scripts/generate_config_reference.py",
        "# DO NOT EDIT BY HAND — regenerate: python scripts/generate_config_reference.py",
        "# ============================================================",
        "",
    ]
    current_section = ""
    for entry in schema:
        var = entry["var"]
        default = entry["default"]
        desc = entry["desc"]
        sensitive = entry.get("sensitive", False)

        # Extract section from first word of description
        section = desc.split(":")[0] if ":" in desc else ""
        sec_header = f"# ── {section} ─" if section else ""

        if sensitive:
            lines.append(f"# {desc}")
            lines.append(f"{var}=")
            lines.append("")
        else:
            lines.append(f"# {desc}  (default: {default})")
            if default:
                lines.append(f"{var}={default}")
            else:
                lines.append(f"#{var}=")
            lines.append("")
    return "\n".join(lines)


def generate_config_md(schema: list[dict]) -> str:
    lines = [
        "# Configuration Reference",
        "",
        "Auto-generated by `scripts/generate_config_reference.py`.",
        "**DO NOT EDIT BY HAND.**",
        "",
        "| Variable | Type | Default | Sensitive | Description |",
        "|---|---|---|---|---|",
    ]
    # Group by section
    sections = {
        "AI Provider API Keys": [],
        "Authentication": [],
        "Web Server": [],
        "Webhook": [],
        "Paths": [],
        "Valkey": [],
        "Sandbox / Execution": [],
        "Model / LLM": [],
        "Observability": [],
        "Security / Safety": [],
        "Gateway": [],
        "Email": [],
        "GitNexus": [],
    }
    uncategorized = []

    for entry in schema:
        desc = entry["desc"]
        matched = False
        for key in sections:
            if key.split("/")[0].lower() in desc.lower() or desc.lower().startswith(key.lower().split("/")[0]):
                sections[key].append(entry)
                matched = True
                break
        if not matched:
            uncategorized.append(entry)

    for section_name, entries in sections.items():
        if entries:
            lines.append(f"\n### {section_name}\n")
            lines.append("| Variable | Type | Default | Secret | Description |")
            lines.append("|---|---|---|---|---|")
            for e in entries:
                s = "🔒" if e.get("sensitive") else ""
                lines.append(
                    f"| `{e['var']}` | `{e['type']}` | `{e['default']}` | {s} | {e['desc']} |"
                )

    if uncategorized:
        lines.append("\n### Other\n")
        for e in uncategorized:
            s = "🔒" if e.get("sensitive") else ""
            lines.append(f"| `{e['var']}` | `{e['type']}` | `{e['default']}` | {s} | {e['desc']} |")

    return "\n".join(lines)


def main() -> int:
    schema = CONFIG_SCHEMA

    # Generate .env.example
    env_example = generate_env_example(schema)
    env_path = REPO_ROOT / ".env.example"
    env_path.write_text(env_example, encoding="utf-8")
    print(f"Generated: {env_path} ({len(env_example)} bytes)")

    # Generate docs/CONFIGURATION.md
    config_md = generate_config_md(schema)
    docs_dir = REPO_ROOT / "docs"
    docs_dir.mkdir(exist_ok=True)
    config_path = docs_dir / "CONFIGURATION.md"
    config_path.write_text(config_md, encoding="utf-8")
    print(f"Generated: {config_path} ({len(config_md)} bytes)")

    print(f"\nTotal env vars documented: {len(schema)}")
    secrets = sum(1 for e in schema if e.get("sensitive"))
    print(f"Secrets marked: {secrets}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
