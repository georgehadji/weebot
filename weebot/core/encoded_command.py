"""One answer to "is this a PowerShell -EncodedCommand?" for every shell gate.

PowerShell accepts any prefix of ``-EncodedCommand`` and either ``-`` or ``/`` before it,
so ``-en``, ``-enc``, ``/EncodedComm`` and the ``-ec`` alias all run a base64 payload.
Each gate used to carry its own list and each list missed some of them.

``-e`` and ``-ec`` are also ordinary flags of other tools (``grep -e``, ``sed -e``), so
they count only in a command that names ``powershell`` or ``pwsh``. A value that is a
known text encoding (``Out-File -enc utf8NoBOM``) is not a payload.
"""

from __future__ import annotations

import re

_FULL = "encodedcommand"
# -en ... -encodedcommand: prefixes of the full name that no other PowerShell parameter shares.
_LONG = "|".join(_FULL[:n] for n in range(2, len(_FULL) + 1))
_BLOB = r"[A-Za-z0-9+/]{8,}={0,2}(?![A-Za-z0-9+/=])"
_ENCODINGS = r"(?:utf-?8(?:nobom|bom)?|utf-?(?:16|32)|unicode|ascii|oem|default|bigendian\w*)\b"
_VALUE = rf"(?:\s+|[:=])(?!{_ENCODINGS}){_BLOB}"
_START = r"(?:^|[\s;&|(])[-/]"

LONG_FORM = rf"{_START}(?:{_LONG}){_VALUE}"
# The same command segment: `powershell -NoProfile -e <blob>`, not `powershell x | grep -e <blob>`.
SHORT_FORM = rf"\b(?:powershell|pwsh)(?:\.exe)?\b[^|;&\n]*{_START}(?:e|ec){_VALUE}"

_LONG_RE = re.compile(LONG_FORM, re.IGNORECASE)
_SHORT_RE = re.compile(SHORT_FORM, re.IGNORECASE)


def has_encoded_command(command: str) -> bool:
    """True when *command* hands PowerShell a base64 payload."""
    return bool(_LONG_RE.search(command) or _SHORT_RE.search(command))
