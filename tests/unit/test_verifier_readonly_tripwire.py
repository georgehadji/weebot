"""Tripwire for the E7b precondition (LongHorizon-Harness).

E7b — a workspace snapshot/restore guard wrapping the verification
episode — is DEFERRED, and this file is what makes deferring it safe.

The deferral rests on a single factual claim: verification cannot mutate
the environment because it has no path to do so. That claim was asserted
in the plan document and never checked against the code. The same
unchecked-premise pattern already hid a live bug — E7a, where the
verifier rewrote the executor's own Step.result in place, retroactively
corrupting PlanHistory snapshots. So here the premise is executable
rather than asserted.

Two things must remain true for E7b to stay inert:
  1. VerifyingState's LLM calls hand over no tools — the verifier
     cannot act on the world.
  2. StepEvidenceAuditor only reads through FileStoragePort — the
     audit cannot write to it.

When either fails, E7b is live and the snapshot guard has to be built.
See tasks/specs/longhorizon_harness_implementation_plan.md (E7).
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any, Optional

import pytest

from weebot.application.flows.states import verifying as verifying_module
from weebot.application.ports.file_storage_port import FileStoragePort
from weebot.application.services import step_evidence_auditor as auditor_module
from weebot.application.services.step_evidence_auditor import StepEvidenceAuditor
from weebot.domain.models.event import ToolEvent

# Kwargs that would give the verifier's LLM a way to act, not just answer.
_AGENCY_KWARGS = frozenset({"tools", "tool_choice", "functions", "function_call"})

# Every FileStoragePort method, split by whether it changes the filesystem.
_MUTATING_PORT_METHODS = frozenset({"write_text", "write_yaml", "delete"})
_READONLY_PORT_METHODS = frozenset({"read_text", "read_yaml", "read_json", "exists", "size"})


def _parse(module) -> ast.Module:
    """Parse a module's own source — static reach beats runtime coverage here.

    A behavioural test only proves the branches it happens to take;
    the risk is a tools= argument on a rarely-taken path.
    """
    source_file = inspect.getsourcefile(module)
    assert source_file is not None, f"cannot locate source for {module.__name__}"
    return ast.parse(Path(source_file).read_text(encoding="utf-8"))


def _chat_calls(tree: ast.Module) -> list[ast.Call]:
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "chat"
    ]


# ── Tripwire 1: the verifier cannot act ──────────────────────────────

def test_verifier_llm_calls_hand_over_no_tools():
    """E7b precondition: VerifyingState asks questions, it does not act.

    The moment any verification call gains tools=, the verifier can touch
    the filesystem and the E7b snapshot guard stops being optional.
    """
    tree = _parse(verifying_module)
    calls = _chat_calls(tree)
    assert calls, (
        "no .chat() calls found in verifying.py — this tripwire is pointing "
        "at the wrong thing and is silently passing"
    )

    offenders = [
        f"{kw.arg}= at line {call.lineno}"
        for call in calls
        for kw in call.keywords
        if kw.arg in _AGENCY_KWARGS
    ]
    assert not offenders, (
        "VerifyingState now passes tool-granting kwargs to the LLM: "
        f"{offenders}. E7b (workspace snapshot guard) is no longer inert — "
        "the verifier can mutate the environment it audits. Implement it."
    )


def test_verifier_llm_calls_take_no_kwargs_splat():
    """A **kwargs splat could smuggle tools= past the check above.

    Statically undecidable, so it is banned outright rather than trusted.
    """
    tree = _parse(verifying_module)
    splats = [
        f"line {call.lineno}"
        for call in _chat_calls(tree)
        for kw in call.keywords
        if kw.arg is None  # ast represents **mapping as a keyword with arg=None
    ]
    assert not splats, (
        f"**kwargs splat in a verifier .chat() call at {splats} — its contents "
        "cannot be checked statically, so tools= could pass unnoticed. "
        "Pass verification kwargs explicitly."
    )


# ── Tripwire 2: the audit cannot write ───────────────────────────────

def test_step_evidence_auditor_uses_only_readonly_port_methods():
    """Static half: every self._files.* call across ALL branches is a read."""
    tree = _parse(auditor_module)
    used = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "_files"
    }
    assert used, (
        "StepEvidenceAuditor no longer references self._files — this tripwire "
        "is pointing at the wrong attribute and is silently passing"
    )

    writes = used - _READONLY_PORT_METHODS
    assert not writes, (
        f"StepEvidenceAuditor now calls mutating port method(s): {sorted(writes)}. "
        "The audit can write to the workspace it audits — E7b is live."
    )


class _TripwirePort(FileStoragePort):
    """A FileStoragePort where every mutating method is a landmine."""

    def __init__(self) -> None:
        self.reads: list[str] = []

    def _detonate(self, method: str) -> None:
        raise AssertionError(
            f"StepEvidenceAuditor called FileStoragePort.{method} — the audit "
            "mutated the workspace it was auditing. E7b is live."
        )

    async def read_text(self, path: str) -> str:
        self.reads.append(path)
        return '<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"/>'

    async def read_yaml(self, path: str) -> dict[str, Any]:
        self.reads.append(path)
        return {}

    async def read_json(self, path: str) -> Any:
        self.reads.append(path)
        return {}

    async def exists(self, path: str) -> bool:
        self.reads.append(path)
        return False  # trip gate A so the violation path runs too

    async def size(self, path: str) -> Optional[int]:
        self.reads.append(path)
        return 512  # undersized, so gate C reads the file head

    async def write_text(self, path: str, content: str) -> None:
        self._detonate("write_text")

    async def write_yaml(self, path: str, data: dict[str, Any]) -> None:
        self._detonate("write_yaml")

    async def delete(self, path: str) -> bool:
        self._detonate("delete")
        return False


@pytest.mark.asyncio
async def test_step_evidence_auditor_writes_nothing_when_every_gate_trips():
    """Behavioural half: run all three gates down their violation paths.

    Violation paths matter more than clean ones — "found a problem" is
    exactly where a future author would be tempted to repair it in place.
    """
    port = _TripwirePort()
    events = [
        ToolEvent(tool_name="write_file", function_args={"path": "missing.txt"}),          # gate A
        ToolEvent(tool_name="bash", function_args={"command": "pytest tests/"},
                  result="3 failed, 1 passed"),                                            # gate B
        ToolEvent(tool_name="image_gen", function_args={"output_path": "hero.png"}),       # gate C
    ]

    report = await StepEvidenceAuditor(port).audit_step(step=None, events=events)

    assert port.reads, "no port reads happened — the gates did not actually run"
    assert report.violations, "expected violations — this fixture is meant to trip every gate"


# ── Rot guard ────────────────────────────────────────────────────────

def test_every_port_method_is_classified_read_or_write():
    """If FileStoragePort grows a method, classify it before shipping.

    Without this, a new mutating method (move, copy, truncate) would be
    invisible to the read-only check above, which only knows the names
    it was given.
    """
    declared = set(FileStoragePort.__abstractmethods__)
    classified = _MUTATING_PORT_METHODS | _READONLY_PORT_METHODS

    assert declared == classified, (
        "FileStoragePort's surface changed. Unclassified: "
        f"{sorted(declared - classified)}; stale: {sorted(classified - declared)}. "
        "Add each new method to _MUTATING_PORT_METHODS or _READONLY_PORT_METHODS."
    )
