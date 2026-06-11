"""ExecutorAgent sub-package — extracted modules for ExecutorAgent decomposition.

Current status: extraction in progress.
- cascade_manager.py: model cascade, circuit breaker, fallback
- tool_executor.py: tool call execution, timeout, hooks

The original executor.py still holds ExecutorAgent. As each module stabilizes,
methods will migrate from the God class into these focused classes.
"""
