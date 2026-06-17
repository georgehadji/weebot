"""Unit tests for AuditLog (hash-chained append-only log)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from weebot.infrastructure.observability.audit_log import AuditLog


class TestAuditLog:
    """AuditLog recording, querying, and integrity verification."""

    def setup_method(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.log = AuditLog(db_path=self._tmp.name)

    def teardown_method(self):
        # Force-close all connections by replacing _get_conn with a closed state
        import sqlite3
        try:
            # Access internal via a final dummy connect that we can close
            conn = sqlite3.connect(str(self._tmp.name))
            conn.close()
        except Exception:
            pass
        try:
            Path(self._tmp.name).unlink(missing_ok=True)
        except PermissionError:
            # Windows may still hold a lock; schedule for next boot
            pass

    @pytest.mark.asyncio
    async def test_record_and_count(self):
        seq = await self.log.record("tool_call", {"tool": "bash", "command": "ls"})
        assert seq == 1
        assert await self.log.count() == 1

    @pytest.mark.asyncio
    async def test_multiple_entries(self):
        await self.log.record("tool_call", {"tool": "bash"})
        await self.log.record("approval", {"approved": True})
        await self.log.record("file_write", {"path": "/tmp/test.txt"})
        assert await self.log.count() == 3

    @pytest.mark.asyncio
    async def test_query_by_type(self):
        await self.log.record("tool_call", {"tool": "bash"})
        await self.log.record("approval", {"approved": True})
        await self.log.record("tool_call", {"tool": "python"})

        tool_calls = await self.log.query(event_type="tool_call")
        assert len(tool_calls) == 2
        for entry in tool_calls:
            assert entry["event_type"] == "tool_call"

    @pytest.mark.asyncio
    async def test_query_all(self):
        await self.log.record("tool_call", {"tool": "bash"})
        await self.log.record("approval", {"approved": True})
        entries = await self.log.query()
        assert len(entries) == 2

    @pytest.mark.asyncio
    async def test_query_limit(self):
        for i in range(5):
            await self.log.record("tool_call", {"i": i})
        entries = await self.log.query(limit=3)
        assert len(entries) == 3

    @pytest.mark.asyncio
    async def test_integrity_passes(self):
        await self.log.record("tool_call", {"tool": "bash"})
        await self.log.record("approval", {"approved": True})
        corrupted = await self.log.verify_integrity()
        assert corrupted == []

    @pytest.mark.asyncio
    async def test_integrity_detects_tamper(self):
        await self.log.record("tool_call", {"tool": "bash"})
        await self.log.record("approval", {"approved": True})

        # Manually tamper with the database
        import sqlite3
        conn = sqlite3.connect(self._tmp.name)
        conn.execute("UPDATE audit_log SET details = '{}' WHERE sequence = 1")
        conn.commit()
        conn.close()

        corrupted = await self.log.verify_integrity()
        assert len(corrupted) >= 1

    @pytest.mark.asyncio
    async def test_hash_chain_linking(self):
        """Each entry's previous_hash should match the previous entry's hash."""
        await self.log.record("first", {"data": 1})
        await self.log.record("second", {"data": 2})
        await self.log.record("third", {"data": 3})

        entries = await self.log.query()
        # Entries are returned in DESC order, so reverse
        entries.reverse()

        assert entries[0]["previous_hash"] == ""
        for i in range(1, len(entries)):
            assert entries[i]["previous_hash"] == entries[i - 1]["hash"]

    @pytest.mark.asyncio
    async def test_empty_log(self):
        assert await self.log.count() == 0
        entries = await self.log.query()
        assert entries == []
        corrupted = await self.log.verify_integrity()
        assert corrupted == []
