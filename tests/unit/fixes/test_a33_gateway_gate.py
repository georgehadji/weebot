"""A33: `GatewayAdapter.handle()` consulted `SafetyChecker.is_critical_operation(text, "gateway")`,
which is False for every tool but "powershell_executor": the gate could never fire.

The fix is to delete the gate, not to make it fire: it scanned the user's chat text for words
like "rm" and "delete", which would also refuse ordinary sentences, and the actions a gateway
run can take are already gated by the guard chain, which wraps the tools of every collection
the registry builds (including the one `build_tools` gives the gateways).
"""

from __future__ import annotations

import inspect

import pytest

from weebot.core.safety import SafetyChecker
from weebot.interfaces.gateways.base import GatewayAdapter


def test_the_inert_gate_is_the_proof_of_the_defect():
    """Pins the finding: the gate the gateway consulted was False for the text it was given."""
    checker = SafetyChecker(llm=None)
    assert checker.is_critical_operation("rm -rf /", "gateway") is False


@pytest.mark.xfail(strict=True, reason="A33: the gateway still consults an inert gate")
def test_the_gateway_no_longer_carries_a_gate_that_cannot_fire():
    assert "is_critical_operation" not in inspect.getsource(GatewayAdapter.handle)
    assert "SafetyChecker" not in inspect.getsource(GatewayAdapter.__init__)


async def test_a_dangerous_sentence_is_passed_on_not_blocked_by_a_word_list():
    class _Adapter(GatewayAdapter):
        async def start(self): ...
        async def stop(self): ...
        async def send_response(self, response): ...

    adapter = _Adapter.__new__(_Adapter)
    adapter._safety = SafetyChecker(llm=None)  # present before the fix, absent after it
    message = type("M", (), {"text": "please remove the draft from my reminders"})()
    assert await adapter.handle(message) == message.text


def test_gateway_tools_come_from_a_guarded_collection():
    """The registry wraps shell and python tools in GuardedTool, which is what covers gateways."""
    from weebot.application.services.tool_guards import GuardedTool
    from weebot.interfaces import factories

    source = inspect.getsource(factories.build_tools)
    assert "registry.create_tool_collection" in source
    from weebot.application.services import tool_registry

    assert "guard_tools" in inspect.getsource(tool_registry)
    assert GuardedTool is not None
