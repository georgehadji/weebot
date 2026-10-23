"""A bundled JMAP preset resolves by the name the docs give it.

Found on the first live inbox read (2026-10-23): docs/atomic_mail.md and the
tool's own help say `ops_file="list_inbox"`, but only `list_inbox.json`
resolved, so every documented preset call failed. The bare name now resolves
against the bundled presets only; the credential directory still needs the
exact name, so a self-written file there cannot pose as a read preset.
"""

from __future__ import annotations

import pytest

from weebot.infrastructure.adapters.atomicmail.jmap_request import _read_ops_file


@pytest.mark.parametrize("name", ["list_inbox", "list_inbox.json"])
def test_the_documented_preset_name_resolves(tmp_path, name):
    assert "Email/query" in _read_ops_file(str(tmp_path), name)


def test_an_unknown_preset_still_fails(tmp_path):
    with pytest.raises(ValueError):
        _read_ops_file(str(tmp_path), "no_such_preset")
