"""BashTool — execute shell commands via PowerShell (primary) or WSL2 (optional)."""
from __future__ import annotations

import subprocess
from typing import Optional

from pydantic import ConfigDict, PrivateAttr

from weebot.core.approval_policy import ExecApprovalPolicy
from weebot.sandbox.executor import SandboxedExecutor
from weebot.tools.base import BaseTool, ToolResult


def _wsl_available() -> bool:
    """Return True if WSL2 is installed and responsive on this machine."""
    try:
        r = subprocess.run(
            ["wsl", "--status"],
            capture_output=True,
            timeout=3,
        )
        return r.returncode == 0
    except Exception:
        return False


class BashTool(BaseTool):
    """Execute a shell command via PowerShell (Windows) or WSL2 bash.

    Primary shell is PowerShell so the tool works on plain Windows 11 without
    WSL.  Pass ``use_wsl=True`` to route through WSL2 bash instead (if available).

    Safety gate: every command is evaluated by ExecApprovalPolicy before
    execution.  Commands that match a DENY rule return an error immediately;
    commands that match an ALWAYS_ASK rule also return an error (the agent
    should surface the undo_hint to the user before retrying).
    """

    name: str = "bash"
    description: str = (
        "Execute a shell command. "
        "Uses PowerShell on Windows (primary) or WSL2 bash (if use_wsl=True). "
        "Dangerous commands (format, rm -rf) are blocked by policy. "
        "Destructive commands (rm, del, kill) require user confirmation."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute",
            },
            "timeout": {
                "type": "number",
                "description": "Timeout in seconds (default 30)",
            },
            "working_dir": {
                "type": "string",
                "description": "Working directory for the command (optional)",
            },
            "use_wsl": {
                "type": "boolean",
                "description": "Route through WSL2 bash instead of PowerShell (default false)",
            },
        },
        "required": ["command"],
    }

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _executor: SandboxedExecutor = PrivateAttr(default=None)
    _policy: ExecApprovalPolicy = PrivateAttr(default=None)
    _default_timeout: float = PrivateAttr(default=30.0)

    def model_post_init(self, __context: object) -> None:
        """Initialise the sandboxed executor and the approval policy."""
        from weebot.config.settings import WeebotSettings

        settings = WeebotSettings()
        self._default_timeout = float(settings.bash_timeout)
        self._executor = SandboxedExecutor(
            max_output_bytes=settings.sandbox_max_output_bytes,
        )
        self._policy = ExecApprovalPolicy()

    async def execute(  # type: ignore[override]
        self,
        command: str,
        timeout: Optional[float] = None,
        working_dir: Optional[str] = None,
        use_wsl: bool = False,
        **_: object,
    ) -> ToolResult:
        """Execute *command* in a sandboxed subprocess.

        Args:
            command:     Shell command string.
            timeout:     Seconds before the subprocess is killed. Default 30.
            working_dir: Optional working directory. Default: inherited.
            use_wsl:     If True and WSL2 is available, use ``wsl bash -c``.

        Returns:
            ToolResult with combined output on success, or an error message.
        """
        effective_timeout = timeout if timeout is not None else self._default_timeout

        # --- Safety gate (ExecApprovalPolicy) ---
        approval = self._policy.evaluate(command)
        if not approval.approved:
            return ToolResult(
                output="",
                error=f"Command denied by policy: {approval.reason}",
            )
        if approval.requires_confirmation:
            return ToolResult(
                output="",
                error=(
                    f"Command requires user confirmation before execution. "
                    f"Hint: {approval.undo_hint}"
                ),
            )

        # --- Build the subprocess command list ---
        if use_wsl and _wsl_available():
            cmd = ["wsl", "bash", "-c", command]
        else:
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]

        # --- Run in sandbox ---
        result = await self._executor.run(cmd, timeout=effective_timeout, cwd=working_dir)

        if result.timed_out:
            return ToolResult(
                output="",
                error=f"Command timed out after {effective_timeout:.0f}s",
            )
        if not result.success:
            return ToolResult(
                output=result.stdout,
                error=result.stderr or f"Exit code {result.returncode}",
            )
        return ToolResult(output=result.combined_output)
