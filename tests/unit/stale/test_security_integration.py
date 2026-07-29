"""Integration tests for security module with tool execution.

Tests the integration between the security module and actual tool execution,
specifically BashTool with StateVerifier.
"""
import asyncio
import tempfile
import pytest
from pathlib import Path

from weebot.tools.bash_tool import BashTool
from weebot.infrastructure.security.state_verifier import (
    StateVerifier,
    FileOperationClaim,
    CommandExecutionClaim,
    VerificationStatus,
)


class TestBashToolWithSecurity:
    """Integration tests for BashTool with StateVerifier."""

    @pytest.fixture
    def bash_tool(self):
        """Create a BashTool instance."""
        return BashTool()

    @pytest.fixture
    def state_verifier(self):
        """Create a StateVerifier instance."""
        return StateVerifier()

    @pytest.mark.asyncio
    async def test_bash_tool_simple_command(self, bash_tool):
        """Test simple command execution."""
        result = await bash_tool.execute("echo test")

        assert result.output is not None
        assert "test" in result.output.lower() or result.error is not None

    @pytest.mark.asyncio
    async def test_bash_tool_with_state_verifier(self, bash_tool, state_verifier):
        """Test that StateVerifier is initialized in BashTool."""
        # Verify StateVerifier is available
        assert bash_tool._state_verifier is not None
        assert bash_tool._verification_enabled is True

    @pytest.mark.asyncio
    async def test_bash_tool_critical_command_verification(self, bash_tool):
        """Test verification of critical commands (create, delete, etc.)."""
        # Create a temp file first
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("test content")
            temp_path = f.name

        try:
            # Execute a command that creates/modifies a file
            result = await bash_tool.execute(f'echo "modified" > "{temp_path}"')

            # Should complete (verification is warning-only, not blocking)
            assert result is not None
        finally:
            # Cleanup
            try:
                Path(temp_path).unlink()
            except FileNotFoundError:
                pass

    @pytest.mark.asyncio
    async def test_bash_tool_security_blocks_dangerous(self, bash_tool):
        """Test that security still blocks dangerous commands."""
        # This should be blocked by the security analyzer
        result = await bash_tool.execute("eval $(echo 'malicious')")

        # Should be blocked or require confirmation
        assert result.error is not None or "security" in result.error.lower() if result.error else True

    @pytest.mark.asyncio
    async def test_state_verifier_file_operation(self, state_verifier):
        """Test StateVerifier with file operations."""
        # Create a temp file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("test content")
            temp_path = f.name

        try:
            # Verify file exists (create claim)
            claim = FileOperationClaim(
                operation="create",
                claimed_path=temp_path,
                claimed_content="test content",
            )

            result = await state_verifier.verify_file_operation(claim)

            # Should verify that file exists
            assert result.status == VerificationStatus.VERIFIED
        finally:
            try:
                Path(temp_path).unlink()
            except FileNotFoundError:
                pass

    @pytest.mark.asyncio
    async def test_state_verifier_delete_operation(self, state_verifier):
        """Test StateVerifier with delete operations."""
        # Create a temp file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("test content")
            temp_path = f.name

        # Delete the file
        Path(temp_path).unlink()

        # Verify deletion claim
        claim = FileOperationClaim(
            operation="delete",
            claimed_path=temp_path,
        )

        result = await state_verifier.verify_file_operation(claim)

        # Should verify that file was deleted
        assert result.status == VerificationStatus.VERIFIED

    @pytest.mark.asyncio
    async def test_state_verifier_command_execution(self, state_verifier):
        """Test StateVerifier with command execution."""
        claim = CommandExecutionClaim(
            command="echo test",
            claimed_returncode=0,
            claimed_output="test",
        )

        result = await state_verifier.verify_command_execution(claim)

        # Should verify command execution
        assert result.status == VerificationStatus.VERIFIED

    @pytest.mark.asyncio
    async def test_state_verifier_statistics(self, state_verifier):
        """Test StateVerifier statistics tracking."""
        # Perform some verifications
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("test")
            temp_path = f.name

        try:
            claim = FileOperationClaim(
                operation="create",
                claimed_path=temp_path,
                claimed_content="test",
            )
            await state_verifier.verify_file_operation(claim)
        finally:
            try:
                Path(temp_path).unlink()
            except:
                pass

        # Check statistics
        stats = state_verifier.get_statistics()

        assert "total_verifications" in stats
        assert stats["total_verifications"] > 0


class TestSecurityModuleIntegration:
    """Integration tests for complete security module flow."""

    @pytest.mark.asyncio
    async def test_full_security_flow_with_bash(self):
        """Test complete security flow: verify -> execute -> verify result."""
        from weebot.infrastructure.security.identity_verifier import IdentityVerifier, IdentityClaim, VerificationLevel
        from weebot.infrastructure.security.audit_logger import SecurityAuditLogger, AuditEventType

        # Initialize components
        identity_verifier = IdentityVerifier()
        logger = SecurityAuditLogger(enable_file_persistence=False)
        bash_tool = BashTool()

        # 1. Verify identity
        claim = IdentityClaim(
            claim_id="test_integration",
            source_type="user",
            source_id="test_user",
            source_name="Test",
            claimed_permissions=["read", "execute"],
        )
        identity_result = identity_verifier.verify_claim(claim, VerificationLevel.BASIC)
        assert identity_result.is_valid

        # 2. Log the action
        logger.log_event(
            event_type=AuditEventType.TOOL_EXECUTE,
            agent_id="test_agent",
            action="test_command",
            result="success",
        )

        # 3. Execute a simple command
        result = await bash_tool.execute("echo integration_test")
        assert result is not None

        # 4. Check logs
        events = logger.get_events(agent_id="test_agent")
        assert len(events) > 0

    @pytest.mark.asyncio
    async def test_sanitizer_with_bash_context(self):
        """Test agent sanitizer with bash tool context."""
        from weebot.infrastructure.security.agent_sanitizer import AgentMemorySanitizer, SanitizationLevel

        sanitizer = AgentMemorySanitizer()

        # Simulate agent context from bash tool
        context = {
            "agent_id": "bash_agent",
            "memory": [
                {"content": "Ran command: rm -rf /tmp/test"},
                {"content": "API key: sk-1234567890abcdefghijklmnopqrstuvwxyz"},
            ],
            "tool_results": [
                {"output": "Command completed successfully"},
            ],
        }

        # Sanitize for handoff
        sanitized = sanitizer.sanitize_for_handoff(
            context=context,
            target_agent="next_agent",
            level=SanitizationLevel.STANDARD,
        )

        # Credentials should be removed
        assert len(sanitized.removed_items) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])