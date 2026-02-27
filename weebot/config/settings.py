"""Configuration and constants for weebot Agent."""
from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Constants
WORKSPACE_ROOT = Path(r"C:\Users\Public\weebot_workspace")
LOGS_DIR = Path("logs")
LOG_FILE = LOGS_DIR / "agent.log"
REQUIRED_PATH_PREFIX = str(WORKSPACE_ROOT)
MAX_RETRIES = 3
CONFIRM_DELETE = True
BROWSER_TIMEOUT = 30000  # ms
HEADLESS = False
MODEL_NAME = "gpt-4"
TEMPERATURE = 0.2
POWERSHELL_PRIORITY_KEYWORDS = [
    "file", "delete", "copy", "move", "directory",
    "process", "kill", "system", "registry", "download"
]


class WeebotSettings(BaseSettings):
    """weebot configuration with validation."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # AI API Keys (at least one required)
    kimi_api_key: str | None = None
    deepseek_api_key: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    # Notifications (optional)
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    slack_webhook_url: str | None = None

    # Budget
    daily_ai_budget: float = 10.0

    @field_validator("daily_ai_budget")
    @classmethod
    def validate_budget(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("daily_ai_budget must be > 0")
        return v

    def validate_at_least_one_key(self) -> None:
        """Raise error if no API keys configured."""
        keys = [self.kimi_api_key, self.deepseek_api_key,
                self.anthropic_api_key, self.openai_api_key]
        if not any(keys):
            raise ValueError(
                "❌ weebot requires at least one AI API key.\n"
                "   Set one of: KIMI_API_KEY, DEEPSEEK_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY\n"
                "   in .env file or as environment variables."
            )

    def available_providers(self) -> list[str]:
        """List available AI providers."""
        providers = []
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
