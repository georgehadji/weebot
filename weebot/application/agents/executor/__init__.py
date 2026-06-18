"""ExecutorAgent sub-package.

- _base.py: ExecutorAgent implementation (migrated from agents/executor.py)

Dead-code modules (cascade_manager.py, tool_executor.py) were removed after
audit review confirmed zero importers.  Future decomposition should extract
collaborators into weebot/application/flows/collaborators/ instead.
"""
from ._base import ExecutorAgent
from ._error_handler import classify_tool_error as _classify_tool_error

__all__ = ["ExecutorAgent", "_classify_tool_error"]
