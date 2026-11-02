"""Decide how a browser is obtained: connect to the CDP browser, launch one, or refuse.

``WEEBOT_BROWSER_CDP_URL`` points Chromium at a running CDP browser such as Lightpanda
(``docker run -d -p 127.0.0.1:9222:9222 lightpanda/browser``). The policy fails closed
(docs/SECURITY_MODEL.md): when that browser is down, or the request needs a local browser
(a proxy, ``headless=False``), the call is refused unless ``WEEBOT_BROWSER_CDP_FALLBACK`` is
on. The agent sets ``headless`` through a tool argument, so a launch-only option must never be
a quiet way out of the container.

The module is a functional core with a thin shell:

* ``plan_launch`` is a pure function from values to a ``LaunchPlan``. No I/O, no settings.
* ``open_browser`` reads the settings, asks the core, and carries the plan out, with a connect
  timeout and a circuit breaker so a dead endpoint costs one wait per cooldown, not one per call.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from weebot.core.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

_COOLDOWN_SECONDS = 30.0
_INVALID_URL = "<invalid CDP url>"


class CdpBrowserUnavailable(RuntimeError):
    """The CDP browser cannot serve this call and the operator has not allowed a local launch."""


@dataclass(frozen=True)
class CdpSettings:
    url: str | None = None
    fallback: bool = False
    connect_timeout_ms: int = 5000
    max_connections: int = 0
    share_connection: bool = False

    @classmethod
    def from_settings(cls) -> CdpSettings:
        from weebot.config.settings import get_settings

        s = get_settings()
        return cls(
            url=s.browser_cdp_url or None,
            fallback=s.browser_cdp_fallback,
            connect_timeout_ms=s.browser_cdp_connect_timeout_ms,
            max_connections=s.browser_cdp_max_connections,
            share_connection=s.browser_cdp_share_connection,
        )


@dataclass(frozen=True)
class LaunchPlan:
    mode: Literal["connect", "launch", "refuse"]
    reason: str = ""


def _launch_only(launch_options: dict[str, Any]) -> list[str]:
    """Options a CDP browser cannot honour: they exist only on a locally launched browser."""
    found = []
    if "proxy" in launch_options:
        found.append("proxy")
    if launch_options.get("headless") is False:
        found.append("headless=False")
    return found


def plan_launch(
    browser_name: str, launch_options: dict[str, Any], cdp: CdpSettings, breaker_open: bool
) -> LaunchPlan:
    """Pure policy. A local launch under CDP needs the operator's opt-in.

    Playwright's ``connect_over_cdp`` is Chromium-only, so Firefox and WebKit can only be
    launched, which makes them launch-only like a proxy.
    """
    if not cdp.url:
        return LaunchPlan("launch")

    needs_local = _launch_only(launch_options)
    if browser_name != "chromium":
        needs_local.insert(0, f"{browser_name} (CDP is Chromium-only)")
    if needs_local:
        reason = f"{', '.join(needs_local)} needs a local browser; WEEBOT_BROWSER_CDP_URL is set"
    elif breaker_open:
        reason = "CDP endpoint unavailable"
    else:
        return LaunchPlan("connect")

    if cdp.fallback:
        return LaunchPlan("launch", reason)
    hint = "set WEEBOT_BROWSER_CDP_FALLBACK=1 to allow a local launch"
    return LaunchPlan("refuse", f"{reason}; {hint}")


def redact_endpoint(url: str) -> str:
    """Scheme, host and port only. Userinfo, path, query and fragment can carry a token."""
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError:
        return _INVALID_URL
    if not parts.scheme or not host:
        return _INVALID_URL
    if ":" in host:
        host = f"[{host}]"
    return f"{parts.scheme}://{host}" + (f":{port}" if port else "")


def cdp_connection_cap() -> int:
    """Most simultaneous CDP connections the endpoint takes; 0 when CDP is off or uncapped."""
    cdp = CdpSettings.from_settings()
    if not cdp.url or cdp.share_connection:  # shared: the whole pool is one connection
        return 0
    return max(0, cdp.max_connections)


def _new_breaker() -> CircuitBreaker:
    # One failure opens it. No jitter or stagger: a single endpoint, nothing to thunder at.
    return CircuitBreaker(
        failure_threshold=1,
        cooldown_seconds=_COOLDOWN_SECONDS,
        jitter_percent=0,
        enable_stagger=False,
    )


_breaker = _new_breaker()


async def open_browser(browser_type: Any, launch_options: dict[str, Any]) -> Any:
    """Return a Playwright ``Browser`` for *browser_type*, following ``plan_launch``.

    Raises ``CdpBrowserUnavailable`` when the plan is to refuse.
    """
    cdp = CdpSettings.from_settings()
    name = browser_type.name
    plan = plan_launch(name, launch_options, cdp, breaker_open=False)

    if plan.mode == "connect":
        endpoint = redact_endpoint(cdp.url)
        if (await _breaker.evaluate(endpoint)).allowed:
            try:
                browser = await browser_type.connect_over_cdp(
                    cdp.url, timeout=cdp.connect_timeout_ms
                )
            except Exception as exc:
                await _breaker.record_failure(endpoint)
                # The exception text can echo the url, so only its type is logged.
                logger.warning(
                    "CDP browser at %s unreachable (%s); retrying in %ss",
                    endpoint,
                    type(exc).__name__,
                    int(_COOLDOWN_SECONDS),
                )
            else:
                await _breaker.record_success(endpoint)
                return browser
        plan = plan_launch(name, launch_options, cdp, breaker_open=True)

    if plan.mode == "refuse":
        raise CdpBrowserUnavailable(f"{plan.reason} ({redact_endpoint(cdp.url)})")
    if plan.reason:
        logger.debug("Launching %s on the host: %s", name, plan.reason)
    return await browser_type.launch(**launch_options)


class SharedBrowser:
    """One CDP connection reused by every session of a pool, one context per session.

    Opt-in (``WEEBOT_BROWSER_CDP_SHARE_CONNECTION``): the endpoint must allow many contexts
    per connection. Lightpanda allows one, so it keeps its own connection per session.
    """

    def __init__(self) -> None:
        self._browser: Any | None = None
        self._lock = asyncio.Lock()

    async def acquire(self, browser_type: Any, launch_options: dict[str, Any]) -> Any | None:
        """The shared browser, or None when this request must get a browser of its own."""
        cdp = CdpSettings.from_settings()
        if not cdp.share_connection:
            return None
        plan = plan_launch(browser_type.name, launch_options, cdp, breaker_open=False)
        if plan.mode != "connect":
            return None  # a launch-only option or another engine: not a plain CDP connection
        async with self._lock:
            if self._browser is None or not self._browser.is_connected():
                self._browser = await open_browser(browser_type, launch_options)
            return self._browser

    async def close(self) -> None:
        browser, self._browser = self._browser, None
        if browser is not None:
            await browser.close()
