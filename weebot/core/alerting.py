#!/usr/bin/env python3
"""alerting.py - Runtime Alerting System

Provides native runtime alerting capabilities as an alternative to external
AlertManager rules defined in docs/alerting_rules.yaml.

Features:
- Alert creation and management
- Multiple severity levels (info, warning, error, critical)
- Alert handlers for different notification channels
- Alert deduplication and grouping
- Automatic alert resolution

Usage:
    from weebot.core.alerting import Alert, AlertManager, AlertSeverity

    # Create alert
    alert = Alert(
        name="high_error_rate",
        severity=AlertSeverity.ERROR,
        message="Error rate exceeded threshold",
        labels={"service": "weebot", "env": "production"}
    )

    # Register with manager
    manager = AlertManager()
    manager.fire_alert(alert)
"""

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any
from collections.abc import Awaitable, Callable
from collections import defaultdict
from functools import partial

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertState(Enum):
    """Alert lifecycle states."""

    FIRING = "firing"
    RESOLVED = "resolved"
    PENDING = "pending"


@dataclass
class Alert:
    """
    Represents a single alert instance.

    Attributes:
        name: Unique identifier for the alert type
        severity: Alert severity level
        message: Human-readable description
        labels: Key-value pairs for categorization
        annotations: Additional metadata for dashboards
        starts_at: When the alert started (default: now)
        ends_at: When the alert ends (None = ongoing)
        generator_url: Link to the source
    """

    name: str
    severity: AlertSeverity
    message: str
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)
    starts_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    ends_at: datetime | None = None
    generator_url: str | None = None
    state: AlertState = AlertState.FIRING

    def to_dict(self) -> dict[str, Any]:
        """Convert alert to dictionary format (Prometheus-compatible)."""
        return {
            "labels": {"alertname": self.name, "severity": self.severity.value, **self.labels},
            "annotations": self.annotations,
            "startsAt": self.starts_at.isoformat(),
            "endsAt": self.ends_at.isoformat() if self.ends_at else "",
            "generatorURL": self.generator_url or "",
            "state": self.state.value,
        }

    def resolve(self) -> None:
        """Mark alert as resolved."""
        self.state = AlertState.RESOLVED
        self.ends_at = datetime.now(UTC)


# Type alias for alert handlers.
#
# `asyncio.coroutine` was deprecated in 3.8 and REMOVED in 3.11, and this is a
# module-level statement -- so importing this module raised AttributeError on
# every supported interpreter, and the whole alerting subsystem could not load.
# Nothing caught it: ruff's CI selector reads it as an ordinary attribute
# access, not an undefined name, and no test imported the module. An alerting
# system that cannot be imported is the failure this audit keeps finding, in
# the component whose job is to report failures.
AlertHandler = Callable[[Alert], None]
AsyncAlertHandler = Callable[[Alert], Awaitable[None]]


class AlertManager:
    """
    Central alert management system.

    Handles alert lifecycle, deduplication, and dispatch to handlers.
    Thread-safe for concurrent access.
    """

    def __init__(self) -> None:
        self._alerts: dict[str, Alert] = {}
        self._handlers: list[AlertHandler] = []
        self._async_handlers: list[AsyncAlertHandler] = []
        self._lock = threading.RLock()
        self._grouping: dict[str, list[Alert]] = defaultdict(list)
        self._group_by: list[str] = ["name", "severity"]
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Record the loop that async handlers should run on.

        Alerts are fired from wherever the failure happened -- a worker thread,
        a watchdog observer, a plain synchronous script. None of those has a
        running loop, and an async handler needs one. Binding it once, from the
        thread that owns it, is what lets `_dispatch` hand work across safely
        instead of demanding that every caller already be on the loop.
        """
        self._loop = loop or asyncio.get_running_loop()

    def register_handler(self, handler: AlertHandler) -> None:
        """Register a synchronous alert handler."""
        with self._lock:
            self._handlers.append(handler)

    def register_async_handler(self, handler: AsyncAlertHandler) -> None:
        """Register an asynchronous alert handler."""
        with self._lock:
            self._async_handlers.append(handler)

    def set_group_by(self, labels: list[str]) -> None:
        """Configure how alerts are grouped."""
        with self._lock:
            self._group_by = labels

    def _get_group_key(self, alert: Alert) -> str:
        """Generate grouping key for an alert."""
        values = []
        for label in self._group_by:
            if label == "name":
                values.append(alert.name)
            elif label == "severity":
                values.append(alert.severity.value)
            else:
                values.append(alert.labels.get(label, ""))
        return ":".join(values)

    def fire_alert(self, alert: Alert) -> None:
        """
        Fire a new alert or update existing one.

        If an alert with the same name already exists, it will be
        updated (deduplication by name).
        """
        with self._lock:
            # Check for existing alert with same name
            existing = self._alerts.get(alert.name)
            if existing and existing.state == AlertState.FIRING:
                # Update existing alert, don't create duplicate
                logger.debug(
                    "Alert %s already firing, updating instead of creating new", alert.name
                )
                existing.message = alert.message
                existing.annotations = alert.annotations
                existing.labels = {**existing.labels, **alert.labels}
            else:
                # New alert
                self._alerts[alert.name] = alert
                group_key = self._get_group_key(alert)
                self._grouping[group_key].append(alert)

                logger.info(
                    "Alert fired: name=%s severity=%s message=%s",
                    alert.name,
                    alert.severity.value,
                    alert.message,
                )

            # Dispatch to handlers
            self._dispatch(alert)

    def resolve_alert(self, name: str, message: str | None = None) -> bool:
        """
        Resolve an alert by name.

        Args:
            name: Name of the alert to resolve
            message: Optional resolution message

        Returns:
            True if alert was found and resolved, False otherwise
        """
        with self._lock:
            alert = self._alerts.get(name)
            if not alert:
                return False

            alert.resolve()
            if message:
                alert.annotations["resolved_message"] = message

            logger.info("Alert resolved: name=%s", name)

            # Dispatch to handlers
            self._dispatch(alert)
            return True

    def get_alert(self, name: str) -> Alert | None:
        """Get alert by name."""
        with self._lock:
            return self._alerts.get(name)

    def get_firing_alerts(self) -> list[Alert]:
        """Get all currently firing alerts."""
        with self._lock:
            return [a for a in self._alerts.values() if a.state == AlertState.FIRING]

    def get_alerts_by_severity(self, severity: AlertSeverity) -> list[Alert]:
        """Get all firing alerts of a specific severity."""
        with self._lock:
            return [
                a
                for a in self._alerts.values()
                if a.state == AlertState.FIRING and a.severity == severity
            ]

    def _dispatch(self, alert: Alert) -> None:
        """Dispatch alert to all registered handlers."""
        # Synchronous handlers
        for handler in self._handlers:
            try:
                handler(alert)
            except Exception as e:
                logger.error("Alert handler failed: handler=%s error=%s", handler.__name__, str(e))

        # Asynchronous handlers.
        #
        # This used to open with `loop = asyncio.get_event_loop()` -- a variable
        # it never read. That call raises RuntimeError in any thread without a
        # running loop, so firing an alert from a worker thread raised out of
        # `fire_alert`, while holding the lock, after the synchronous handlers
        # had already run. A partial dispatch and an exception, from a dead
        # assignment, in a class whose docstring promises thread safety.
        # `ensure_future` was the other half: not thread-safe, and the task it
        # returned was dropped, so a failing handler was never heard from.
        if not self._async_handlers:
            return

        try:
            running: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        target = running or self._loop

        if target is None or target.is_closed():
            # Say so. An async handler that cannot run is a notification that
            # will not be delivered, and silence here is the failure mode this
            # whole class exists to prevent.
            logger.error(
                "Alert '%s' fired but %d async handler(s) could not run: no event "
                "loop is available on this thread and none is bound. Call "
                "AlertManager.bind_loop() from the loop thread at startup.",
                alert.name,
                len(self._async_handlers),
            )
            return

        for handler in self._async_handlers:
            try:
                if running is target:
                    future: Any = target.create_task(handler(alert))
                else:
                    # Called off the loop's thread; this is the only safe API.
                    future = asyncio.run_coroutine_threadsafe(handler(alert), target)
            except Exception as e:
                logger.error(
                    "Async alert handler failed: handler=%s error=%s",
                    getattr(handler, "__name__", handler),
                    str(e),
                )
                continue
            future.add_done_callback(partial(self._log_handler_outcome, handler, alert))

    @staticmethod
    def _log_handler_outcome(handler: AsyncAlertHandler, alert: Alert, future: Any) -> None:
        """Retrieve the handler's exception so it is reported, not swallowed."""
        try:
            future.result()
        except asyncio.CancelledError:
            # Shutdown, not a handler fault -- but not nothing either, since a
            # cancelled handler is still an alert that was not delivered.
            logger.debug(
                "Async alert handler cancelled: handler=%s alert=%s",
                getattr(handler, "__name__", handler),
                alert.name,
            )
        except Exception as exc:
            logger.error(
                "Async alert handler failed: handler=%s alert=%s error=%s",
                getattr(handler, "__name__", handler),
                alert.name,
                exc,
            )

    def clear_resolved(self) -> int:
        """
        Remove all resolved alerts from memory.

        Returns:
            Number of alerts removed
        """
        with self._lock:
            resolved = [
                name for name, alert in self._alerts.items() if alert.state == AlertState.RESOLVED
            ]
            for name in resolved:
                del self._alerts[name]

            # Clean up grouping
            self._grouping.clear()
            for alert in self._alerts.values():
                group_key = self._get_group_key(alert)
                self._grouping[group_key].append(alert)

            return len(resolved)

    def export_prometheus(self) -> list[dict[str, Any]]:
        """
        Export alerts in Prometheus alertmanager format.

        Returns:
            List of alert dictionaries
        """
        with self._lock:
            return [alert.to_dict() for alert in self.get_firing_alerts()]


# =============================================================================
# Built-in Handlers
# =============================================================================


def log_alert_handler(alert: Alert) -> None:
    """Log alerts using the standard logging module."""
    log_level = {
        AlertSeverity.INFO: logging.INFO,
        AlertSeverity.WARNING: logging.WARNING,
        AlertSeverity.ERROR: logging.ERROR,
        AlertSeverity.CRITICAL: logging.CRITICAL,
    }.get(alert.severity, logging.INFO)

    logger.log(
        log_level, "[ALERT] %s: %s (severity: %s)", alert.name, alert.message, alert.severity.value
    )


# =============================================================================
# Convenience Functions
# =============================================================================

# Global alert manager instance
_default_manager: AlertManager | None = None
_manager_lock = threading.Lock()


def get_alert_manager() -> AlertManager:
    """Get the global AlertManager instance."""
    global _default_manager
    with _manager_lock:
        if _default_manager is None:
            _default_manager = AlertManager()
            _default_manager.register_handler(log_alert_handler)
        return _default_manager


def fire_alert(
    name: str,
    severity: AlertSeverity,
    message: str,
    labels: dict[str, str] | None = None,
    annotations: dict[str, str] | None = None,
) -> Alert:
    """
    Convenience function to fire an alert using the global manager.

    Args:
        name: Alert name
        severity: Alert severity
        message: Alert message
        labels: Optional labels
        annotations: Optional annotations

    Returns:
        The created Alert
    """
    alert = Alert(
        name=name,
        severity=severity,
        message=message,
        labels=labels or {},
        annotations=annotations or {},
    )
    get_alert_manager().fire_alert(alert)
    return alert


def resolve_alert(name: str, message: str | None = None) -> bool:
    """
    Convenience function to resolve an alert using the global manager.

    Args:
        name: Alert name to resolve
        message: Optional resolution message

    Returns:
        True if resolved, False if not found
    """
    return get_alert_manager().resolve_alert(name, message)
