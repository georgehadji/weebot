"""Unit tests for domain ports and exceptions."""
from typing import Protocol

import pytest

from weebot.domain.exceptions import (
    BudgetExceededError,
    CheckpointError,
    ProjectNotFoundError,
    SafetyError,
    TaskExecutionError,
    WeebotError,
)
from weebot.domain.ports import IModelProvider, INotifier, IRepository, ITool


class TestExceptions:
    def test_budget_exceeded_is_weebot_error(self):
        exc = BudgetExceededError("Over limit")
        assert isinstance(exc, WeebotError)

    def test_safety_error_is_weebot_error(self):
        exc = SafetyError("Dangerous operation")
        assert isinstance(exc, WeebotError)

    def test_task_execution_error_is_weebot_error(self):
        exc = TaskExecutionError("Task failed")
        assert isinstance(exc, WeebotError)

    def test_project_not_found_is_weebot_error(self):
        exc = ProjectNotFoundError("proj-123")
        assert isinstance(exc, WeebotError)

    def test_checkpoint_error_is_weebot_error(self):
        exc = CheckpointError("checkpoint failed")
        assert isinstance(exc, WeebotError)

    def test_weebot_error_message_preserved(self):
        exc = BudgetExceededError("daily limit $10 exceeded")
        assert "daily limit" in str(exc)


class TestPorts:
    def test_imodel_provider_is_protocol(self):
        assert issubclass(IModelProvider, Protocol)

    def test_irepository_is_protocol(self):
        assert issubclass(IRepository, Protocol)

    def test_inotifier_is_protocol(self):
        assert issubclass(INotifier, Protocol)

    def test_itool_is_protocol(self):
        assert issubclass(ITool, Protocol)

    def test_concrete_class_satisfies_imodel_provider(self):
        class FakeProvider:
            async def generate(self, prompt, task_type, system_prompt="",
                               temperature=0.7, max_tokens=2000):
                return "result"

            async def estimate_cost(self, prompt, task_type):
                return 0.001

        assert isinstance(FakeProvider(), IModelProvider)

    def test_concrete_class_satisfies_inotifier(self):
        class FakeNotifier:
            async def notify(self, title, message, level="info", project_id=None):
                pass

        assert isinstance(FakeNotifier(), INotifier)
