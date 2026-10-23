"""The `WEEBOT_*` names `.env.example` documents are the names settings read.

`WeebotSettings` has no `env_prefix`, so a field without an alias is read from
its bare upper-case name (`WEB_REQUIRE_AUTH`). Eight fields were documented,
and set in real `.env` files, under a `WEEBOT_` name nothing read -- three of
them security knobs (web auth, webhook key, webhook exec tools). Their defaults
happen to be the safe side, so the failure was silent: a configured webhook key
was ignored, and so was every gateway session limit.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from weebot.config.settings import WeebotSettings

ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("env", "field", "raw", "expected"),
    [
        ("WEEBOT_WEB_REQUIRE_AUTH", "web_require_auth", "false", False),
        ("WEEBOT_WEBHOOK_API_KEY", "webhook_api_key", "k-test", "k-test"),
        ("WEEBOT_WEBHOOK_ALLOW_EXEC_TOOLS", "webhook_allow_exec_tools", "true", True),
        ("WEEBOT_GATEWAY_AUTH_ENABLED", "gateway_auth_enabled", "false", False),
        ("WEEBOT_GATEWAY_SESSION_TTL_SECONDS", "gateway_session_ttl_seconds", "3600", 3600),
        ("WEEBOT_GATEWAY_MAX_SESSIONS_PER_PLATFORM", "gateway_max_sessions_per_platform", "7", 7),
        ("WEEBOT_MCP_COMPOSITE_TOOLS_ENABLED", "mcp_composite_tools_enabled", "false", False),
        ("WEEBOT_PONYTAIL_MODE", "ponytail_mode", "lite", "lite"),
    ],
)
def test_the_documented_name_reaches_the_field(monkeypatch, env, field, raw, expected):
    monkeypatch.setenv(env, raw)
    assert getattr(WeebotSettings(_env_file=None), field) == expected


def test_the_bare_name_still_works(monkeypatch):
    # The WEEBOT_ name wins when both are set; another test may have loaded it.
    monkeypatch.delenv("WEEBOT_PONYTAIL_MODE", raising=False)
    monkeypatch.setenv("PONYTAIL_MODE", "full")
    assert WeebotSettings(_env_file=None).ponytail_mode == "full"


def _settings_env_names() -> set[str]:
    names: set[str] = set()
    for name, f in WeebotSettings.model_fields.items():
        names.add(name.upper())
        for alias in (f.alias, f.validation_alias):
            if alias is not None:
                names.update(re.findall(r"[A-Z][A-Z0-9_]+", str(alias)))
    return names


def test_every_documented_weebot_name_has_a_reader():
    """A documented knob nothing reads is worse than an undocumented one."""
    documented = set(
        re.findall(
            r"^#?\s*(WEEBOT_[A-Z0-9_]+)=",
            (ROOT / ".env.example").read_text(encoding="utf-8"),
            re.M,
        )
    )
    code = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for d in ("weebot", "cli")
        for p in (ROOT / d).rglob("*.py")
    )
    read = _settings_env_names()
    dead = sorted(
        n for n in documented if n not in read and f'"{n}"' not in code and f"'{n}'" not in code
    )
    assert dead == []
