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
# For a variable that is a WeebotSettings field, the field's default wins over
# the "default" written here (``resolved_schema``): five of these had drifted
# from the code. Every variable listed must have a reader
# (tests/unit/scripts/test_generate_config_reference.py).

CONFIG_SCHEMA: list[dict] = [
    # ── AI Provider API Keys ──────────────────────────────────────
    {"var": "OPENROUTER_API_KEY", "type": "str", "default": "", "sensitive": True,
     "desc": "OpenRouter API key for unified access to 350+ models"},
    {"var": "OPENROUTER_MIN_CREDIT_USD", "type": "float", "default": "0.10",
     "desc": "OpenRouter balance (USD) below which the cascade skips OpenRouter-only models"},
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
    {"var": "OLLAMA_ENABLED", "type": "bool", "default": "false",
     "desc": "Use a local Ollama model for the roles in OLLAMA_ROLES (see docs/OLLAMA.md)"},
    {"var": "OLLAMA_BASE_URL", "type": "str", "default": "http://localhost:11434/v1",
     "desc": "Ollama's OpenAI-compatible endpoint"},
    {"var": "OLLAMA_MODEL", "type": "str", "default": "qwen3:8b",
     "desc": "Model tag from `ollama list`"},
    {"var": "OLLAMA_CONTEXT_WINDOW", "type": "int", "default": "4096",
     "desc": "Context the model really has (num_ctx); Ollama's /v1 ignores a per-request value"},
    {"var": "OLLAMA_ROLES", "type": "str", "default": "summarizer,documentation",
     "desc": "Roles that try an Ollama model first: `role` or `role=tag` (e.g. verifier=gemma4:31b-cloud)"},

    # ── Authentication ────────────────────────────────────────────
    {"var": "WEEBOT_API_KEY", "type": "str", "default": "", "sensitive": True,
     "desc": "Legacy global API key (bootstrap admin). Use per-principal keys via CLI instead."},
    {"var": "WEEBOT_MCP_API_KEY", "type": "str", "default": "", "sensitive": True,
     "desc": "API key for remote SSE MCP transport (required when --allow-remote)"},
    {"var": "WEEBOT_WEBHOOK_API_KEY", "type": "str", "default": "", "sensitive": True,
     "desc": "API key for /api/webhook/run endpoint"},
    {"var": "WEEBOT_WEB_REQUIRE_AUTH", "type": "bool",
     "desc": "When true and no WEEBOT_API_KEY, refuse non-loopback requests with 503"},
    {"var": "WEEBOT_GATEWAY_AUTH_ENABLED", "type": "bool",
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
    {"var": "WEEBOT_WEBHOOK_ALLOW_EXEC_TOOLS", "type": "bool",
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

    # ── Valkey (Event Bus) ────────────────────────────────────────
    {"var": "VALKEY_PASSWORD", "type": "str", "default": "weebot_default",
     "desc": "Valkey password. The default is for local docker compose only: the Valkey service publishes no port (pinned by tests/unit/test_compose_valkey_unpublished.py). Set your own value before publishing it"},

    # ── Session cost budget (plan 2.4, D6) ────────────────────────
    {"var": "WEEBOT_SESSION_COST_SOFT_USD", "type": "float", "default": "0.50",
     "desc": "Per-session spend (USD) above which the cascade skips PREMIUM models for the rest of the session; 0 disables"},
    {"var": "WEEBOT_SESSION_COST_HARD_USD", "type": "float", "default": "2.50",
     "desc": "Per-session spend (USD) at which the flow asks to continue, then ends as BUDGET_EXCEEDED if refused; 0 disables"},

    # ── Sandbox / Execution ───────────────────────────────────────
    {"var": "BASH_TIMEOUT", "type": "int",
     "desc": "Maximum seconds for a single bash command"},
    {"var": "PYTHON_TIMEOUT", "type": "int",
     "desc": "Maximum seconds for a single Python execution"},
    {"var": "SANDBOX_MAX_OUTPUT_BYTES", "type": "int",
     "desc": "Maximum bytes of sandbox output before truncation"},
    {"var": "SANDBOX_ALLOW_NETWORK", "type": "bool",
     "desc": "Allow network access from sandboxed code execution"},
    {"var": "SANDBOX_MODE", "type": "str",
     "desc": "auto (native on Windows, Docker elsewhere), docker_first, native, docker, wsl2"},
    {"var": "SANDBOX_REQUIRE_ISOLATION", "type": "bool",
     "desc": "Refuse sandboxed calls on a backend that cannot enforce network-off (ADR-014)"},
    {"var": "WEEBOT_AUTO_APPROVE", "type": "str", "default": "",
     "desc": "Set to 1 to auto-approve CLI tool approvals (dangerous — trusted sandboxed envs only); any other value asks"},
    {"var": "WEEBOT_SHELL_GUARD_MODE", "type": "str",
     "desc": "Tool guard chain mode: 'observe' (record only) or 'enforce' (refuse)"},
    {"var": "FINANCIAL_TOOLS_ALWAYS_ASK", "type": "bool",
     "desc": "Financial/payment tools always ask before running (observe mode logs only)"},
    {"var": "WEEBOT_FINANCIAL_TOOL_PATTERNS", "type": "str",
     "default": "*stripe*,*payment*,*invoice*,*refund*,*payout*,*checkout*,*billing*",
     "desc": "Comma-separated globs (case-insensitive) naming financial/payment tools"},
    {"var": "WEEBOT_OUTBOUND_TOOL_PATTERNS", "type": "str",
     "default": "*schedulepost*,*deletepost*,*publish*,*send_email*,*send_mail*,"
                "*send_reply*,*send_message*,*tweet*,*generate*,*clipping*",
     "desc": "Comma-separated globs naming tools that publish, send or spend; they always ask"},
    {"var": "WEEBOT_OUTBOUND_ASK_IN_OBSERVE", "type": "bool",
     "desc": "Outbound tools ask through the approval channel even in observe mode"},
    {"var": "AGENT_REACH_PATH", "type": "str", "default": "",
     "desc": "Path to agent-reach.exe for the agent_reach tool (else PATH, else ~/.agent-reach-venv)"},
    {"var": "MOLI_PATH", "type": "str", "default": "",
     "desc": "Path to moli.exe for the moli_fetch tool (else PATH, else %LOCALAPPDATA%\\Moli\\bin)"},
    {"var": "CAMOFOX_PATH", "type": "str", "default": "",
     "desc": "camofox-browser package folder for camofox_browser (else ~/.camofox-browser)"},
    {"var": "REMOTION_HOST", "type": "str", "default": "",
     "desc": "Folder with Remotion installed, for remotion_video (else ~/.weebot-remotion)"},
    {"var": "WEEBOT_INTENT_REVIEW_TIMEOUT_S", "type": "float",
     "desc": "Seconds the pre-planning intent review may take; on timeout it fails open"},

    # ── Model / LLM ───────────────────────────────────────────────
    {"var": "DAILY_AI_BUDGET", "type": "float",
     "desc": "Maximum daily AI spend in USD"},
    {"var": "WEEBOT_PONYTAIL_MODE", "type": "str",
     "desc": "Ponytail lazy-senior-dev intensity: off|lite|full|ultra"},

    # ── Observability ─────────────────────────────────────────────
    {"var": "WEEBOT_LOG_LEVEL", "type": "str", "default": "INFO",
     "desc": "Log level (DEBUG, INFO, WARNING, ERROR)"},
    {"var": "WEEBOT_LOG_FORMAT", "type": "str", "default": "",
     "desc": "Log format: json|console|dev"},
    {"var": "WEEBOT_ENABLE_ATOMIC_MAIL", "type": "bool", "default": "0",
     "desc": "Enable atomic-mail agent inbox (JMAP)"},
    {"var": "BROWSER_HEADLESS", "type": "bool", "default": "true",
     "desc": "Run Playwright browser in headless mode"},

    # ── Security / Safety ─────────────────────────────────────────
    # Defaults must match the code (egress_guard.py, web/auth.py): both default
    # on. These said "false", so every regeneration shipped a weaker template.
    {"var": "WEEBOT_EGRESS_ENFORCE", "type": "bool", "default": "true",
     "desc": "Enforce egress guard (block outbound requests not in allowlist)"},
    {"var": "WEEBOT_ENFORCE_SESSION_OWNERSHIP", "type": "bool", "default": "true",
     "desc": "Enforce user_id matching on session access"},
    {"var": "WEEBOT_SHELL_DEFAULT_ASK", "type": "str", "default": "observe",
     "desc": "Shell commands no approval rule covers: off, observe (log what would ask) or enforce"},
    {"var": "WEEBOT_BEHIND_PROXY", "type": "bool", "default": "false",
     "desc": "The UI proxy fronts this API: loopback no longer counts as identity for mutations, "
             "so they need an API key"},
    {"var": "WEEBOT_MAX_BODY_BYTES", "type": "int", "default": "1048576",
     "desc": "Largest request body the web API accepts (413 above it)"},
    {"var": "WHATSAPP_ALLOW_UNSIGNED_WEBHOOKS", "type": "bool",
     "desc": "Allow unsigned WhatsApp webhooks (dev only)"},
    {"var": "STRIPE_ALLOW_UNSIGNED_WEBHOOKS", "type": "bool",
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
    {"var": "SIGNAL_ACCOUNT_NUMBER", "type": "str",
     "desc": "Signal account number for gateway integration"},

    # ── Email ─────────────────────────────────────────────────────
    {"var": "EMAIL_IMAP_SERVER", "type": "str",
     "desc": "IMAP server for email gateway"},
    {"var": "EMAIL_IMAP_USER", "type": "str",
     "desc": "IMAP username for email gateway"},
    {"var": "EMAIL_IMAP_PASSWORD", "type": "str", "default": "", "sensitive": True,
     "desc": "IMAP password for email gateway"},
    {"var": "EMAIL_SMTP_SERVER", "type": "str",
     "desc": "SMTP server for email gateway"},
    {"var": "EMAIL_SMTP_PORT", "type": "int",
     "desc": "SMTP port for email gateway"},
    {"var": "EMAIL_FROM_ADDRESS", "type": "str",
     "desc": "From address for outgoing email gateway messages"},
    {"var": "EMAIL_POLL_INTERVAL_SECONDS", "type": "int",
     "desc": "Email gateway IMAP poll interval"},

    # ── MCP ───────────────────────────────────────────────────────
    {"var": "WEEBOT_MCP_COMPOSITE_TOOLS_ENABLED", "type": "bool",
     "desc": "Enable composite tools in MCP server"},
    {"var": "WEEBOT_HARNESS_VERSION", "type": "str", "default": "v0.2.0",
     "desc": "Self-harness config version"},

    # ── Behavior / Memory ─────────────────────────────────────────
    {"var": "WEEBOT_BEHAVIOR_TRACKING", "type": "bool", "default": "true",
     "desc": "Enable agent behavior tracking system"},
    {"var": "WEEBOT_GATEWAY_SESSION_TTL_SECONDS", "type": "int",
     "desc": "Gateway session TTL"},
    {"var": "WEEBOT_GATEWAY_MAX_SESSIONS_PER_PLATFORM", "type": "int",
     "desc": "Max concurrent gateway sessions per platform"},
    {"var": "SIGNAL_CLI_REST_URL", "type": "str",
     "desc": "Signal CLI REST API URL"},

    # ── Optional features, off by default (D4) ────────────────────
    {"var": "WEEBOT_STEP_EVALUATOR", "type": "bool", "default": "false",
     "desc": "Score each step's progress on the verifier model; a stalled step is replanned"},
    {"var": "WEEBOT_SKILL_PROMOTION_GATE", "type": "bool", "default": "false",
     "desc": "Chain-of-verification veto before a learned skill is promoted to trusted"},
    {"var": "WEEBOT_STAGED_VALIDATION", "type": "bool", "default": "false",
     "desc": "SkillOpt validates a candidate on a 10-task probe first and stops if it scores low"},
    {"var": "WEEBOT_SCORING_MODE", "type": "str", "default": "plan_outcome",
     "desc": "Scorer for sessions with an expected answer: plan_outcome|exact|execution|verifier"},
    {"var": "WEEBOT_EPISODIC_SUMMARIES", "type": "bool", "default": "false",
     "desc": "Save summaries of successful runs and show them when planning similar tasks"},
    {"var": "WEEBOT_FLOW_CHECKPOINTS", "type": "bool", "default": "false",
     "desc": "Save the plan after each step so `flow recover` can resume an interrupted run"},
    {"var": "WEEBOT_STRATEGY_TRANSFER", "type": "bool", "default": "false",
     "desc": "Offer approaches that worked on other kinds of task when planning"},
    {"var": "WEEBOT_EVENT_BUS", "type": "str", "default": "local",
     "desc": "Event bus: local, or valkey to share events between processes (WEEBOT_VALKEY_URL)"},
    {"var": "WEEBOT_WINDOWS_TOAST", "type": "bool", "default": "false",
     "desc": "Windows desktop toasts for errors, questions and finished runs (web backend)"},
    {"var": "WEEBOT_SPEECH_BACKEND", "type": "str", "default": "whisper",
     "desc": "Voice tools backend: whisper (local extras) or openrouter (billed, audio leaves)"},

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


def settings_env_names() -> dict[str, str]:
    """Env-var name -> WeebotSettings field name, aliases included."""
    sys.path.insert(0, str(REPO_ROOT))
    from weebot.config.settings import WeebotSettings

    names: dict[str, str] = {}
    for field_name, info in WeebotSettings.model_fields.items():
        names[field_name.upper()] = field_name
        for alias in (info.alias, info.validation_alias):
            if alias is not None:
                for name in re.findall(r"[A-Z][A-Z0-9_]+", str(alias)):
                    names[name] = field_name
    return names


def _format_default(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(v) for v in value)
    return str(value)


def resolved_schema() -> list[dict]:
    """CONFIG_SCHEMA with every settings-backed default read from the settings field."""
    from weebot.config.settings import WeebotSettings

    fields = settings_env_names()
    resolved = []
    for entry in CONFIG_SCHEMA:
        field_name = fields.get(entry["var"])
        if field_name is not None and not entry.get("sensitive"):
            info = WeebotSettings.model_fields[field_name]
            default = info.default_factory() if info.default_factory else info.default
            entry = {**entry, "default": _format_default(default)}
        resolved.append(entry)
    return resolved


def main() -> int:
    schema = resolved_schema()

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
