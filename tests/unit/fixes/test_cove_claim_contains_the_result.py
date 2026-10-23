"""CoVe checks an answer against the step's result, not only its description.

Found on the 2026-10-23 runs: every CoVe check on a correct answer came back
"inconsistent" and the summary was rewritten. The claim the consistency check
saw was `summary[:300]`, and the summary starts with the step's description --
planner descriptions run to 250+ characters -- so the result (`348 lines`)
was cut off and the checker compared the answer with a claim that held none.
"""

from __future__ import annotations

import pytest

from weebot.application.flows.states.verifying import VerifyingState


class _LLM:
    def __init__(self):
        self.prompts = []

    async def chat(self, messages, **kw):
        self.prompts.append(messages[-1]["content"])

        class _R:
            content = "YES"

        return _R()


@pytest.mark.asyncio
async def test_the_consistency_prompt_holds_the_step_result():
    llm = _LLM()

    class _Flow:
        _verifier_llm = llm
        _llm = llm

    description = "Run a read-only PowerShell command to count lines " * 6  # ~300 chars
    summary = f"Step step-1: {description}\nResult: README.md has 348 lines"
    await VerifyingState()._check_consistency(_Flow(), "How many lines?", "348", summary)
    assert "348 lines" in llm.prompts[-1]


@pytest.mark.asyncio
async def test_the_evidence_shows_what_each_tool_was_called_with():
    """'What command was run?' was unanswerable: the evidence held tool
    outputs only, never the arguments."""
    from weebot.domain.models.event import ToolEvent, ToolStatus

    llm = _LLM()

    class _Session:
        events = [
            ToolEvent(
                tool_name="powershell",
                function_args={"command": "Get-Content README.md | Measure-Object -Line"},
                status=ToolStatus.CALLED,
                result="348",
            )
        ]

    class _Flow:
        _verifier_llm = llm
        _llm = llm
        _session = _Session()

    await VerifyingState()._answer_independently(_Flow(), "What command was run?")
    assert "Measure-Object" in llm.prompts[-1]


def test_an_answer_the_evidence_cannot_give_is_not_a_contradiction():
    """'The evidence does not say' is unverifiable, not inconsistent; counting
    it as an inconsistency rewrote correct summaries on most runs."""
    assert VerifyingState._is_unverifiable("UNKNOWN: the evidence shows no file writes")
    assert not VerifyingState._is_unverifiable("README.md has 348 lines.")
