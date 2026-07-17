"""Contract tests — verify every port has at least one registered adapter.

Each test:
1. Verifies the port ABC is importable
2. Verifies the registered adapter class implements all abstract methods
3. Verifies the adapter can be constructed via DI
4. Flags dead ports (zero adapters) with ``@pytest.mark.skip`` + TODO
"""
from __future__ import annotations

import inspect
import os
from abc import ABC
from pathlib import Path

import pytest

from weebot.application.di import Container

# ── Discover all port modules ─────────────────────────────────────────

PORTS_DIR = Path(__file__).resolve().parent.parent.parent / "weebot" / "application" / "ports"

# Classes that are NOT ports (concretes living in ports/ dir)
_NON_PORT_CLASSES = {
    "NotificationBus",  # concrete implementation defined inside ports/
}

# Ports known to have zero adapters (tracked for future implementation)
_ZERO_ADAPTER_PORTS = {
    "SwarmEventBusPort": (
        "SwarmEventBus exists but does not inherit the port interface"
    ),
    "SpeechPort": (
        "WhisperSpeechAdapter exists but is not found by "
        "conservative scan (nested package)"
    ),
    "TaskQueuePort": (
        "InMemoryTaskQueue exists but is not found by "
        "conservative scan (nested package)"
    ),
    "OptimizerPort": (
        "OptimizerAgent inherits OptimizerPort but is not found by "
        "conservative scan (deep import path)"
    ),
    "CanonicalizerPort": (
        "Docstring documents an ActionCanonicalizer implementation that was "
        "never written — genuinely unimplemented, not a scan gap. "
        "See docs/plans/ARCHITECTURE_9_PLAN.md."
    ),
}


def _discover_ports() -> list[type]:
    """Return every ABC class defined in application/ports/*.py."""
    ports: list[type] = []
    for py_file in sorted(PORTS_DIR.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        mod_name = f"weebot.application.ports.{py_file.stem}"
        try:
            import importlib
            mod = importlib.import_module(mod_name)
        except ImportError as exc:
            print(f"  [SKIP] Could not import {mod_name}: {exc}")
            continue
        for name, obj in inspect.getmembers(mod, inspect.isclass):
            if name in _NON_PORT_CLASSES:
                continue
            # Only classes actually *defined* in this module are ports —
            # re-exported/imported classes (e.g. a type-hint dependency
            # like `FlowFactory = Callable[[Session], BaseFlow]`) are not.
            if obj.__module__ != mod_name:
                continue
            if issubclass(obj, ABC) and obj is not ABC:
                if hasattr(obj, "__abstractmethods__") and obj.__abstractmethods__:
                    ports.append(obj)
    return ports


# Modules that import heavy third-party SDKs at import time.  On local
# developer machines these can block indefinitely (e.g. OpenAI SDK loading
# native deps).  They are still exercised in CI where the environment is clean.
_HEAVY_SDK_MODULES = {
    "weebot.infrastructure.adapters.llm.openai_adapter",
    "weebot.infrastructure.adapters.llm.anthropic_adapter",
    "weebot.infrastructure.adapters.llm.openrouter_adapter",
}


def _get_adapter_classes(port_cls: type) -> list[type]:
    """Find all concrete subclasses of *port_cls* across the codebase.

    Uses a conservative scan through ``weebot.infrastructure``,
    ``weebot.application.services``, and ``weebot.application.agents``.

    Heavy SDK modules are skipped locally to avoid import hangs; CI still
    scans them.  See ``_HEAVY_SDK_MODULES``.
    """
    import importlib
    import pkgutil

    adapters: list[type] = []
    in_ci = bool(os.environ.get("CI"))

    packages_to_scan = [
        "weebot.infrastructure",
        "weebot.application.services",
        "weebot.application.agents",
        "weebot.application.cqrs",
        "weebot.application.eval",  # JudgePort adapters: ModelJudge, ScoreJudge
    ]

    for pkg_name in packages_to_scan:
        try:
            pkg = importlib.import_module(pkg_name)
            pkg_path = getattr(pkg, "__path__", None)
            if not pkg_path:
                continue
            for _importer, mod_name, _is_pkg in pkgutil.walk_packages(
                pkg_path, prefix=f"{pkg_name}.",
            ):
                if not in_ci and mod_name in _HEAVY_SDK_MODULES:
                    continue
                try:
                    mod = importlib.import_module(mod_name)
                except Exception:
                    # Adapter modules may pull optional/heavy deps; a module we
                    # cannot import simply contributes no adapters to the scan.
                    continue
                for _name, obj in inspect.getmembers(mod, inspect.isclass):
                    if (
                        issubclass(obj, port_cls)
                        and obj is not port_cls
                        and not inspect.isabstract(obj)
                    ):
                        adapters.append(obj)
        except Exception:
            continue

    return adapters


def _get_abstract_methods(cls: type) -> list[str]:
    """Return names of abstract methods on *cls*."""
    return sorted(getattr(cls, "__abstractmethods__", set()) or [])


# ── Generate one test per port ────────────────────────────────────────

PORTS = _discover_ports()


@pytest.mark.parametrize("port_cls", PORTS, ids=lambda c: c.__name__)
class TestPortContracts:
    """Verify every port has a valid adapter registered."""

    def test_port_is_abstract(self, port_cls: type) -> None:
        """Port interface must have at least one abstract method."""
        abstract = _get_abstract_methods(port_cls)
        assert len(abstract) > 0, (
            f"{port_cls.__name__} has no abstract methods — "
            f"it may not need to be a port, or methods are missing @abstractmethod"
        )

    def test_has_adapter(self, port_cls: type) -> None:
        """Port must have at least one concrete adapter."""
        if port_cls.__name__ in _ZERO_ADAPTER_PORTS:
            pytest.skip(
                f"{port_cls.__name__}: {_ZERO_ADAPTER_PORTS[port_cls.__name__]}"
            )
        adapters = _get_adapter_classes(port_cls)

        # Heavy SDK adapters (e.g. OpenAI/Anthropic LLM adapters) are skipped
        # locally to avoid import hangs.  Fall back to DI resolution for the
        # known LLMPort case.
        if not adapters and not os.environ.get("CI") and port_cls.__name__ == "LLMPort":
            try:
                container = Container()
                container.configure_defaults()
                instance = container.get(port_cls)  # type: ignore[type-abstract]
                if isinstance(instance, port_cls):
                    pytest.skip(
                        "LLMPort adapter resolved via DI "
                        "(heavy SDK modules skipped locally)"
                    )
            except Exception:
                pass

        assert len(adapters) > 0, (
            f"{port_cls.__name__} has no registered adapter. "
            f"See docs/plans/ARCHITECTURE_9_PLAN.md for tracking."
        )

    def test_adapter_implements_port(self, port_cls: type) -> None:
        """Each adapter must implement all abstract methods of the port."""
        if port_cls.__name__ in _ZERO_ADAPTER_PORTS:
            pytest.skip("Zero-adapter port")
        adapters = _get_adapter_classes(port_cls)
        abstract_methods = _get_abstract_methods(port_cls)

        for adapter_cls in adapters:
            missing = [
                m for m in abstract_methods
                if not hasattr(adapter_cls, m)
            ]
            assert not missing, (
                f"{adapter_cls.__name__} implements {port_cls.__name__} "
                f"but is missing abstract methods: {missing}"
            )

    def test_adapter_constructible_from_di(self, port_cls: type) -> None:
        """The primary adapter for this port can be constructed via DI."""
        if port_cls.__name__ in _ZERO_ADAPTER_PORTS:
            pytest.skip("Zero-adapter port")
        adapters = _get_adapter_classes(port_cls)
        if not adapters:
            pytest.skip("No adapter to test")

        # A port that isn't wired into configure_defaults() is a legitimate
        # skip. A port that IS wired but blows up while constructing is a real
        # bug, and must fail — catching everything here and skipping meant this
        # test could never fail for the one thing it exists to catch.
        container = Container()
        container.configure_defaults()

        # Ask the container whether the port is wired rather than inferring it
        # from a KeyError: Container.get() raises KeyError for an unwired port,
        # but a factory that itself raises KeyError (e.g. os.environ["MISSING"])
        # would then be misread as "not wired" — the same silent pass this test
        # is meant to eliminate.
        is_wired = (
            port_cls in container._bindings or port_cls in container._singletons
        )
        if not is_wired:
            pytest.skip(f"{port_cls.__name__} not wired in configure_defaults()")

        try:
            instance = container.get(port_cls)  # type: ignore[type-abstract]
        except Exception as exc:
            pytest.fail(
                f"{port_cls.__name__} is wired in configure_defaults() but its "
                f"factory raised {type(exc).__name__}: {exc}"
            )

        assert isinstance(instance, port_cls), (
            f"DI returned {type(instance).__name__} which is not a "
            f"{port_cls.__name__}"
        )
