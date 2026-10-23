"""W4.3 (F24, decision 4): a configured Valkey URL fails fast at start-up.

ValkeyEventBus publishes to Valkey channels that nothing reads back, so with
Valkey reachable every in-process subscriber (WebSocket fan-out, journal,
approvals) silently got nothing. Until a bridge exists, DI refuses to build an
event bus when a Valkey URL is set, and the adapter refuses to publish.
"""

from __future__ import annotations

import pytest

from weebot.application.di import Container
from weebot.config.secret_accessor import SecretAccessor
from weebot.infrastructure.event_bus import AsyncEventBus, DurableEventBus


@pytest.mark.parametrize("var", ["WEEBOT_VALKEY_URL", "WEEBOT_REDIS_URL"])
def test_di_refuses_a_valkey_url(monkeypatch, var):
    def _get(name, *a, **k):
        return "valkey://h:6379/0" if name == var else None

    monkeypatch.setattr(SecretAccessor, "get", staticmethod(_get))
    with pytest.raises(RuntimeError, match=var):
        Container()._create_event_bus()


def test_without_a_url_the_bus_is_local_and_durable(monkeypatch):
    monkeypatch.setattr(SecretAccessor, "get", staticmethod(lambda name, *a, **k: None))
    c = Container()
    c.configure_defaults()
    bus = c._create_event_bus()
    assert isinstance(bus, DurableEventBus) and isinstance(bus._inner, AsyncEventBus)
