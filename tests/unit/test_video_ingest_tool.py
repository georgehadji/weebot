"""Tests for VideoIngestTool (YouTube transcript ingestion + JSONL export)."""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from weebot.tools.video_ingest_tool import VideoIngestTool, _chunk_text, _extract_video_id


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def vt(tmp_path):
    """Fresh VideoIngestTool backed by a temp-file SQLite database."""
    return VideoIngestTool(db_path=str(tmp_path / "video_test.db"))


def _fake_transcript(text: str = "Hello world " * 200):
    """Build a mock YouTubeTranscriptApi that returns a fixed transcript."""
    segment = {"text": text, "start": 0.0, "duration": 1.0}

    mock_transcript = MagicMock()
    mock_transcript.fetch.return_value = [segment]
    mock_transcript.language_code = "en"

    mock_list = MagicMock()
    mock_list.find_transcript.return_value = mock_transcript
    mock_list.__iter__ = MagicMock(return_value=iter([mock_transcript]))

    return mock_list


# ---------------------------------------------------------------------------
# _extract_video_id
# ---------------------------------------------------------------------------

def test_extract_video_id_standard_url():
    vid = _extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert vid == "dQw4w9WgXcQ"


def test_extract_video_id_short_url():
    vid = _extract_video_id("https://youtu.be/dQw4w9WgXcQ")
    assert vid == "dQw4w9WgXcQ"


def test_extract_video_id_shorts_url():
    vid = _extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ")
    assert vid == "dQw4w9WgXcQ"


def test_extract_video_id_invalid_url():
    vid = _extract_video_id("https://vimeo.com/12345")
    assert vid is None


# ---------------------------------------------------------------------------
# _chunk_text
# ---------------------------------------------------------------------------

def test_chunk_text_produces_chunks():
    text = " ".join([f"word{i}" for i in range(1000)])
    chunks = _chunk_text(text, chunk_size=100, overlap=10)
    assert len(chunks) > 1
    # Each chunk has at least 20 words
    for c in chunks:
        assert len(c.split()) >= 20


def test_chunk_text_overlap():
    text = " ".join([f"w{i}" for i in range(200)])
    chunks = _chunk_text(text, chunk_size=100, overlap=20)
    # With overlap, end of chunk N shares words with start of chunk N+1
    if len(chunks) >= 2:
        tail = set(chunks[0].split()[-20:])
        head = set(chunks[1].split()[:20])
        assert tail & head  # non-empty intersection


def test_chunk_text_short_input_single_chunk():
    # 30 words — enough to pass the 20-word minimum threshold
    text = " ".join([f"word{i}" for i in range(30)])
    chunks = _chunk_text(text, chunk_size=400)
    assert len(chunks) == 1


# ---------------------------------------------------------------------------
# ingest_youtube — validation errors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_youtube_missing_url_is_error(vt):
    result = await vt.execute(action="ingest_youtube", project_id="p1")
    assert result.is_error
    assert "url" in result.error


@pytest.mark.asyncio
async def test_ingest_youtube_missing_project_id_is_error(vt):
    result = await vt.execute(action="ingest_youtube", url="https://youtu.be/abc123abc12")
    assert result.is_error
    assert "project_id" in result.error


@pytest.mark.asyncio
async def test_ingest_youtube_invalid_url_is_error(vt):
    result = await vt.execute(
        action="ingest_youtube",
        url="https://not-youtube.com/video",
        project_id="p1",
    )
    assert result.is_error
    assert "video ID" in result.error


# ---------------------------------------------------------------------------
# ingest_youtube — success (mocked transcript API)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_youtube_returns_source_id(vt):
    with (
        patch("weebot.tools.video_ingest_tool.YouTubeTranscriptApi") as mock_api,
        patch("weebot.tools.video_ingest_tool._fetch_title", return_value="Test Video"),
    ):
        mock_api.list_transcripts.return_value = _fake_transcript()
        result = await vt.execute(
            action="ingest_youtube",
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            project_id="proj-1",
        )

    assert not result.is_error, result.error
    data = json.loads(result.output)
    assert "source_id" in data
    assert data["project_id"] == "proj-1"
    assert data["chunk_count"] >= 1


@pytest.mark.asyncio
async def test_ingest_youtube_chunks_stored_in_kb_notes(vt, tmp_path):
    import sqlite3 as _sq

    with (
        patch("weebot.tools.video_ingest_tool.YouTubeTranscriptApi") as mock_api,
        patch("weebot.tools.video_ingest_tool._fetch_title", return_value="My Video"),
    ):
        mock_api.list_transcripts.return_value = _fake_transcript("word " * 500)
        result = await vt.execute(
            action="ingest_youtube",
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            project_id="proj-2",
        )

    data = json.loads(result.output)
    chunk_count = data["chunk_count"]

    with _sq.connect(vt.db_path) as conn:
        rows = conn.execute(
            "SELECT note_id FROM kb_notes WHERE project_id = 'proj-2'"
        ).fetchall()

    assert len(rows) == chunk_count


@pytest.mark.asyncio
async def test_ingest_youtube_source_recorded(vt):
    with (
        patch("weebot.tools.video_ingest_tool.YouTubeTranscriptApi") as mock_api,
        patch("weebot.tools.video_ingest_tool._fetch_title", return_value="Src Video"),
    ):
        mock_api.list_transcripts.return_value = _fake_transcript()
        await vt.execute(
            action="ingest_youtube",
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            project_id="p-src",
        )

    list_result = await vt.execute(action="list_sources", project_id="p-src")
    assert not list_result.is_error
    data = json.loads(list_result.output)
    assert data["count"] == 1
    assert data["sources"][0]["status"] == "done"
    assert data["sources"][0]["title"] == "Src Video"


# ---------------------------------------------------------------------------
# list_sources
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_sources_empty_project(vt):
    result = await vt.execute(action="list_sources", project_id="nonexistent")
    assert not result.is_error
    data = json.loads(result.output)
    assert data["count"] == 0


@pytest.mark.asyncio
async def test_list_sources_no_filter_returns_all(vt):
    for vid_id in ("aaaaaaaaaaa", "bbbbbbbbbbb"):
        with (
            patch("weebot.tools.video_ingest_tool.YouTubeTranscriptApi") as mock_api,
            patch("weebot.tools.video_ingest_tool._fetch_title", return_value="T"),
        ):
            mock_api.list_transcripts.return_value = _fake_transcript()
            await vt.execute(
                action="ingest_youtube",
                url=f"https://www.youtube.com/watch?v={vid_id}",
                project_id="multi",
            )

    result = await vt.execute(action="list_sources")
    data = json.loads(result.output)
    assert data["count"] == 2


# ---------------------------------------------------------------------------
# export_jsonl
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_jsonl_missing_project_id_is_error(vt, tmp_path):
    result = await vt.execute(
        action="export_jsonl", output_path=str(tmp_path / "out.jsonl")
    )
    assert result.is_error
    assert "project_id" in result.error


@pytest.mark.asyncio
async def test_export_jsonl_missing_output_path_is_error(vt):
    result = await vt.execute(action="export_jsonl", project_id="p1")
    assert result.is_error
    assert "output_path" in result.error


@pytest.mark.asyncio
async def test_export_jsonl_creates_valid_jsonl(vt, tmp_path):
    with (
        patch("weebot.tools.video_ingest_tool.YouTubeTranscriptApi") as mock_api,
        patch("weebot.tools.video_ingest_tool._fetch_title", return_value="JSONL Video"),
    ):
        mock_api.list_transcripts.return_value = _fake_transcript("token " * 600)
        await vt.execute(
            action="ingest_youtube",
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            project_id="export-test",
        )

    out = str(tmp_path / "training.jsonl")
    result = await vt.execute(
        action="export_jsonl", project_id="export-test", output_path=out
    )

    assert not result.is_error, result.error
    data = json.loads(result.output)
    assert data["exported"] >= 1
    assert data["skipped"] == 0

    # Verify every line is valid JSON with required keys
    with open(out, encoding="utf-8") as fh:
        lines = [json.loads(l) for l in fh if l.strip()]
    assert len(lines) == data["total"]
    for line in lines:
        assert "id" in line and "text" in line and "source" in line and "title" in line


@pytest.mark.asyncio
async def test_export_jsonl_resumes_after_crash(vt, tmp_path):
    """Second export run skips already-written lines (crash recovery)."""
    with (
        patch("weebot.tools.video_ingest_tool.YouTubeTranscriptApi") as mock_api,
        patch("weebot.tools.video_ingest_tool._fetch_title", return_value="Resume Video"),
    ):
        mock_api.list_transcripts.return_value = _fake_transcript("data " * 800)
        await vt.execute(
            action="ingest_youtube",
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            project_id="resume-test",
        )

    out = str(tmp_path / "resume.jsonl")

    # First export — write all lines
    r1 = await vt.execute(
        action="export_jsonl", project_id="resume-test", output_path=out
    )
    d1 = json.loads(r1.output)
    assert d1["skipped"] == 0
    total = d1["total"]

    # Simulate partial crash by truncating to first line
    with open(out, "r", encoding="utf-8") as fh:
        first_line = fh.readline()
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(first_line)

    # Second export — should skip the 1 already-written line
    r2 = await vt.execute(
        action="export_jsonl", project_id="resume-test", output_path=out
    )
    d2 = json.loads(r2.output)
    assert d2["skipped"] == 1
    assert d2["exported"] == total - 1
    assert d2["total"] == total


# ---------------------------------------------------------------------------
# unknown action
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_action_is_error(vt):
    result = await vt.execute(action="fly_to_moon")
    assert result.is_error
    assert "Unknown action" in result.error
