"""PythonExecuteTool — run Python code in an isolated subprocess."""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Optional

from pydantic import ConfigDict, PrivateAttr

from weebot.core.approval_policy import ExecApprovalPolicy
from weebot.sandbox.executor import SandboxedExecutor
from weebot.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from weebot.config.settings import WeebotSettings

# Module-level singleton — parsed once per process instead of per tool instance.
_SETTINGS: Optional["WeebotSettings"] = None


def _get_settings() -> "WeebotSettings":
    global _SETTINGS
    if _SETTINGS is None:
        from weebot.config.settings import WeebotSettings
        _SETTINGS = WeebotSettings()
    return _SETTINGS


class PythonExecuteTool(BaseTool):
    """Execute Python code in an isolated subprocess.

    The code is passed to a child Python interpreter via ``python -c <code>``,
    giving full process isolation with independent timeout and memory limits.
    stdout and stderr are captured and returned to the agent.

    Supports data analysis libraries (pandas, numpy, matplotlib) as long as
    they are installed in the same Python environment.

    Safety gate: the code string is evaluated by ExecApprovalPolicy before
    execution.  Code that matches a DENY rule (e.g. contains the literal
    ``format``) is blocked; code matching ALWAYS_ASK is blocked pending
    explicit user confirmation.
    """

    name: str = "python_execute"
    description: str = (
        "Execute Python code in an isolated subprocess. "
        "stdout and stderr are captured and returned. "
        "Supports pandas, numpy, matplotlib if installed. "
        "Use print() to produce output visible to the agent."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python source code to execute",
            },
            "timeout": {
                "type": "number",
                "description": "Timeout in seconds (default 30)",
            },
        },
        "required": ["code"],
    }

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _executor: SandboxedExecutor = PrivateAttr(default=None)
    _policy: ExecApprovalPolicy = PrivateAttr(default=None)
    _default_timeout: float = PrivateAttr(default=30.0)

    def model_post_init(self, __context: object) -> None:
        """Initialise the sandboxed executor and the approval policy."""
        settings = _get_settings()
        self._default_timeout = float(settings.python_timeout)
        self._executor = SandboxedExecutor(
            max_output_bytes=settings.sandbox_max_output_bytes,
        )
        self._policy = ExecApprovalPolicy()

    async def execute(  # type: ignore[override]
        self,
        code: str,
        timeout: Optional[float] = None,
        **_: object,
    ) -> ToolResult:
        """Run *code* in a child Python process and return its output.

        Args:
            code:    Python source code string. Use ``print()`` for output.
            timeout: Seconds before the child process is killed. Default 30.

        Returns:
            ToolResult with combined stdout/stderr on success, or an error
            message describing why execution failed.
        """
        effective_timeout = timeout if timeout is not None else self._default_timeout

        # --- Safety gate (ExecApprovalPolicy) ---
        approval = self._policy.evaluate(code)
        if not approval.approved:
            return ToolResult(
                output="",
                error=f"Code denied by policy: {approval.reason}",
            )
        if approval.requires_confirmation:
            return ToolResult(
                output="",
                error=(
                    f"Code requires user confirmation before execution. "
                    f"Hint: {approval.undo_hint}"
                ),
            )

        # --- Run in isolated subprocess ---
        cmd = [sys.executable, "-c", code]
        result = await self._executor.run(cmd, timeout=effective_timeout)

        if result.timed_out:
            return ToolResult(
                output="",
                error=f"Python code timed out after {effective_timeout:.0f}s",
            )
        if not result.success:
            return ToolResult(
                output=result.stdout,
                error=result.stderr or f"Exit code {result.returncode}",
            )
        return ToolResult(output=result.combined_output)
