"""The web UI's dev and start servers listen on loopback only (F45).

The UI's `/api` proxy calls the backend from the Next server, so the backend
sees 127.0.0.1, and loopback skips the API-key check. `next dev` / `next start`
listen on every interface by default, so anyone on the LAN could mutate through
the proxy without a key. Next sets `x-forwarded-for` with `??=`, so the proxy
cannot tell a remote client from a local one by headers. Docker is not affected:
there the backend sees the UI container's address, not loopback.
"""

from __future__ import annotations

import json
import pathlib


def test_dev_and_start_bind_127_0_0_1():
    root = pathlib.Path(__file__).resolve().parents[3]
    scripts = json.loads((root / "weebot-ui" / "package.json").read_text(encoding="utf-8"))[
        "scripts"
    ]
    for name in ("dev", "start"):
        assert "-H 127.0.0.1" in scripts[name], (name, scripts[name])
