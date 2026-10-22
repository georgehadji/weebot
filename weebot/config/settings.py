"""Configuration and constants for weebot Agent."""

import os
from functools import lru_cache
from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Constants - Use environment variable or current working directory.
# These are read with os.getenv once, at import, and are deliberately NOT
# WeebotSettings fields: tools use WORKSPACE_ROOT in class bodies
# (powershell_tool.py) and at module level, so a settings-backed shim would
# validate the whole .env at import. Entry points must load_dotenv() before
# importing weebot (run.py, cli/main.py, run_mcp.py). ICM fix plan W2.4b, option
# (a); passing the workspace to tools through ToolConfig is planned for Wave 5.
WORKSPACE_ROOT = Path(os.getenv("WEEBOT_WORKSPACE", os.getcwd()))
LOGS_DIR = Path(os.getenv("WEEBOT_LOGS_DIR", "logs"))
LOG_FILE = LOGS_DIR / "agent.log"
SESSIONS_DB = os.getenv("WEEBOT_SESSIONS_DB", "./weebot_sessions.db")
MEMORY_DIR = Path(os.getenv("WEEBOT_MEMORY_DIR", str(Path.home() / ".weebot" / "memory")))
PROFILES_DIR = Path(os.getenv("WEEBOT_PROFILES_DIR", "./user_profiles"))
REQUIRED_PATH_PREFIX = str(WORKSPACE_ROOT)
MAX_RETRIES = 3
CONFIRM_DELETE = True
BROWSER_TIMEOUT = 30000  # ms
HEADLESS = False
MODEL_NAME = "x-ai/grok-build-0.1"  # kept for legacy compat; see model_refs.MODEL_DI_DEFAULT
TEMPERATURE = 0.2
POWERSHELL_PRIORITY_KEYWORDS = [
    "file",
    "delete",
    "copy",
    "move",
    "directory",
    "process",
    "kill",
    "system",
    "registry",
    "download",
]


class WeebotSettings(BaseSettings):
    """weebot configuration with validation.

    Source priority: .env file > system environment > defaults.
    This ensures the .env file (committed config) takes precedence
    over potentially stale system environment variables.
    """

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,  # allow both alias and field name for env vars
    )

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        """Order sources so explicit constructor kwargs always win, then
        .env overrides system environment (the documented intent).

        Init kwargs must rank highest: silently overriding an explicitly
        passed value with a stale .env/env var violates least astonishment
        and breaks explicit construction (e.g. tests, programmatic config).
        Among the ambient sources, .env still takes precedence over system
        environment as originally intended.
        """
        return (
            init_settings,  # constructor kwargs — highest priority
            dotenv_settings,  # .env file — overrides system environment
            env_settings,  # system environment
            file_secret_settings,  # secrets dir
        )

    # AI API Keys (at least one required)
    kimi_api_key: str | None = None
    deepseek_api_key: str | None = None
    xai_api_key: str | None = None  # env: XAI_API_KEY
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    openrouter_api_key: str | None = None  # env: OPENROUTER_API_KEY

    # Reasoner API Settings
    reasoner_api_url: str = "http://localhost:8003"  # env: REASONER_API_URL
    reasoner_api_key: str | None = None  # env: REASONER_API_KEY
    reasoner_dir: str | None = None  # env: REASONER_DIR

    # Berb Research API Settings
    berb_api_url: str = "http://localhost:8004"  # env: BERB_API_URL
    berb_api_key: str | None = None  # env: BERB_API_KEY
    berb_dir: str | None = None  # env: BERB_DIR

    # Scraper (Spacescraper) API Settings
    scraper_api_url: str = "http://localhost:8000"  # env: SCRAPER_API_URL
    scraper_api_key: str | None = None  # env: SCRAPER_API_KEY
    scraper_dir: str | None = None  # env: SCRAPER_DIR

    # Web API Auth
    weebot_api_key: str | None = None  # env: WEEBOT_API_KEY
    web_require_auth: bool = Field(
        default=True,
        description="When True and no weebot_api_key is set, refuse non-loopback requests.",
    )
    web_host: str = Field(
        default="127.0.0.1", description="Web API bind address (default loopback for security)."
    )
    webhook_api_key: str | None = Field(
        default=None, description="Independent API key for the /api/webhook/run endpoint."
    )
    webhook_allow_exec_tools: bool = Field(
        default=False,
        description="When True, webhook endpoint may use exec tools (bash, powershell, python_execute).",
    )

    # Discord (optional)
    discord_public_key: str | None = None  # env: DISCORD_PUBLIC_KEY
    discord_bot_token: str | None = None  # env: DISCORD_BOT_TOKEN
    discord_application_id: str | None = None  # env: DISCORD_APPLICATION_ID

    # Notifications (optional)
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    slack_webhook_url: str | None = None

    # Slack gateway (Events API) — required to run weebot from Slack.
    # Distinct from slack_webhook_url above (outbound notifications only).
    slack_bot_token: str | None = None  # env: SLACK_BOT_TOKEN
    slack_signing_secret: str | None = None  # env: SLACK_SIGNING_SECRET

    # WhatsApp gateway (Business Cloud API)
    whatsapp_business_api_token: str | None = None  # env: WHATSAPP_BUSINESS_API_TOKEN
    whatsapp_business_phone_number_id: str | None = None  # env: WHATSAPP_BUSINESS_PHONE_NUMBER_ID
    whatsapp_webhook_verify_token: str | None = None  # env: WHATSAPP_WEBHOOK_VERIFY_TOKEN
    whatsapp_app_secret: str | None = (
        None  # env: WHATSAPP_APP_SECRET (optional, enables signature verification)
    )
    whatsapp_allow_unsigned_webhooks: bool = Field(
        default=False, description="Allow unsigned WhatsApp webhooks (dev only)."
    )

    # Stripe webhook
    stripe_webhook_secret: str | None = None  # env: STRIPE_WEBHOOK_SECRET
    stripe_allow_unsigned_webhooks: bool = Field(
        default=False, description="Allow unsigned Stripe webhooks (dev only)."
    )

    # Signal gateway (signal-cli REST API — requires a local signal-cli instance)
    signal_cli_rest_url: str = "http://localhost:8080"  # env: SIGNAL_CLI_REST_URL
    signal_account_number: str | None = None  # env: SIGNAL_ACCOUNT_NUMBER

    # Email gateway (IMAP polling + SMTP send)
    email_imap_server: str = "imap.gmail.com"  # env: EMAIL_IMAP_SERVER
    email_imap_user: str | None = None  # env: EMAIL_IMAP_USER
    email_imap_password: str | None = None  # env: EMAIL_IMAP_PASSWORD
    email_smtp_server: str = "smtp.gmail.com"  # env: EMAIL_SMTP_SERVER
    email_smtp_port: int = 587  # env: EMAIL_SMTP_PORT
    email_from_address: str | None = None  # env: EMAIL_FROM_ADDRESS
    email_poll_interval_seconds: float = 30.0  # env: EMAIL_POLL_INTERVAL_SECONDS

    # Budget
    daily_ai_budget: float = 10.0

    # SkillHub — remote skill registry index
    skillhub_index_url: str = (
        "https://raw.githubusercontent.com/weebot-community/skillhub/main/index.json"  # env: SKILLHUB_INDEX_URL — JSON index of community-contributed skills
    )

    # awesome-agent-skills — curated GitHub index (heilcheng/awesome-agent-skills)
    awesome_agent_skills_index_url: str = (
        "https://raw.githubusercontent.com/heilcheng/awesome-agent-skills/main/README.md"  # env: AWESOME_AGENT_SKILLS_INDEX_URL
    )

    # Sandbox / code execution
    # env: SANDBOX_MODE — "auto"|"docker_first"|"native"|"docker"|"wsl2".
    # auto: native on Windows, Docker elsewhere. docker_first (ADR-014): Docker
    # when ready and weebot-tool-env is built, else the platform default.
    sandbox_mode: str = "auto"
    # env: SANDBOX_REQUIRE_ISOLATION — refuse sandboxed calls on a backend that
    # cannot enforce network-off, instead of warning (ADR-014). Off by default.
    sandbox_require_isolation: bool = False
    bash_timeout: int = 30  # env: BASH_TIMEOUT
    python_timeout: int = 30  # env: PYTHON_TIMEOUT
    sandbox_max_output_bytes: int = 65_536  # env: SANDBOX_MAX_OUTPUT_BYTES (64 KB)
    sandbox_allow_network: bool = False  # env: SANDBOX_ALLOW_NETWORK

    # Tool guard chain (application/services/tool_guards.py). "observe" only
    # records what the chain would decide; "enforce" refuses DENY and ASK.
    # ICM fix plan W3.1; the flip to enforce is W3.7, after observe data.
    shell_guard_mode: str = Field(
        default="observe",
        alias="WEEBOT_SHELL_GUARD_MODE",
        description="Tool guard chain mode: 'observe' (record only) or 'enforce' (refuse).",
    )
    intent_review_timeout_s: float = Field(
        default=30.0,
        gt=0,
        alias="WEEBOT_INTENT_REVIEW_TIMEOUT_S",
        description="Seconds the pre-planning intent review may take; on timeout it fails open.",
    )

    @field_validator("shell_guard_mode")
    @classmethod
    def validate_shell_guard_mode(cls, v: str) -> str:
        normalized = str(v).strip().lower()
        if normalized not in {"observe", "enforce"}:
            raise ValueError(f"shell_guard_mode must be 'observe' or 'enforce', got {v!r}")
        return normalized

    @field_validator("daily_ai_budget")
    @classmethod
    def validate_budget(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("daily_ai_budget must be > 0")
        return v

    @field_validator("bash_timeout", "python_timeout")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(
                f"Timeout must be > 0 seconds (got {v}). "
                "Set BASH_TIMEOUT and PYTHON_TIMEOUT to a positive integer."
            )
        return v

    @field_validator("sandbox_mode")
    @classmethod
    def validate_sandbox_mode(cls, v: str) -> str:
        allowed = {"auto", "docker_first", "native", "docker", "wsl2"}
        if v.lower() not in allowed:
            raise ValueError(
                f"sandbox_mode must be one of {allowed}, got '{v}'. "
                "Set SANDBOX_MODE to 'auto', 'docker_first', 'native', 'docker', or 'wsl2'."
            )
        return v.lower()

    @field_validator("sandbox_max_output_bytes")
    @classmethod
    def validate_max_output(cls, v: int) -> int:
        if v < 1024:
            raise ValueError(f"sandbox_max_output_bytes must be >= 1024 bytes (got {v}).")
        return v

    # ========================================================================
    # DRIFT MONITORING SETTINGS (v2.4.0+)
    # ========================================================================

    # Enable/disable drift monitoring
    drift_monitoring_enabled: bool = True

    # Baseline window for comparison
    drift_baseline_window_days: int = 7

    # Detection check interval
    drift_detection_interval_minutes: int = 5

    # Performance drift thresholds (multipliers of baseline)
    latency_p95_warning_multiplier: float = 1.20  # 20% increase
    latency_p95_critical_multiplier: float = 1.50  # 50% increase
    memory_warning_multiplier: float = 1.30  # 30% increase
    memory_critical_multiplier: float = 1.50  # 50% increase

    # Error rate drift thresholds (multipliers of baseline)
    error_rate_warning_multiplier: float = 2.0  # 2x baseline
    error_rate_critical_multiplier: float = 5.0  # 5x baseline

    # Data distribution drift thresholds (KL divergence)
    kl_divergence_warning: float = 0.5
    kl_divergence_critical: float = 1.0

    # Cooldown periods (minutes)
    alert_cooldown_minutes: int = 15
    performance_alert_cooldown_minutes: int = 30
    data_drift_cooldown_minutes: int = 60

    # Minimum samples for reliable detection
    drift_min_samples: int = 1000

    # =======================================================================
    # HTTP CLIENT SETTINGS (v2.6.0+)
    # =======================================================================

    # Default timeouts for HTTP requests
    http_timeout_default: float = 30.0
    http_timeout_connect: float = 10.0
    http_timeout_read: float = 60.0

    # Connection pooling
    http_max_connections: int = 20
    http_max_keepalive: int = 10
    http_keepalive: bool = True

    # Retry settings
    http_max_retries: int = 3
    http_retry_backoff: float = 1.0

    # =======================================================================
    # MCP CLIENT SETTINGS (Track 1 — Hermes Audit)
    # =======================================================================

    # MCP servers are configured via mcp_servers dict (loaded from YAML/JSON).
    # Each key is a server name, value is MCPServerConfig-compatible dict.
    mcp_servers_config_path: str | None = Field(
        default=None,
        description="Path to MCP servers config file (YAML/JSON). If None, no servers.",
    )
    mcp_token_dir: str = Field(
        default=".weebot/mcp-tokens",
        description="Directory for OAuth token cache (relative to workspace root or absolute).",
    )
    mcp_sampling_enabled: bool = Field(
        default=True, description="Allow MCP servers to request sampling/createMessage."
    )
    mcp_scoped_aggregation: bool = Field(
        default=True,
        description="Enable per-request scoped retrieval of MCP-bridged external tools.",
    )
    mcp_scope_native_tools: bool = Field(
        default=False,
        description="When True, also scope native tools per query so total tools stay <= 12.",
    )
    mcp_composite_tools_enabled: bool = Field(
        default=True,
        description=(
            "Expose composite workflow tools and hide covered atomic tools " "on the MCP surface."
        ),
    )

    # =======================================================================
    # PONYTAIL MODE (lazy senior dev coding persona)
    # =======================================================================

    ponytail_mode: str = Field(
        default="off", description="Ponytail lazy-senior-dev intensity: off | lite | full | ultra"
    )

    @field_validator("ponytail_mode")
    @classmethod
    def validate_ponytail_mode(cls, v: str) -> str:
        allowed = {"off", "lite", "full", "ultra"}
        normalized = str(v).strip().lower()
        if normalized not in allowed:
            raise ValueError(f"ponytail_mode must be one of {sorted(allowed)}, got {v!r}")
        return normalized

    # =======================================================================
    # GATEWAY SESSION SETTINGS (Track 2 — Hermes Audit)
    # =======================================================================

    gateway_session_ttl_seconds: int = Field(
        default=7 * 24 * 60 * 60,  # 7 days
        description="TTL for gateway sessions before auto-close.",
    )
    gateway_max_sessions_per_platform: int = Field(
        default=100, description="Max active sessions per platform (0 = unlimited)."
    )
    gateway_allowed_platforms: list[str] = Field(
        default_factory=lambda: ["telegram", "discord", "slack"],
        description="List of enabled gateway platforms.",
    )
    gateway_auth_enabled: bool = Field(
        default=True,
        description=(
            "Enforce the gateway allowlist (see `python -m cli.main gateway "
            "allowlist`) for inbound Slack/Telegram/Discord messages. Chats "
            "must be allowlisted before the bot will respond to them."
        ),
    )

    # =======================================================================
    # CONTEXT ENGINE SETTINGS (Track 3 — Hermes Audit)
    # =======================================================================

    context_engine: str = Field(
        default="lossy",
        description="Context engine type: 'lossy' (compression), 'none' (pass-through).",
    )
    context_compression_threshold: int = Field(
        default=12000, description="Token count threshold that triggers compression."
    )
    context_compression_target_ratio: float = Field(
        default=0.5,
        description="Target compression ratio (e.g. 0.5 = compress to 50% of threshold).",
    )
    context_compression_protect_last_n: int = Field(
        default=6, description="Preserve the last N messages when compressing."
    )
    prompt_caching_enabled: bool = Field(
        default=False, description="Enable Anthropic/OpenRouter prompt caching breakpoints."
    )
    prompt_caching_ttl_seconds: int = Field(
        default=300, description="TTL for cached prompt breakpoints."
    )

    # =======================================================================
    # CRON AGENT TASK SETTINGS (Track 4 — Hermes Audit)
    # =======================================================================

    cron_agent_jobs_enabled: bool = Field(
        default=False, description="Enable cron agent task execution."
    )
    cron_agent_max_runtime_seconds: int = Field(
        default=300, description="Max runtime for a single cron agent job."
    )
    cron_agent_default_model: str | None = Field(
        default=None, description="Default model override for cron agent sessions."
    )

    # Feature flags (migrated from os.getenv — see Phase 3c)
    # Supported env var names: WEEBOT_PLAN_REVIEW_ENABLED (legacy) or
    # PLAN_REVIEW_ENABLED (current).  populate_by_name=True in model_config
    # ensures both are accepted.
    plan_review_enabled: bool = Field(
        default=True,
        alias="WEEBOT_PLAN_REVIEW_ENABLED",
        description="Enable plan-review pause before execution.",
    )
    cove_enabled: bool = Field(
        default=True, alias="WEEBOT_COVE_ENABLED", description="Enable Chain-of-Verification step."
    )
    cove_max_questions: int = Field(
        default=3,
        alias="WEEBOT_COVE_QUESTIONS",
        description="Max verification questions in CoVE step.",
    )

    # =======================================================================
    # SKILLS HUB SETTINGS (Track 6 — Hermes Audit)
    # =======================================================================

    skills_hub_catalog_url: str | None = Field(
        default=None, description="URL for remote skills hub catalog."
    )
    skill_blueprints_enabled: bool = Field(
        default=False, description="Enable skill blueprint auto-suggestion."
    )

    # =======================================================================
    # SECURITY SETTINGS (Track 5 — Hermes Audit)
    # =======================================================================

    # =======================================================================
    # SCALABILITY SETTINGS (WP-8 — Hermes Audit)
    # =======================================================================

    llm_max_concurrent_requests: int = Field(
        default=12, ge=1, le=100, description="Max concurrent LLM API requests across all sessions."
    )
    llm_pool_acquire_timeout_s: float = Field(
        default=300.0,
        gt=0,
        description=(
            "Seconds a model call may queue for an LLM concurrency slot before it is "
            "refused with LLMCapacityExhaustedError. Queue time does not count "
            "against the model's own timeout."
        ),
    )
    max_concurrent_flows: int = Field(
        default=8,
        ge=1,
        le=200,
        description=(
            "Max agent flows running at once in one process. Further sessions wait "
            "for a slot before their flow is built. Default is a starting value, "
            "not a measured one -- tune it against real load."
        ),
    )
    financial_tools_always_ask: bool = Field(
        default=True, description="Financial/payment tools always require user approval."
    )
    financial_tool_patterns: str = Field(
        default="*stripe*,*payment*,*invoice*,*refund*,*payout*,*checkout*,*billing*",
        alias="WEEBOT_FINANCIAL_TOOL_PATTERNS",
        description="Comma-separated globs (case-insensitive) naming financial/payment tools.",
    )
    outbound_tool_patterns: str = Field(
        default=(
            "*schedulepost*,*deletepost*,*publish*,*send_email*,*send_mail*,*send_reply*,"
            "*send_message*,*tweet*,*generate*,*clipping*"
        ),
        alias="WEEBOT_OUTBOUND_TOOL_PATTERNS",
        description=(
            "Comma-separated globs (case-insensitive) naming tools that publish, send or "
            "spend (MCP tools are namespaced mcp__<server>__<tool>). They always ask."
        ),
    )
    outbound_ask_in_observe: bool = Field(
        default=True,
        alias="WEEBOT_OUTBOUND_ASK_IN_OBSERVE",
        description="Outbound tools ask through the approval channel even in observe mode.",
    )
    secret_redaction_enabled: bool = Field(
        default=True, description="Redact secrets (PANs, API keys) in tool output and logs."
    )
    secret_redaction_entropy_threshold: float = Field(
        default=3.5, description="Shannon entropy threshold for secret detection."
    )

    def validate_at_least_one_key(self) -> None:
        """Raise error if no API keys configured."""
        if not self.available_providers():
            env_names = ", ".join(field.upper() for field in _PROVIDER_KEYS.values())
            raise ValueError(
                "❌ weebot requires at least one AI API key.\n"
                f"   Set one of: {env_names}\n"
                "   in .env file or as environment variables."
            )

    def available_providers(self) -> list[str]:
        """List available AI providers."""
        return [name for name, field in _PROVIDER_KEYS.items() if getattr(self, field)]


# Provider name -> WeebotSettings key field. One table for the key check and
# the provider list, so a provider cannot be counted by one and not the other.
_PROVIDER_KEYS: dict[str, str] = {
    "openrouter": "openrouter_api_key",
    "kimi": "kimi_api_key",
    "deepseek": "deepseek_api_key",
    "claude": "anthropic_api_key",
    "openai": "openai_api_key",
    "xai": "xai_api_key",
}


@lru_cache(maxsize=1)
def get_settings() -> WeebotSettings:
    """The process-wide WeebotSettings, built (and .env read) once.

    Production code calls this instead of ``WeebotSettings()``; the count of
    direct constructions is ratcheted by ``scripts/lint_settings_construction.py``.
    A changed ``.env`` takes effect on restart. Tests reset it with
    ``get_settings.cache_clear()`` (autouse fixture in ``tests/conftest.py``).
    """
    return WeebotSettings()


def ensure_workspace() -> None:
    """Ensure workspace and logs directories exist."""
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(exist_ok=True)


# OSWorldSettings moved to weebot/config/osworld_settings.py (ICM fix plan W2.4).
