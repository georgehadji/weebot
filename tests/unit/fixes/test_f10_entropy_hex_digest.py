"""F10: the analyzer's entropy layer rated hex digests DANGEROUS (fixed in W3.6).

`git checkout <40-hex sha>` was refused by the bash tool because layer 3 saw
a high-entropy "encoded payload": a 1.2x entropy multiplier lifted hex
(at most 4.0 bits/char) over the 4.0 threshold. The multiplier is gone and
pure-hex runs are excluded; tests/unit/tools/data/command_corpus.json holds
the wider calibration.
"""

import pytest

from weebot.tools.bash_security import CommandRiskLevel, get_security_analyzer


@pytest.mark.parametrize(
    "command",
    [
        "git checkout 3f786850e387550fdab836ed7e6dc881de23001b",
        "docker pull python@sha256:"
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ],
)
def test_hex_digest_is_not_dangerous(command):
    assert get_security_analyzer().analyze(command).risk_level != CommandRiskLevel.DANGEROUS
