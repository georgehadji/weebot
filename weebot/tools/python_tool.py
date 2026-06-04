"""PythonExecuteTool — run Python code in an isolated subprocess."""
from __future__ import annotations

import sys
from typing import Optional

from pydantic import ConfigDict, PrivateAttr

from weebot.application.ports.sandbox_port import SandboxPort, SandboxResult
from weebot.config.tool_config import ToolConfig
from weebot.core.approval_policy import ExecApprovalPolicy
from weebot.core.bash_guard import BashGuard
from weebot.infrastructure.sandbox.native_windows import NativeWindowsSandbox
from weebot.tools.base import BaseTool, ToolResult


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

    _policy: ExecApprovalPolicy = PrivateAttr(default=None)
    _bash_guard: BashGuard = PrivateAttr(default=None)
    _default_timeout: float = PrivateAttr(default=30.0)
    _sandbox: SandboxPort = PrivateAttr(default=None)
    _tool_config: Optional[ToolConfig] = PrivateAttr(default=None)

    def model_post_init(self, __context: object) -> None:
        """Initialise the sandbox and the approval policy.

        Timeout defaults to 30.0 unless set_config() is called.
        """
        self._sandbox = NativeWindowsSandbox()
        self._policy = ExecApprovalPolicy()
        self._bash_guard = BashGuard()

    def set_config(self, config: ToolConfig) -> None:
        """Inject a ToolConfig for settings."""
        self._tool_config = config
        self._default_timeout = float(config.python_timeout)

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

        # --- Defense-in-depth: BashGuard catches shell injection ---
        from weebot.core.bash_guard import RiskLevel as BashRiskLevel
        risk, checks = self._bash_guard.evaluate(code)
        if risk == BashRiskLevel.BLOCKED:
            reasons = [c.description for c in checks if c.description]
            return ToolResult(
                output="",
                error=f"Code blocked by BashGuard: {'; '.join(reasons)}",
            )

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

        # --- Run in isolated subprocess (always via SandboxPort) ---
        result = await self._sandbox.execute_python(
            code=code,
            timeout=effective_timeout,
        )

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
