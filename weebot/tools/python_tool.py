"""PythonExecuteTool — run Python code in an isolated subprocess."""

from __future__ import annotations

from typing import ClassVar
from weebot.domain.models.output_trust import OutputTrust


from pydantic import ConfigDict, PrivateAttr

import logging

from weebot.application.ports.sandbox_port import (
    SandboxConfig,
    SandboxPort,
    SandboxType,
    network_allowed,
)
from weebot.application.services.kernel_manager import KernelManager
from weebot.config.tool_config import ToolConfig
from weebot.core.log_context import session_id_var
from weebot.core.approval import is_human_approved
from weebot.core.approval_policy import ExecApprovalPolicy
from weebot.core.bash_guard import BashGuard
from weebot.tools._results import to_tool_result
from weebot.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


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

    output_trust: ClassVar[OutputTrust] = OutputTrust.LOCAL

    name: str = "python_execute"
    description: str = (
        "Execute Python code in an isolated subprocess. "
        "stdout and stderr are captured and returned. "
        "Supports pandas, numpy, matplotlib if installed. "
        "Use print() to produce output visible to the agent. "
        "Variables persist between calls in the same session; pass reset=true to start clean "
        "or persistent=false for a one-shot run (needed for network access)."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python source code to execute"},
            "timeout": {"type": "number", "description": "Timeout in seconds (default 30)"},
            "persistent": {
                "type": "boolean",
                "description": "Keep variables between calls (default true). False = one-shot.",
            },
            "reset": {
                "type": "boolean",
                "description": "Discard the session's variables before running this code.",
            },
        },
        "required": ["code"],
    }

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _policy: ExecApprovalPolicy = PrivateAttr(default=None)
    _bash_guard: BashGuard = PrivateAttr(default=None)
    _default_timeout: float = PrivateAttr(default=30.0)
    _sandbox: SandboxPort = PrivateAttr(default=None)
    _tool_config: ToolConfig | None = PrivateAttr(default=None)
    _kernels: KernelManager | None = PrivateAttr(default=None)

    @staticmethod
    def _make_prometheus_counter():
        """Build the on_security_event callback that increments Prometheus counter."""
        try:
            from weebot.application.services.metrics_bridge import get_metrics

            _m = get_metrics()
            if _m is None:
                return None

            def _counter(risk_level):
                _m.bash_guard_events_total.labels(risk_level=risk_level.value).inc()

            return _counter
        except Exception:
            return None

    def __init__(self, sandbox: SandboxPort | None = None, kernels: KernelManager | None = None):
        """Initialise with a sandbox port instance (injected by DI).

        Args:
            sandbox: SandboxPort implementation for code execution.
                When None, resolves from the DI container.
            kernels: Keeps a Python session per agent session (H17). When None, or on a
                sandbox without kernel support, every call is one-shot, as before.
        """
        import logging as _logging

        super().__init__()
        if sandbox is None:
            # No sandbox injected — fall back to the environment default so the
            # tool is usable when constructed directly (registry, MCP, tests).
            try:
                from weebot.infrastructure.sandbox.factory import create_default_sandbox

                sandbox = create_default_sandbox()
            except Exception as exc:
                _logging.getLogger(__name__).warning(
                    "PythonExecuteTool: no SandboxPort injected and default "
                    "sandbox creation failed (%s) — python_execute will error "
                    "until a sandbox is set",
                    exc,
                )
        self._sandbox = sandbox
        self._kernels = kernels
        self._policy = ExecApprovalPolicy()
        self._bash_guard = BashGuard(on_security_event=self._make_prometheus_counter())

    def set_config(self, config: ToolConfig) -> None:
        """Inject a ToolConfig for settings."""
        self._tool_config = config
        self._default_timeout = float(config.python_timeout)

    def _kernel_session(self, persistent: bool) -> str | None:
        """The session to keep a kernel for, or None when this call runs one-shot."""
        if not persistent or self._kernels is None:
            return None
        if getattr(self._sandbox, "sandbox_type", None) is not SandboxType.NATIVE_WINDOWS:
            return None
        if network_allowed(SandboxConfig()):
            return None  # this call was cleared for the network; a running kernel cannot be
        return session_id_var.get() or None

    async def _execute_in_kernel(
        self, session_id: str, code: str, timeout: float, reset: bool
    ) -> ToolResult | None:
        """The result of running *code* in the session's kernel, or None to run it one-shot."""
        try:
            run = await self._kernels.run(session_id, code, timeout, reset=reset)
        except RuntimeError as exc:
            logger.warning("python_execute: no kernel (%s); running one-shot", exc)
            return None
        result = run.result
        note = (
            f"(Python session restarted, earlier variables are gone: {run.notice})\n"
            if run.notice
            else ""
        )
        if result.died:
            return ToolResult(output="", error=result.error)
        if result.error:
            return ToolResult(output=note + result.stdout, error=result.error)
        return ToolResult(output=note + result.stdout)

    async def execute(  # type: ignore[override]
        self,
        code: str,
        timeout: float | None = None,
        persistent: bool = True,
        reset: bool = False,
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
        if self._sandbox is None:
            return ToolResult(
                output="",
                error="python_execute is unavailable: no SandboxPort was injected at construction.",
            )

        effective_timeout = timeout if timeout is not None else self._default_timeout
        # Clamp timeout: floor at 1.0, cap at max_tool_timeout or 300.0
        try:
            effective_timeout = float(effective_timeout)
        except (TypeError, ValueError):
            effective_timeout = self._default_timeout
        effective_timeout = max(1.0, effective_timeout)
        _max_timeout = 300.0
        if self._tool_config and self._tool_config.max_tool_timeout:
            _max_timeout = float(self._tool_config.max_tool_timeout)
        effective_timeout = min(effective_timeout, _max_timeout)

        # --- Defense-in-depth: BashGuard catches shell injection ---
        from weebot.core.bash_guard import RiskLevel as BashRiskLevel

        risk, checks = self._bash_guard.evaluate(code)
        if risk == BashRiskLevel.BLOCKED:
            reasons = [c.description for c in checks if c.description]
            return ToolResult(output="", error=f"Code blocked by BashGuard: {'; '.join(reasons)}")

        # --- Safety gate (ExecApprovalPolicy) ---
        from weebot.core.shell_segments import SegmentSyntax

        # Lines of code are not separate commands (R01 splits shell text on newlines).
        approval = self._policy.evaluate(code, syntax=SegmentSyntax.PYTHON)
        if not approval.approved:
            return ToolResult(output="", error=f"Code denied by policy: {approval.reason}")
        if approval.requires_confirmation and not is_human_approved(self.name):
            hint = _contextual_hint(code, approval.undo_hint)
            return ToolResult(
                output="",
                error=(f"Code requires user confirmation before execution. " f"Hint: {hint}"),
            )

        # --- A kernel that keeps this session's variables, when there is one (H17) ---
        kernel_session = self._kernel_session(bool(persistent))
        if kernel_session is not None:
            kernel_result = await self._execute_in_kernel(
                kernel_session, code, effective_timeout, bool(reset)
            )
            if kernel_result is not None:
                return kernel_result

        # --- Run in isolated subprocess (always via SandboxPort) ---
        result = await self._sandbox.execute_python(
            code=code, timeout=effective_timeout, memory_limit_mb=256
        )

        return to_tool_result(result, timeout=effective_timeout, label="Python code")
