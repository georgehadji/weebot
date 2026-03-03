"""BashTool — execute shell commands via PowerShell (primary) or WSL2 (optional)."""
from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING, Optional

from pydantic import ConfigDict, PrivateAttr

from weebot.core.approval_policy import ExecApprovalPolicy
from weebot.sandbox.executor import SandboxedExecutor
from weebot.tools.base import BaseTool, ToolResult

# NEW: Multi-layer security analyzer
from weebot.tools.bash_security import (
    CommandSecurityAnalyzer, 
    RiskLevel,
    get_security_analyzer
)

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

    Safety gates (in order):
    1. Multi-layer security analyzer (NEW: defense in depth)
    2. ExecApprovalPolicy (legacy rule-based approval)
    3. Sandboxed execution with timeout

    Security Architecture:
    - Layer 1: Pattern matching for known attack vectors
    - Layer 2: Behavioral analysis (download+execute detection)
    - Layer 3: Entropy analysis (encoded payload detection)
    - Layer 4: Semantic validation (command structure)
    """

    name: str = "bash"
    description: str = (
        "Execute a shell command. "
        "Uses PowerShell on Windows (primary) or WSL2 bash (if use_wsl=True). "
        "Dangerous commands are blocked by multi-layer security analysis. "
        "Destructive commands require user confirmation."
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
            "security_override": {
                "type": "string",
                "description": "Optional: security override token for dangerous commands (requires admin)",
            },
        },
        "required": ["command"],
    }

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _executor: SandboxedExecutor = PrivateAttr(default=None)
    _policy: ExecApprovalPolicy = PrivateAttr(default=None)
    _security_analyzer: CommandSecurityAnalyzer = PrivateAttr(default=None)
    _default_timeout: float = PrivateAttr(default=30.0)
    _security_enabled: bool = PrivateAttr(default=True)

    def model_post_init(self, __context: object) -> None:
        """Initialise the sandboxed executor, approval policy, and security analyzer."""
        settings = _get_settings()
        self._default_timeout = float(settings.bash_timeout)
        self._executor = SandboxedExecutor(
            max_output_bytes=settings.sandbox_max_output_bytes,
        )
        self._policy = ExecApprovalPolicy()
        
        # NEW: Initialize multi-layer security analyzer
        try:
            self._security_analyzer = get_security_analyzer()
            self._security_enabled = True
        except Exception as e:
            # FALLBACK: If security analyzer fails to initialize, 
            # fall back to legacy mode but log the issue
            import logging
            logging.getLogger(__name__).warning(
                f"Security analyzer initialization failed: {e}. "
                "Falling back to legacy pattern matching only."
            )
            self._security_analyzer = None
            self._security_enabled = False

    # LEGACY: Patterns for detecting encoded/obfuscated commands (fallback)
    _ENCODED_COMMAND_PATTERNS = [
        r'base64\s*-d.*\|',  # base64 decode pipe
        r'base64\s*--decode.*\|',
        r'eval\s*\$\(',  # eval with command substitution
        r'eval\s*`',  # eval with backticks
        r'`.*base64.*`',  # backticks with base64
        r'\$\(.*base64.*\)',  # command substitution with base64
        r'echo\s+[A-Za-z0-9+/]{40,}.*\|',  # echo base64 to pipe
        r'\b(echo|printf)\s+.*\|\s*(bash|sh|zsh)',  # piping encoded content to shell
        r'<\(.*\)',  # process substitution
    ]
    
    def _legacy_validate_no_encoded_commands(self, command: str) -> tuple[bool, str]:
        """
        LEGACY FALLBACK: Check for encoded/obfuscated bash commands.
        
        This method is used when the multi-layer security analyzer
        fails to initialize or is disabled.
        
        Returns:
            (is_valid, error_message)
        """
        # Check for encoded command patterns
        for pattern in self._ENCODED_COMMAND_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return False, (
                    f"Security Error: Command contains encoded/obfuscated content "
                    f"which is not allowed for security reasons. "
                    f"Use plain, readable commands only."
                )
        
        # Check for suspicious base64-like strings
        base64_pattern = r'[A-Za-z0-9+/]{100,}={0,2}'
        matches = re.findall(base64_pattern, command)
        for match in matches:
            # Try to decode and check for shell commands
            try:
                import base64
                # Try both standard and urlsafe base64
                for decoder in [base64.b64decode, base64.urlsafe_b64decode]:
                    try:
                        decoded = decoder(match).decode('utf-8', errors='ignore')
                        shell_keywords = ['bash', 'sh', 'cmd', 'powershell', 'eval', 'exec', 'rm -rf', 'format']
                        if any(keyword in decoded.lower() for keyword in shell_keywords):
                            return False, (
                                "Security Error: Suspicious encoded shell command detected. "
                                "Use plain text commands only."
                            )
                    except Exception:
                        continue
            except Exception:
                pass
        
        return True, ""

    def _validate_security(self, command: str, security_override: Optional[str] = None) -> tuple[bool, str]:
        """
        Multi-layer security validation with fallback.
        
        Args:
            command: Shell command to validate
            security_override: Optional override token (requires admin)
            
        Returns:
            (is_valid, error_message)
        """
        # Check if security analyzer is available
        if self._security_enabled and self._security_analyzer:
            try:
                assessment = self._security_analyzer.analyze(command)
                
                if assessment.risk_level == RiskLevel.DANGEROUS:
                    # Check for override token (admin only)
                    if security_override and self._verify_override_token(command, security_override):
                        import logging
                        logging.getLogger(__name__).warning(
                            f"Security override used for dangerous command: {command[:50]}..."
                        )
                        return True, ""
                    
                    return False, (
                        f"Security Error: {assessment.reason}. "
                        f"Layer {assessment.layer_triggered} triggered. "
                        f"This command pattern is blocked for security. "
                        f"Details: {assessment.details}"
                    )
                
                elif assessment.risk_level == RiskLevel.SUSPICIOUS:
                    # Suspicious commands require explicit confirmation
                    # This is handled by the approval policy below
                    import logging
                    logging.getLogger(__name__).info(
                        f"Suspicious command detected: {assessment.reason}"
                    )
                
                return True, ""
                
            except Exception as e:
                # If security analysis fails, fall back to legacy validation
                import logging
                logging.getLogger(__name__).error(
                    f"Security analysis failed: {e}. Falling back to legacy validation."
                )
                return self._legacy_validate_no_encoded_commands(command)
        else:
            # FALLBACK: Use legacy validation
            return self._legacy_validate_no_encoded_commands(command)
    
    def _verify_override_token(self, command: str, token: str) -> bool:
        """
        Verify security override token.
        
        NOTE: This is a placeholder. In production, implement:
        - HMAC verification
        - Token expiration checking
        - Audit logging
        - Admin permission verification
        """
        # PLACEHOLDER: Always reject in default implementation
        # Subclasses can override with proper implementation
        return False

    async def execute(  # type: ignore[override]
        self,
        command: str,
        timeout: Optional[float] = None,
        working_dir: Optional[str] = None,
        use_wsl: bool = False,
        security_override: Optional[str] = None,
        **_: object,
    ) -> ToolResult:
        """Execute *command* in a sandboxed subprocess.

        Args:
            command:     Shell command string.
            timeout:     Seconds before the subprocess is killed. Default 30.
            working_dir: Optional working directory. Default: inherited.
            use_wsl:     If True and WSL2 is available, use ``wsl bash -c``.
            security_override: Optional admin override token for blocked commands.

        Returns:
            ToolResult with combined output on success, or an error message.
        """
        effective_timeout = timeout if timeout is not None else self._default_timeout

        # --- Security check: multi-layer analysis (NEW) ---
        is_valid, error_msg = self._validate_security(command, security_override)
        if not is_valid:
            return ToolResult(output="", error=error_msg)

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
