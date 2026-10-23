"""Tools get their settings from WeebotSettings (SSOT audit row 2).

`ToolConfig` exists so tools take settings by injection, and the registry calls
`set_config` on every tool that has it -- but no caller ever passed one, so
`BASH_TIMEOUT`, `PYTHON_TIMEOUT`, `SANDBOX_MAX_OUTPUT_BYTES` and the Berb /
Reasoner / Scraper settings were documented knobs with no effect: tools ran on
the dataclass defaults.
"""

from __future__ import annotations

from weebot.config.settings import WeebotSettings
from weebot.config.tool_config import ToolConfig, tool_config_from_settings


def test_the_tool_config_carries_the_settings_values():
    settings = WeebotSettings(_env_file=None, bash_timeout=91, python_timeout=17)
    cfg = tool_config_from_settings(settings)
    assert (cfg.bash_timeout, cfg.python_timeout) == (91, 17)
    assert cfg.sandbox_max_output_bytes == settings.sandbox_max_output_bytes


def test_the_container_resolves_a_tool_config():
    from weebot.application.di import Container

    c = Container()
    c.configure_defaults()
    assert isinstance(c.get(ToolConfig), ToolConfig)


def test_the_registry_wiring_carries_the_tool_config():
    from weebot.application.di import Container

    c = Container()
    c.configure_defaults()
    assert c.tool_wiring()["tool_config"] is c.get(ToolConfig)
