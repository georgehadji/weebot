"""PythonExecuteTool — run Python code in an isolated subprocess."""
from __future__ import annotations

import sys
from typing import Optional

from pydantic import ConfigDict, PrivateAttr

from weebot.application.ports.sandbox_port import SandboxPort, SandboxResult
from weebot.config.tool_config import ToolConfig
from weebot.core.approval_policy import ExecApprovalPolicy
from weebot.core.bash_guard import BashGuard
from weebot.tools.base import BaseTool, ToolResult


def _contextual_hint(code: str, base_hint: str) -> str:
    """Derive a contextual message from the code being evaluated."""
    code_lower = code.lower()
    if "import sys" in code_lower or "sys.argv" in code_lower:
        return f"{base_hint} (code uses sys module — review argv/path access)"
    if "open(" in code_lower and ("'w'" in code or '"w"' in code):
        return f"{base_hint} (code opens files for writing)"
    if "shutil.rmtree" in code_lower or "os.remove" in code_lower:
        return f"{base_hint} (code may delete files — verify target paths first)"
    return base_hint


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

    @staticmethod
    def _make_prometheus_counter():
        """Build the on_security_event callback that increments Prometheus counter."""
        try:
            from weebot.infrastructure.observability import metrics as _m
            def _counter(risk_level):
                _m.bash_guard_events_total.labels(risk_level=risk_level.value).inc()
            return _counter
        except Exception:
            return None

    def __init__(self, sandbox: Optional[SandboxPort] = None):
        """Initialise with a sandbox port instance (injected by DI).

        Args:
            sandbox: SandboxPort implementation for code execution.
                When None, resolves from the DI container.
        """
        super().__init__()
        if sandbox is None:
            # Try resolving from DI container as fallback
            try:
                from weebot.application.di import Container
                from weebot.application.ports.sandbox_port import SandboxPort as _SP
                _c = Container()
                sandbox = _c._maybe_get(_SP)
            except Exception:
                pass
        if sandbox is None:
            # Final fallback: use native sandbox
            try:
                from weebot.infrastructure.sandbox.factory import create_sandbox
                sandbox = create_sandbox()
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "PythonExecuteTool: no SandboxPort available — "
                    "python_execute will be unavailable"
                )
        self._sandbox = sandbox
        self._policy = ExecApprovalPolicy()
        self._bash_guard = BashGuard(
            on_security_event=self._make_prometheus_counter(),
        )

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
            hint = _contextual_hint(code, approval.undo_hint)
            return ToolResult(
                output="",
                error=(
                    f"Code requires user confirmation before execution. "
                    f"Hint: {hint}"
                ),
            )

        # --- Run in isolated subprocess (always via SandboxPort) ---
        result = await self._sandbox.execute_python(
            code=code,
            timeout=effective_timeout,
            memory_limit_mb=256,
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
