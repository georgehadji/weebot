"""ExecutorAgent sub-package — extracted modules for ExecutorAgent decomposition.

Current status: extraction in progress.
- _base.py: original ExecutorAgent (migrated from agents/executor.py)
- cascade_manager.py: model cascade, circuit breaker, fallback
- tool_executor.py: tool call execution, timeout, hooks

As each module stabilises, methods will migrate out of _base.ExecutorAgent
into the focused sub-modules above.
"""
from ._base import ExecutorAgent, _classify_tool_error

__all__ = ["ExecutorAgent", "_classify_tool_error"]
