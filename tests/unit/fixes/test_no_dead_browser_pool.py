"""No DI browser pool that nothing uses, and no health line claiming one (F72).

`browser_pool` was registered ("started lazily on first use") but nothing ever
started or acquired it; the browser tools use one PlaywrightAdapter each
collection. /health still reported it "healthy" from an import flag.
"""

from __future__ import annotations

import inspect


def test_the_container_has_no_browser_pool():
    from weebot.application.di import Container

    c = Container()
    c.configure_defaults()
    assert "browser_pool" not in c._bindings


def test_health_does_not_report_a_browser_pool():
    from weebot.interfaces.web.routers import health

    assert 'name="browser_pool"' not in inspect.getsource(health)
