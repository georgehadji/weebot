"""Stress test configuration."""
import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "stress: marks stress tests (may be slow)",
    )
