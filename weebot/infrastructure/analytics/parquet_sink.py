"""ParquetActivitySink — buffers ActivityEvents and flushes to Parquet files.

Implements :class:`~weebot.application.ports.analytics_port.AnalyticsSinkPort`.
Partitions output by project_id and date so queries over DuckDB/Polars are fast.

Gracefully degrades to a no-op when ``pyarrow`` is not installed.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from weebot.application.ports.analytics_port import AnalyticsSinkPort

if TYPE_CHECKING:
    from weebot.core.activity_stream import ActivityEvent

_log = logging.getLogger(__name__)

_PARQUET_AVAILABLE = False
try:
    import pyarrow as pa
    import pyarrow.parquet as pq
    _PARQUET_AVAILABLE = True
except ImportError:
    pass


class ParquetActivitySink(AnalyticsSinkPort):
    """Buffers events in-memory and flushes to partitioned Parquet files.

    Output layout::

        {output_dir}/{project_id}/date={YYYY-MM-DD}/events.parquet

    Configured via:
    - ``WEEBOT_ANALYTICS_DIR`` — output directory (default: ./analytics)
    - ``WEEBOT_ANALYTICS_FLUSH_INTERVAL`` — flush interval in seconds (default: 300)

    When ``pyarrow`` is not installed, the sink is a no-op.
    """

    _SCHEMA = None  # lazily built from pyarrow

    def __init__(
        self,
        output_dir: str | None = None,
        flush_interval_s: int = 300,
    ) -> None:
        self._dir = Path(
            output_dir or os.getenv("WEEBOT_ANALYTICS_DIR", "./analytics")
        )
        self._flush_interval = int(
            os.getenv("WEEBOT_ANALYTICS_FLUSH_INTERVAL", str(flush_interval_s))
        )
        self._buffer: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None

        if _PARQUET_AVAILABLE:
            self._setup_schema()

    def _setup_schema(self) -> None:
        """Define the Parquet schema (lazy, only if pyarrow is available)."""
        import pyarrow as pa
        ParquetActivitySink._SCHEMA = pa.schema([
            ("project_id", pa.string()),
            ("kind", pa.string()),
            ("message", pa.string()),
            ("timestamp", pa.timestamp("us", tz="UTC")),
        ])

    # ── AnalyticsSinkPort implementation ─────────────────────────────

    async def push(self, event: "ActivityEvent") -> None:
        """Buffer an event for later flush."""
        if not _PARQUET_AVAILABLE:
            return

        row = {
            "project_id": event.project_id,
            "kind": event.kind,
            "message": event.message,
            "timestamp": event.timestamp,
        }
        async with self._lock:
            self._buffer.append(row)

        # Start periodic flush on first event
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.ensure_future(self._periodic_flush())

    async def flush(self) -> None:
        """Flush all buffered events to Parquet immediately."""
        if not _PARQUET_AVAILABLE:
            return

        async with self._lock:
            if not self._buffer:
                return
            rows = self._buffer[:]
            self._buffer.clear()

        await self._write_batch(rows)

    async def _periodic_flush(self) -> None:
        """Flush periodically at the configured interval."""
        try:
            while True:
                await asyncio.sleep(self._flush_interval)
                await self.flush()
        except asyncio.CancelledError:
            pass  # Normal shutdown — remaining events flushed in close()

    async def close(self) -> None:
        """Cancel background flush task and flush remaining buffered events."""
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self.flush()

    async def __aenter__(self) -> "ParquetActivitySink":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def _write_batch(self, rows: list[dict[str, Any]]) -> None:
        """Write a batch of rows to partitioned Parquet files."""
        import pyarrow as pa
        import pyarrow.parquet as pq

        if not rows:
            return

        try:
            table = pa.Table.from_pylist(rows, schema=self._SCHEMA)

            # Partition by project_id and date
            for row in rows:
                pid = row["project_id"]
                ts = row["timestamp"]
                if isinstance(ts, datetime):
                    date_str = ts.strftime("%Y-%m-%d")
                else:
                    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

                part_dir = self._dir / pid / f"date={date_str}"
                part_dir.mkdir(parents=True, exist_ok=True)

                out_path = part_dir / "events.parquet"
                single = pa.Table.from_pylist([row], schema=self._SCHEMA)

                if out_path.exists():
                    existing = pq.read_table(str(out_path))
                    combined = pa.concat_tables([existing, single])
                    pq.write_table(combined, str(out_path))
                else:
                    pq.write_table(single, str(out_path))

            _log.debug("Flushed %d events to Parquet under %s", len(rows), self._dir)
        except Exception:
            _log.warning("Parquet write failed — swallowing", exc_info=True)
