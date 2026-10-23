"""Tests never read a settings class's .env file (tests/conftest.py `_no_dotenv_settings`).

The Stripe dev opt-in test is the real-world check, but it only bites on a machine
whose .env sets STRIPE_ALLOW_UNSIGNED_WEBHOOKS. This one bites everywhere.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


def _settings_class(env_file):
    class _Probe(BaseSettings):
        model_config = SettingsConfigDict(env_file=str(env_file))
        probe_value: str = "default"

    return _Probe


def test_a_settings_class_ignores_its_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("PROBE_VALUE=from_file\n")
    probe = _settings_class(env_file)
    assert probe().probe_value == "default"
    monkeypatch.setenv("PROBE_VALUE", "from_env")
    assert probe().probe_value == "from_env"


def test_an_explicit_env_file_is_still_read(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("PROBE_VALUE=from_file\n")
    assert _settings_class(env_file)(_env_file=str(env_file)).probe_value == "from_file"
