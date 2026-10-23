"""`.env.example` and `docs/CONFIGURATION.md` say what the code does.

Both files are generated from `CONFIG_SCHEMA` in
`scripts/generate_config_reference.py`, a hand-written list. Where a variable is
a `WeebotSettings` field the list carried its own default, and five had drifted
(gateway session TTL 3600 against 604800, per-platform cap 50 against 100,
e-mail poll 60 against 30, both mail hosts blank against gmail). Fifteen more
variables were documented that nothing reads, eleven of them `GITNEXUS_*` for a
`GitNexusConfig` no module imported. The settings field is now the one
home of its default; the list keeps only the name, the description and whether
it is a secret.
"""

from __future__ import annotations

import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_config_reference as gen  # noqa: E402


def test_committed_files_are_the_generator_output():
    schema = gen.resolved_schema()
    assert (ROOT / ".env.example").read_text(encoding="utf-8") == gen.generate_env_example(schema)
    assert (ROOT / "docs/CONFIGURATION.md").read_text(encoding="utf-8") == gen.generate_config_md(
        schema
    )


@pytest.mark.parametrize(
    ("var", "expected"),
    [
        ("WEEBOT_GATEWAY_SESSION_TTL_SECONDS", "604800"),
        ("WEEBOT_GATEWAY_MAX_SESSIONS_PER_PLATFORM", "100"),
        ("EMAIL_POLL_INTERVAL_SECONDS", "30.0"),
        ("EMAIL_IMAP_SERVER", "imap.gmail.com"),
        ("WEEBOT_WEB_REQUIRE_AUTH", "true"),
    ],
)
def test_a_settings_default_is_documented_as_settings_has_it(var, expected):
    entry = next(e for e in gen.resolved_schema() if e["var"] == var)
    assert entry["default"] == expected


def test_every_documented_variable_has_a_reader():
    readers = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for pattern in ("weebot/**/*.py", "cli/**/*.py", "scripts/**/*.py", "tests/**/*.py")
        for p in ROOT.glob(pattern)
        if p.name != "generate_config_reference.py"
    )
    readers += (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    settings_names = gen.settings_env_names()
    dead = sorted(
        e["var"]
        for e in gen.CONFIG_SCHEMA
        if e["var"] not in settings_names and not re.search(rf"\b{e['var']}\b", readers)
    )
    assert dead == []
