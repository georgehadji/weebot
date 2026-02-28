"""Unit tests for ActivityStream."""
import pytest
from datetime import datetime
from weebot.activity_stream import ActivityStream, ActivityEvent


class TestActivityStream:
    def test_starts_empty(self):
        stream = ActivityStream()
        assert stream.recent() == []

    def test_push_adds_event(self):
        stream = ActivityStream()
        stream.push("proj-1", "job", "Started analysis")
        assert len(stream.recent()) == 1

    def test_recent_returns_newest_first(self):
        stream = ActivityStream()
        stream.push("p", "job", "first")
        stream.push("p", "tool", "second")
        events = stream.recent()
        assert events[0].message == "second"

    def test_recent_n_limits_results(self):
        stream = ActivityStream()
        for i in range(10):
            stream.push("p", "job", f"event {i}")
        assert len(stream.recent(n=3)) == 3

    def test_overflow_drops_oldest(self):
        stream = ActivityStream(max_size=5)
        for i in range(7):
            stream.push("p", "job", f"event {i}")
        events = stream.recent()
        assert len(events) == 5
        assert events[-1].message == "event 2"   # oldest kept

    def test_filter_by_project(self):
        stream = ActivityStream()
        stream.push("proj-a", "job", "task A")
        stream.push("proj-b", "job", "task B")
        filtered = stream.recent(project_id="proj-a")
        assert all(e.project_id == "proj-a" for e in filtered)
        assert len(filtered) == 1

    def test_event_has_timestamp(self):
        stream = ActivityStream()
        stream.push("p", "exec", "ran command")
        assert isinstance(stream.recent()[0].timestamp, datetime)

    def test_clear_empties_stream(self):
        stream = ActivityStream()
        stream.push("p", "job", "something")
        stream.clear()
        assert stream.recent() == []

    def test_event_fields_preserved(self):
        stream = ActivityStream()
        stream.push("myproj", "search", "found 3 results")
        e = stream.recent()[0]
        assert e.project_id == "myproj"
        assert e.kind == "search"
        assert e.message == "found 3 results"
