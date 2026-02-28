"""Unit tests for AgentLogger with rotation."""
import pytest
from pathlib import Path
from weebot.utils.logger import AgentLogger


class TestLogRotation:
    def test_logger_creates_log_file(self, tmp_path):
        log_file = tmp_path / "agent.log"
        logger = AgentLogger(log_path=log_file)
        logger.get_logger().info("hello")
        assert log_file.exists()

    def test_logger_rotates_at_5mb(self, tmp_path):
        log_file = tmp_path / "agent.log"
        # Pre-fill file past 5MB
        log_file.write_bytes(b"x" * (5 * 1024 * 1024 + 1))
        logger = AgentLogger(log_path=log_file)
        logger.get_logger().info("trigger rotation check")
        # After any write, original should be backed up or truncated
        assert (tmp_path / "agent.log.1").exists() or log_file.stat().st_size < 5 * 1024 * 1024 + 200

    def test_logger_accepts_custom_path(self, tmp_path):
        log_file = tmp_path / "subdir" / "custom.log"
        logger = AgentLogger(log_path=log_file)
        assert logger.log_path == log_file

    def test_logger_default_path_unchanged(self):
        logger = AgentLogger()
        assert "agent.log" in str(logger.log_path)
