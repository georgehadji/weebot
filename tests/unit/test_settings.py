"""Unit tests for WeebotSettings configuration validation."""
import pytest
from pydantic import ValidationError


class TestWeebotSettingsValidation:
    def test_raises_when_no_keys_configured(self, monkeypatch):
        # Explicitly clear all API keys to simulate no configuration
        for var in ("KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        
        # Mock env file loading by setting env_file to non-existent path
        from weebot.config import settings as settings_module
        original_config = settings_module.WeebotSettings.model_config
        settings_module.WeebotSettings.model_config = original_config.copy()
        settings_module.WeebotSettings.model_config['env_file'] = '/nonexistent/.env'
        
        try:
            from weebot.config.settings import WeebotSettings
            settings = WeebotSettings()
            with pytest.raises(ValueError, match="at least one AI API key"):
                settings.validate_at_least_one_key()
        finally:
            # Restore original config
            settings_module.WeebotSettings.model_config = original_config

    def test_passes_with_openai_key(self, with_openai_key):
        from weebot.config.settings import WeebotSettings
        settings = WeebotSettings()
        settings.validate_at_least_one_key()  # should not raise

    def test_passes_with_anthropic_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        from weebot.config.settings import WeebotSettings
        settings = WeebotSettings()
        settings.validate_at_least_one_key()

    def test_passes_with_kimi_key(self, monkeypatch):
        monkeypatch.setenv("KIMI_API_KEY", "kimi-test")
        from weebot.config.settings import WeebotSettings
        settings = WeebotSettings()
        settings.validate_at_least_one_key()

    def test_passes_with_deepseek_key(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
        from weebot.config.settings import WeebotSettings
        settings = WeebotSettings()
        settings.validate_at_least_one_key()


class TestWeebotSettingsProviders:
    def test_providers_match_configured_keys(self, with_openai_key):
        """Test that available providers match the configured API keys."""
        from weebot.config.settings import WeebotSettings
        settings = WeebotSettings()
        providers = settings.available_providers()
        # With OPENAI_API_KEY set, should have openai provider
        assert "openai" in providers

    def test_openai_provider_listed(self, with_openai_key):
        from weebot.config.settings import WeebotSettings
        settings = WeebotSettings()
        assert "openai" in settings.available_providers()

    def test_claude_provider_listed(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        from weebot.config.settings import WeebotSettings
        settings = WeebotSettings()
        assert "claude" in settings.available_providers()

    def test_all_providers_listed(self, with_all_keys):
        from weebot.config.settings import WeebotSettings
        settings = WeebotSettings()
        providers = settings.available_providers()
        assert set(providers) == {"kimi", "deepseek", "claude", "openai"}

    def test_provider_count_matches_keys_set(self, with_all_keys):
        from weebot.config.settings import WeebotSettings
        settings = WeebotSettings()
        assert len(settings.available_providers()) == 4


class TestWeebotSettingsBudget:
    def test_default_budget_is_ten(self, with_openai_key):
        from weebot.config.settings import WeebotSettings
        settings = WeebotSettings()
        assert settings.daily_ai_budget == 10.0

    def test_budget_validation_rejects_zero(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("DAILY_AI_BUDGET", "0")
        from weebot.config.settings import WeebotSettings
        with pytest.raises(ValidationError):
            WeebotSettings()

    def test_budget_validation_rejects_negative(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("DAILY_AI_BUDGET", "-5")
        from weebot.config.settings import WeebotSettings
        with pytest.raises(ValidationError):
            WeebotSettings()