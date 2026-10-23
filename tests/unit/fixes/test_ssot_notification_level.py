"""One NotificationLevel (SSOT audit row 19).

The port defined it with `auto()` values and a DEBUG member; the infrastructure
notifier defined its own with string values and no DEBUG, so a level from one
was never equal to the same-named level from the other.
"""

from __future__ import annotations

from weebot.application.ports import notification_port
from weebot.infrastructure.notifications import notifications


def test_the_notifier_uses_the_port_enum():
    assert notifications.NotificationLevel is notification_port.NotificationLevel


def test_levels_serialise_as_lower_case_names():
    assert notification_port.NotificationLevel.ERROR.value == "error"
    assert notification_port.NotificationLevel.DEBUG.value == "debug"
