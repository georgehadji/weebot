"""get_settings(): one cached WeebotSettings per process (ICM fix plan W2.1)."""

from weebot.application.di import Container
from weebot.config.settings import WeebotSettings, get_settings


def test_returns_the_same_instance():
    assert get_settings() is get_settings()


def test_cache_clear_rebuilds_from_the_environment(monkeypatch):
    monkeypatch.setenv("BASH_TIMEOUT", "41")
    first = get_settings()
    assert first.bash_timeout == 41
    monkeypatch.setenv("BASH_TIMEOUT", "42")
    assert get_settings().bash_timeout == 41, "cached until cleared"
    get_settings.cache_clear()
    assert get_settings().bash_timeout == 42


def test_container_resolves_the_accessor_instance():
    container = Container()
    container.configure_defaults()
    assert container.get(WeebotSettings) is get_settings()
