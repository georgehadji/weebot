"""Unit tests for SafetyChecker critical operation detection."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from weebot.core.safety import SafetyChecker


@pytest.fixture
def checker():
    """SafetyChecker with mocked LLM to avoid real API calls."""
    with patch("weebot.core.safety.ChatOpenAI") as mock_cls:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(
            content='{"confirmation_required": "yes", "plan_b": "backup first"}'
        ))
        mock_cls.return_value = mock_llm
        yield SafetyChecker()


class TestIsCriticalOperation:
    def test_delete_command_on_powershell_is_critical(self, checker):
        assert checker.is_critical_operation("delete all temp files", "powershell_executor")

    def test_remove_command_on_powershell_is_critical(self, checker):
        assert checker.is_critical_operation("Remove-Item old_backup", "powershell_executor")

    def test_kill_command_on_powershell_is_critical(self, checker):
        assert checker.is_critical_operation("kill the process", "powershell_executor")

    def test_rm_command_on_powershell_is_critical(self, checker):
        assert checker.is_critical_operation("rm workspace folder", "powershell_executor")

    def test_format_command_on_powershell_is_critical(self, checker):
        assert checker.is_critical_operation("format volume", "powershell_executor")

    def test_stop_process_on_powershell_is_critical(self, checker):
        assert checker.is_critical_operation("stop-process browser", "powershell_executor")

    def test_non_critical_task_on_powershell_not_critical(self, checker):
        assert not checker.is_critical_operation("list files in workspace", "powershell_executor")

    def test_delete_on_browser_tool_not_critical(self, checker):
        # Only powershell_executor triggers safety checks
        assert not checker.is_critical_operation("delete cookie", "browser_navigator")

    def test_case_insensitive_keyword_matching(self, checker):
        assert checker.is_critical_operation("DELETE all logs", "powershell_executor")
        assert checker.is_critical_operation("Kill process", "powershell_executor")


class TestGeneratePlanB:
    @pytest.mark.asyncio
    async def test_returns_dict_with_simulation_result(self, checker):
        result = await checker.generate_plan_b("delete all files", "high risk context")
        assert isinstance(result, dict)
        assert "simulation_result" in result

    @pytest.mark.asyncio
    async def test_returns_original_action(self, checker):
        action = "Remove-Item -Recurse workspace"
        result = await checker.generate_plan_b(action, "cleanup task")
        assert result["original_action"] == action

    @pytest.mark.asyncio
    async def test_proceed_flag_requires_confirmation_for_destructive(self, checker):
        # Remove-Item matches ExecApprovalPolicy ALWAYS_ASK → proceed = False
        result = await checker.generate_plan_b("Remove-Item old_logs", "maintenance")
        assert result["proceed"] is False

    @pytest.mark.asyncio
    async def test_proceed_flag_true_for_safe_commands(self, checker):
        result = await checker.generate_plan_b("Get-ChildItem C:\\logs", "inspection")
        assert result["proceed"] is True
