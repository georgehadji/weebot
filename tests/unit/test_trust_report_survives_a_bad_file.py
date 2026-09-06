"""A corrupt trust file must not crash the trust report.

`get_trust_report` wraps `json.loads(TRUST_FILE.read_text())` in a handler that
catches JSONDecodeError and FileNotFoundError and substitutes a default. The
`.get` calls that consume the result sit OUTSIDE that handler, so a file that is
valid JSON but not an object -- or an object whose `score` is not a number --
walks straight past the fallback the handler exists to provide.

Measured before the fix, all six raising:

    []                   -> AttributeError: 'list' object has no attribute 'get'
    "a string"           -> AttributeError: 'str' object has no attribute 'get'
    123                  -> AttributeError: 'int' object has no attribute 'get'
    null                 -> AttributeError: 'NoneType' object has no attribute 'get'
    {"score": "high"}    -> ValueError: invalid literal for int() ... 'highhigh...'
    {"score": null}      -> TypeError: unsupported operand type(s) for *: 'NoneType' and 'int'

The fifth is the one worth reading twice: `"high" * 100` is a legal string
repetition, so the wrong type produced a 400-character string and failed one
call later, nowhere near the file that caused it.

Same shape as D61: `.get(key, default)` substitutes only when the key is
ABSENT, never when it is present and wrong.
"""

from __future__ import annotations

import pytest

from weebot.core import behavior_reporting as br


@pytest.fixture
def trust_file(tmp_path, monkeypatch):
    f = tmp_path / "trust.json"
    monkeypatch.setattr(br, "TRUST_FILE", f)
    monkeypatch.setattr(br, "LEDGER_DIR", tmp_path / "ledger")
    (tmp_path / "ledger").mkdir()
    return f


@pytest.mark.parametrize(
    "raw",
    ["[]", '"a string"', "123", "null", "true",
     '{"score": "high"}', '{"score": null}', '{"score": [1]}',
     '{"total": "many"}', '{"overrides": {}}'],
)
def test_a_wrong_shaped_trust_file_falls_back_instead_of_raising(trust_file, raw):
    trust_file.write_text(raw)
    report = br.BehaviorReporter().get_trust_report()
    assert isinstance(report["score_percentage"], int)
    assert 0 <= report["score_percentage"] <= 100
    assert report["status"] in {"trusted", "review", "supervision"}


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('{"score": 5}', 100),        # above range -> clamped, not defaulted
        ('{"score": -3}', 0),
        ('{"score": 1e400}', 100),    # +inf
        ('{"score": -1e400}', 0),     # -inf: must NOT report "fully trusted"
        ('{"score": true}', 100),     # bool is not a score; takes the default
        ('{"score": 0}', 0),
    ],
)
def test_an_out_of_range_score_is_clamped_by_sign(trust_file, raw, expected):
    """An infinity carries a sign, so it clamps; only NaN takes the default.

    Defaulting -inf to 1.0 would report a corrupt file as fully trusted -- the
    fail-open direction, in the one number whose job is to say when to stop
    trusting.
    """
    trust_file.write_text(raw)
    assert br.BehaviorReporter().get_trust_report()["score_percentage"] == expected


def test_the_reporter_never_rewrites_the_file_it_reads(trust_file):
    trust_file.write_text("[]")
    br.BehaviorReporter().get_trust_report()
    assert trust_file.read_text() == "[]", "the reporter rewrote a file it only reads"


def test_an_unparseable_file_still_falls_back(trust_file):
    """The case the handler already covered. Must keep working."""
    trust_file.write_text("{not json")
    assert br.BehaviorReporter().get_trust_report()["score_percentage"] == 100


def test_a_missing_file_still_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(br, "TRUST_FILE", tmp_path / "absent.json")
    monkeypatch.setattr(br, "LEDGER_DIR", tmp_path / "ledger")
    (tmp_path / "ledger").mkdir()
    assert br.BehaviorReporter().get_trust_report()["score_percentage"] == 100


def test_a_good_trust_file_is_reported_faithfully(trust_file):
    """The control: a real file must be read, not defaulted away."""
    trust_file.write_text('{"score": 0.82, "total": 50, "overrides": 9, '
                          '"last_updated": "2026-01-01"}')
    report = br.BehaviorReporter().get_trust_report()
    assert report["score"] == 0.82
    assert report["score_percentage"] == 82
    assert report["total_actions"] == 50
    assert report["overrides"] == 9
    assert report["last_updated"] == "2026-01-01"
    assert report["status"] == "review"
