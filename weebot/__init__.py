"""weebot: AI Agent Framework for Windows 11."""
# Lazy imports — heavyweight modules are loaded on demand via __getattr__
# to keep the root namespace fast and prevent transitive layer leaks.
import typing as _t
import warnings


_DEPRECATED = frozenset({
    "WeebotAgent", "AgentConfig",
})

_LAZY_MAP = {
    "WeebotAgent": ".agent_core_v2",
    "AgentConfig": ".agent_core_v2",
}


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


__all__ = [
    "WeebotAgent",
    "AgentConfig",
]
