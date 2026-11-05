"""The container gives `python_execute` its kernel manager, and session delete stops it (H17).

A tool built without the manager still works one-shot, so an unwired tool would pass every
other test while a persistent kernel was never used in a real flow.
"""

from __future__ import annotations

from weebot.application.ports.sandbox_port import SandboxType


class _Sandbox:
    sandbox_type = SandboxType.NATIVE_WINDOWS

    async def execute_python(self, code, timeout, memory_limit_mb=None):  # pragma: no cover
        raise AssertionError("not reached")


def _python_tool(container):
    from weebot.application.services.tool_registry import RoleBasedToolRegistry

    registry = RoleBasedToolRegistry(wiring=container.tool_wiring)
    collection = registry.create_tool_collection("admin", sandbox_port=_Sandbox())
    return collection.get_tool("python_execute").inner  # GuardedTool wraps it


def test_python_execute_is_built_with_the_containers_kernel_manager():
    from weebot.application.di import Container
    from weebot.application.services.kernel_manager import KernelManager

    container = Container()
    container.configure_defaults()

    assert _python_tool(container)._kernels is container.get(KernelManager)


def test_every_collection_shares_one_manager():
    from weebot.application.di import Container

    container = Container()
    container.configure_defaults()

    assert _python_tool(container)._kernels is _python_tool(container)._kernels


def test_a_registry_without_wiring_builds_the_tool_one_shot():
    from weebot.application.services.tool_registry import RoleBasedToolRegistry

    tool = (
        RoleBasedToolRegistry()
        .create_tool_collection("admin", sandbox_port=_Sandbox())
        .get_tool("python_execute")
        .inner
    )

    assert tool._kernels is None


def test_session_delete_stops_the_sessions_kernel():
    from weebot.application.services.kernel_manager import KernelManager
    from weebot.interfaces.web.dependencies import _session_stores

    assert ("kernels", KernelManager, "stop_session") in _session_stores()
