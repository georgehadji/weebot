"""Tests for Phase 4 Observability components.

Tests Structured Logging.
"""

import json
import pytest
from datetime import datetime, UTC


class TestStructuredLogger:
    """Test structured logging functionality."""

    def test_logger_creation(self):
        """Test logger can be created."""
        from weebot.core.structured_logger import get_logger

        logger = get_logger("test.logger")
        assert logger is not None
        assert logger.name == "test.logger"

    def test_log_record_creation(self):
        """Test log record can be created and serialized."""
        from weebot.core.structured_logger import StructuredLogRecord

        record = StructuredLogRecord(level="INFO", message="Test message", logger_name="test")

        data = record.to_dict()
        assert data["level"] == "INFO"
        assert data["message"] == "Test message"
        assert "timestamp" in data

    def test_log_record_json_serialization(self):
        """Test log record serializes to valid JSON."""
        from weebot.core.structured_logger import StructuredLogRecord

        record = StructuredLogRecord(
            level="ERROR",
            message="Error occurred",
            logger_name="test",
            error_type="ValueError",
            error_category="VALIDATION",
        )

        json_str = record.to_json()
        data = json.loads(json_str)

        assert data["level"] == "ERROR"
        assert data["error_type"] == "ValueError"
        assert data["error_category"] == "VALIDATION"

    def test_correlation_id_context(self):
        """Test correlation ID context manager."""
        from weebot.core.structured_logger import StructuredLogger, get_correlation_id

        logger = StructuredLogger("test")

        # Initially no correlation ID
        assert get_correlation_id() is None

        # Set via context manager
        with logger.correlation_id("test-cid-123"):
            assert get_correlation_id() == "test-cid-123"

        # Reset after context
        assert get_correlation_id() is None

    def test_timer_context(self):
        """Test timer context manager."""
        from weebot.core.structured_logger import StructuredLogger

        logger = StructuredLogger("test")

        # Timer should complete without error
        with logger.timer("test_operation"):
            pass  # Immediate completion

    def test_error_categorization(self):
        """Test error categorization in logs."""
        from weebot.core.structured_logger import StructuredLogger

        logger = StructuredLogger("test")

        # Verify error categories exist
        assert "CRITICAL" in StructuredLogger.ERROR_CATEGORIES
        assert "ERROR" in StructuredLogger.ERROR_CATEGORIES
        assert "WARNING" in StructuredLogger.ERROR_CATEGORIES
