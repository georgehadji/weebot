"""One set names the shell tools (SSOT audit row 17).

`tool_guards.SHELL_TOOLS` is the set the guard chain parses commands for. The
step-evidence auditor and the memory compactor kept their own copies, with a
`shell_exec` tool that does not exist; a shell tool added to the guard set would
have been missed by both.
"""

from __future__ import annotations

import inspect

from weebot.application.services import memory_compactor, step_evidence_auditor, tool_guards


def test_the_auditor_uses_the_guard_set():
    assert step_evidence_auditor._SHELL_TOOLS is tool_guards.SHELL_TOOLS


def test_the_compactor_uses_the_guard_set():
    source = inspect.getsource(memory_compactor)
    assert '"shell_exec"' not in source
    assert "SHELL_TOOLS" in source
