"""Configuration and constants for weebot Agent."""
import os
from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Constants - Use environment variable or current working directory
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
    "file", "delete", "copy", "move", "directory",
    "process", "kill", "system", "registry", "download"
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
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
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
            init_settings,        # constructor kwargs — highest priority
            dotenv_settings,      # .env file — overrides system environment
            env_settings,         # system environment
            file_secret_settings, # secrets dir
        )

    # AI API Keys (at least one required)
    kimi_api_key: str | None = None
    deepseek_api_key: str | None = None
    xai_api_key: str | None = None          # env: XAI_API_KEY
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    openrouter_api_key: str | None = None   # env: OPENROUTER_API_KEY

    # Web API Auth
    weebot_api_key: str | None = None       # env: WEEBOT_API_KEY

    # Discord (optional)
    discord_public_key: str | None = None      # env: DISCORD_PUBLIC_KEY
    discord_bot_token: str | None = None       # env: DISCORD_BOT_TOKEN
    discord_application_id: str | None = None  # env: DISCORD_APPLICATION_ID

    # Notifications (optional)
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    slack_webhook_url: str | None = None

    # Budget
    daily_ai_budget: float = 10.0

    # SkillHub — remote skill registry index
    skillhub_index_url: str = (
        "https://raw.githubusercontent.com/weebot-community/skillhub/main/index.json"
    )  # env: SKILLHUB_INDEX_URL — JSON index of community-contributed skills

    # awesome-agent-skills — curated GitHub index (heilcheng/awesome-agent-skills)
    awesome_agent_skills_index_url: str = (
        "https://raw.githubusercontent.com/heilcheng/awesome-agent-skills/main/README.md"
    )  # env: AWESOME_AGENT_SKILLS_INDEX_URL

    # Sandbox / code execution
    sandbox_mode: str = "auto"              # env: SANDBOX_MODE — "auto" | "native" | "docker" | "wsl2"
    bash_timeout: int = 30                  # env: BASH_TIMEOUT
    python_timeout: int = 30               # env: PYTHON_TIMEOUT
    sandbox_max_output_bytes: int = 65_536  # env: SANDBOX_MAX_OUTPUT_BYTES (64 KB)
    sandbox_allow_network: bool = False    # env: SANDBOX_ALLOW_NETWORK

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
        allowed = {"auto", "native", "docker", "wsl2"}
        if v.lower() not in allowed:
            raise ValueError(
                f"sandbox_mode must be one of {allowed}, got '{v}'. "
                "Set SANDBOX_MODE to 'auto', 'native', 'docker', or 'wsl2'."
            )
        return v.lower()

    @field_validator("sandbox_max_output_bytes")
    @classmethod
    def validate_max_output(cls, v: int) -> int:
        if v < 1024:
            raise ValueError(
                f"sandbox_max_output_bytes must be >= 1024 bytes (got {v})."
            )
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
    latency_p95_warning_multiplier: float = 1.20   # 20% increase
    latency_p95_critical_multiplier: float = 1.50  # 50% increase
    memory_warning_multiplier: float = 1.30         # 30% increase
    memory_critical_multiplier: float = 1.50         # 50% increase
    
    # Error rate drift thresholds (multipliers of baseline)
    error_rate_warning_multiplier: float = 2.0       # 2x baseline
    error_rate_critical_multiplier: float = 5.0        # 5x baseline
    
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
        default=True,
        description="Allow MCP servers to request sampling/createMessage.",
    )

    # =======================================================================
    # GATEWAY SESSION SETTINGS (Track 2 — Hermes Audit)
    # =======================================================================

    gateway_session_ttl_seconds: int = Field(
        default=7 * 24 * 60 * 60,  # 7 days
        description="TTL for gateway sessions before auto-close.",
    )
    gateway_max_sessions_per_platform: int = Field(
        default=100,
        description="Max active sessions per platform (0 = unlimited).",
    )
    gateway_allowed_platforms: list[str] = Field(
        default_factory=lambda: ["telegram", "discord", "slack"],
        description="List of enabled gateway platforms.",
    )

    # =======================================================================
    # CONTEXT ENGINE SETTINGS (Track 3 — Hermes Audit)
    # =======================================================================

    context_engine: str = Field(
        default="lossy",
        description="Context engine type: 'lossy' (compression), 'none' (pass-through).",
    )
    context_compression_threshold: int = Field(
        default=12000,
        description="Token count threshold that triggers compression.",
    )
    context_compression_target_ratio: float = Field(
        default=0.5,
        description="Target compression ratio (e.g. 0.5 = compress to 50% of threshold).",
    )
    context_compression_protect_last_n: int = Field(
        default=6,
        description="Preserve the last N messages when compressing.",
    )
    prompt_caching_enabled: bool = Field(
        default=False,
        description="Enable Anthropic/OpenRouter prompt caching breakpoints.",
    )
    prompt_caching_ttl_seconds: int = Field(
        default=300,
        description="TTL for cached prompt breakpoints.",
    )

    # =======================================================================
    # CRON AGENT TASK SETTINGS (Track 4 — Hermes Audit)
    # =======================================================================

    cron_agent_jobs_enabled: bool = Field(
        default=False,
        description="Enable cron agent task execution.",
    )
    cron_agent_max_runtime_seconds: int = Field(
        default=300,
        description="Max runtime for a single cron agent job.",
    )
    cron_agent_default_model: str | None = Field(
        default=None,
        description="Default model override for cron agent sessions.",
    )

    # =======================================================================
    # SKILLS HUB SETTINGS (Track 6 — Hermes Audit)
    # =======================================================================

    skills_hub_catalog_url: str | None = Field(
        default=None,
        description="URL for remote skills hub catalog.",
    )
    skill_blueprints_enabled: bool = Field(
        default=False,
        description="Enable skill blueprint auto-suggestion.",
    )

    # =======================================================================
    # SECURITY SETTINGS (Track 5 — Hermes Audit)
    # =======================================================================

    # =======================================================================
    # SCALABILITY SETTINGS (WP-8 — Hermes Audit)
    # =======================================================================

    llm_max_concurrent_requests: int = Field(
        default=12,
        ge=1,
        le=100,
        description="Max concurrent LLM API requests across all sessions.",
    )
    financial_tools_always_ask: bool = Field(
        default=True,
        description="Financial/payment tools always require user approval.",
    )
    secret_redaction_enabled: bool = Field(
        default=True,
        description="Redact secrets (PANs, API keys) in tool output and logs.",
    )
    secret_redaction_entropy_threshold: float = Field(
        default=3.5,
        description="Shannon entropy threshold for secret detection.",
    )

    def validate_at_least_one_key(self) -> None:
        """Raise error if no API keys configured."""
        keys = [self.kimi_api_key, self.deepseek_api_key,
                self.anthropic_api_key, self.openai_api_key,
                self.openrouter_api_key]
        if not any(keys):
            raise ValueError(
                "❌ weebot requires at least one AI API key.\n"
                "   Set one of: KIMI_API_KEY, DEEPSEEK_API_KEY, ANTHROPIC_API_KEY,\n"
                "   OPENROUTER_API_KEY, or OPENAI_API_KEY\n"
                "   in .env file or as environment variables."
            )

    def available_providers(self) -> list[str]:
        """List available AI providers."""
        providers = []
        if self.openrouter_api_key:
            providers.append("openrouter")
        if self.kimi_api_key:
            providers.append("kimi")
        if self.deepseek_api_key:
            providers.append("deepseek")
        if self.anthropic_api_key:
            providers.append("claude")
        if self.openai_api_key:
            providers.append("openai")
        return providers


def ensure_workspace() -> None:
    """Ensure workspace and logs directories exist."""
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(exist_ok=True)
