"""An unset `${VAR}` in one MCP server's config skips that server only.

`expand_env` ran over the whole file and raised ConfigError on the first unset
variable, so one missing key (say `${POSTIZ_API_KEY}`) removed every
configured server, Apify included.
"""

from __future__ import annotations

import json
import types

from weebot.application.di._factories import FactoriesMixin


def test_the_other_servers_still_load(tmp_path, monkeypatch):
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({
        "good": {"url": "https://example.test/mcp"},
        "needs_key": {
            "url": "https://x.test",
            "headers": {"Authorization": "Bearer ${WB_TEST_UNSET_KEY}"},
        },
    }), encoding="utf-8")
    monkeypatch.delenv("WB_TEST_UNSET_KEY", raising=False)
    monkeypatch.setenv("WEEBOT_ENABLE_X_MCP", "1")
    monkeypatch.setattr("weebot.config.settings.get_settings",
                        lambda: types.SimpleNamespace(mcp_servers_config_path=str(cfg)))
    manager = FactoriesMixin()._create_mcp_client()
    assert list(manager._config["mcpServers"]) == ["good"]
