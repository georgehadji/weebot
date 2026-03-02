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

    # ------------------------------------------------------------------
    # Per-project index tests
    # ------------------------------------------------------------------

    def test_project_index_populated_on_push(self):
        stream = ActivityStream()
        stream.push("p1", "job", "a")
        stream.push("p2", "job", "b")
        assert len(stream._by_project["p1"]) == 1
        assert len(stream._by_project["p2"]) == 1

    def test_project_filter_uses_index(self):
        stream = ActivityStream()
        for i in range(5):
            stream.push("alpha", "job", f"a{i}")
        for i in range(3):
            stream.push("beta", "job", f"b{i}")
        alpha = stream.recent(project_id="alpha")
        assert len(alpha) == 5
        assert all(e.project_id == "alpha" for e in alpha)

    def test_project_index_cleared_on_clear(self):
        stream = ActivityStream()
        stream.push("p", "job", "x")
        stream.clear()
        assert len(stream._by_project) == 0

    def test_project_index_eviction_consistent_with_buffer(self):
        """When the buffer is full and oldest event is evicted, the per-project
        index must no longer contain that event."""
        stream = ActivityStream(max_size=3)
        # Push 3 events for "pA" — fills the buffer
        stream.push("pA", "job", "e0")
        stream.push("pA", "job", "e1")
        stream.push("pA", "job", "e2")
        # Push a 4th event: oldest ("e0") is evicted from the buffer
        stream.push("pA", "job", "e3")
        # Main buffer has 3 events; index for pA must also have at most 3
        assert len(stream._by_project["pA"]) <= 3
        # e0 must not appear in recent()
        messages = [e.message for e in stream.recent(project_id="pA")]
        assert "e0" not in messages
