"""weebot: AI Agent Framework for Windows 11."""
# Lazy imports — heavyweight modules are loaded on demand via __getattr__
# to keep the root namespace fast and prevent transitive layer leaks.
import typing as _t
import warnings


# ARCH-AUDIT-V2 A5: agent_core_v2 fully sunset.
# Root lazy imports removed — use Container.build_agent_runner() instead.
_DEPRECATED: frozenset[str] = frozenset()

_LAZY_MAP: dict[str, str] = {}


def __getattr__(name: str) -> _t.Any:
    if name in _LAZY_MAP:
        import importlib
        if name in _DEPRECATED:
            warnings.warn(
                f"weebot.{name} is deprecated. "
                f"See docs/architecture/REMEDIATION_PLAN.md step-17.",
                DeprecationWarning,
                stacklevel=2,
            )
        mod = importlib.import_module(_LAZY_MAP[name], __package__)
        return getattr(mod, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


__all__: list[str] = []
