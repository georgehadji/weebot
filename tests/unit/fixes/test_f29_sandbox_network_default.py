"""F29: the sandbox allowed network although the setting said off (fixed in W3.9).

`SandboxConfig()` defaulted to `allow_network=True` and nothing built a config
from `WeebotSettings`. Now the default is off, `create_default_sandbox()` uses
`build_sandbox_config(settings)`, and a single call gets network only when
ToolExecutor clears it (decision 7, ADR-013).
"""

from weebot.application.ports.sandbox_port import SandboxConfig
from weebot.config.settings import WeebotSettings, get_settings
from weebot.infrastructure.sandbox.factory import build_sandbox_config, create_default_sandbox


def test_setting_defaults_to_network_off():
    assert WeebotSettings().sandbox_allow_network is False


def test_default_sandbox_config_has_network_off():
    assert SandboxConfig().allow_network is False


def test_default_sandbox_reads_the_settings(monkeypatch):
    monkeypatch.setenv("SANDBOX_ALLOW_NETWORK", "true")
    monkeypatch.setenv("SANDBOX_MAX_OUTPUT_BYTES", "4096")
    config = build_sandbox_config(get_settings())
    assert (config.allow_network, config.max_output_bytes) == (True, 4096)
    assert create_default_sandbox()._config.allow_network is True
