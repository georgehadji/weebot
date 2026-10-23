"""The DI-built session persistence adapter does not retry permanent errors.

The adapter's own default skips retries for errors that fail the same way every
time. The container built a second config without `retryable`, so production
retried a malformed session three times before dead-lettering it.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from weebot.application.di import Container
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.infrastructure.persistence.session_persistence_adapter import _is_transient


def test_the_container_adapter_uses_the_permanent_error_filter():
    c = Container()
    c.register(StateRepositoryPort, MagicMock())
    adapter = c._create_session_persistence_adapter()
    assert adapter._retry._config.retryable is _is_transient
