"""L4 (remaining-work plan 2026-10-29): the event-store time filter matches same-day events.

SQLite stores ``CURRENT_TIMESTAMP`` as ``YYYY-MM-DD HH:MM:SS`` (UTC) and compares it as
text. The filter bound ``isoformat()``, whose ``T`` sorts after the stored space, so a
``start_time`` earlier the same day matched nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from weebot.infrastructure.event_store import AsyncEventStore


async def test_start_time_earlier_today_finds_the_event(tmp_path):
    store = AsyncEventStore(db_path=str(tmp_path / "events.db"))
    await store.log_event("s", "message", {})
    since = datetime.now(UTC) - timedelta(minutes=1)
    assert len(await store.query_events(session_id="s", start_time=since)) == 1


async def test_end_time_in_the_past_excludes_the_event(tmp_path):
    store = AsyncEventStore(db_path=str(tmp_path / "events.db"))
    await store.log_event("s", "message", {})
    until = datetime.now(UTC) - timedelta(minutes=1)
    assert await store.query_events(session_id="s", end_time=until) == []


async def test_an_aware_local_time_is_converted_to_utc(tmp_path):
    store = AsyncEventStore(db_path=str(tmp_path / "events.db"))
    await store.log_event("s", "message", {})
    since = (datetime.now(UTC) - timedelta(minutes=1)).astimezone(timezone(timedelta(hours=5)))
    assert len(await store.query_events(session_id="s", start_time=since)) == 1
