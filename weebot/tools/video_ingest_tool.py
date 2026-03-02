"""VideoIngestTool — ingest YouTube transcripts into the knowledge base.

Workflow
--------
1. ``ingest_youtube`` — fetch transcript via youtube-transcript-api, chunk it,
   store each chunk in the shared ``kb_notes`` FTS5 table (same database used
   by KnowledgeTool) and record the source in ``video_sources``.
2. ``list_sources``  — browse ingested video sources per project.
3. ``export_jsonl``  — export all project chunks as a fault-tolerant JSONL file.
   If the file already exists the writer skips already-written lines so a
   crashed run can resume from exactly where it stopped.

Dependencies
------------
- ``youtube-transcript-api`` (required): ``pip install youtube-transcript-api``
- ``tiktoken`` (optional): ``pip install tiktoken``
  When present, chunking is token-accurate (cl100k_base).
  When absent, words (whitespace split) are used as a fallback.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime
from typing import Any

from weebot.tools.base import BaseTool, ToolResult

# ---------------------------------------------------------------------------
# Optional dependency — imported at module level for testability
# ---------------------------------------------------------------------------

try:
    from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
    from youtube_transcript_api._errors import (  # type: ignore
        TranscriptsDisabled,
        NoTranscriptFound,
    )
except ImportError:
    YouTubeTranscriptApi = None  # type: ignore[assignment,misc]
    TranscriptsDisabled = Exception  # type: ignore[assignment,misc]
    NoTranscriptFound = Exception  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Chunking helpers
# ---------------------------------------------------------------------------

def _try_tiktoken_encode(text: str) -> list[int] | None:
    """Return token ids using tiktoken, or None if not installed."""
    try:
        import tiktoken  # type: ignore
        enc = tiktoken.get_encoding("cl100k_base")
        return enc.encode(text)
    except Exception:
        return None


def _chunk_text(text: str, chunk_size: int = 400, overlap: int = 50) -> list[str]:
    """Split *text* into overlapping chunks of approximately *chunk_size* units.

    Units are tokens when tiktoken is available, words otherwise.
    Chunks shorter than 20 words are discarded.
    """
    tokens = _try_tiktoken_encode(text)

    if tokens is not None:
        # Token-based chunking
        step = max(1, chunk_size - overlap)
        raw_chunks = [
            tokens[i: i + chunk_size] for i in range(0, len(tokens), step)
        ]
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            decoded = [enc.decode(c) for c in raw_chunks]
        except Exception:
            decoded = []
        if decoded:
            return [c for c in decoded if len(c.split()) >= 20]

    # Fallback: word-based chunking
    words = text.split()
    step = max(1, chunk_size - overlap)
    chunks: list[str] = []
    for i in range(0, len(words), step):
        chunk_words = words[i: i + chunk_size]
        if len(chunk_words) >= 20:
            chunks.append(" ".join(chunk_words))
    return chunks


# ---------------------------------------------------------------------------
# YouTube helpers
# ---------------------------------------------------------------------------

def _extract_video_id(url: str) -> str | None:
    """Return the YouTube video ID from a URL, or None if unrecognised."""
    patterns = [
        r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})",
        r"(?:embed/)([A-Za-z0-9_-]{11})",
        r"(?:shorts/)([A-Za-z0-9_-]{11})",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


def _fetch_transcript(video_id: str, language: str = "en") -> tuple[str, str]:
    """Return ``(title, full_text)`` for *video_id*.

    Raises ``ImportError`` when youtube-transcript-api is not installed.
    Raises ``ValueError`` when no transcript is available.
    """
    if YouTubeTranscriptApi is None:
        raise ImportError(
            "youtube-transcript-api is required. "
            "Install it with: pip install youtube-transcript-api"
        )

    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        # Prefer requested language; fall back to any available transcript.
        try:
            transcript = transcript_list.find_transcript([language])
        except Exception:
            transcript = transcript_list.find_generated_transcript(
                [t.language_code for t in transcript_list]
            )
        segments = transcript.fetch()
    except (TranscriptsDisabled, NoTranscriptFound) as exc:
        raise ValueError(f"No transcript available for video {video_id!r}: {exc}") from exc
    except Exception as exc:
        raise ValueError(f"Failed to fetch transcript: {exc}") from exc

    full_text = " ".join(s["text"] for s in segments)
    # Attempt to get video title via oEmbed (no API key needed).
    title = _fetch_title(video_id)
    return title, full_text


def _fetch_title(video_id: str) -> str:
    """Return the video title from YouTube oEmbed endpoint, or the ID on failure."""
    try:
        import urllib.request
        import urllib.parse
        oembed_url = (
            "https://www.youtube.com/oembed?url="
            + urllib.parse.quote(f"https://www.youtube.com/watch?v={video_id}")
            + "&format=json"
        )
        with urllib.request.urlopen(oembed_url, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            return data.get("title", video_id)
    except Exception:
        return video_id


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

class VideoIngestTool(BaseTool):
    """Ingest YouTube videos into the persistent knowledge base.

    Transcripts are chunked and stored in the shared ``kb_notes`` FTS5 table
    so they are immediately searchable via ``KnowledgeTool.search``.
    A fault-tolerant JSONL exporter lets you build fine-tuning datasets that
    survive process crashes.

    Actions
    -------
    ingest_youtube  -- fetch + chunk + store a YouTube video
    list_sources    -- browse ingested sources
    export_jsonl    -- export chunks as crash-resumable JSONL
    """

    name: str = "video_ingest"
    description: str = (
        "Ingest YouTube video transcripts into the persistent knowledge base "
        "and export them as JSONL training data. "
        "See the 'action' parameter for available operations."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["ingest_youtube", "list_sources", "export_jsonl"],
                "description": "Operation to perform.",
            },
            "url": {
                "type": "string",
                "description": "YouTube video URL (required for ingest_youtube).",
            },
            "project_id": {
                "type": "string",
                "description": "Project scope (required for ingest_youtube / export_jsonl).",
            },
            "language": {
                "type": "string",
                "description": "Preferred transcript language code (default: 'en').",
            },
            "chunk_size": {
                "type": "integer",
                "description": "Approximate words/tokens per chunk (default: 400).",
            },
            "output_path": {
                "type": "string",
                "description": "File path for JSONL output (required for export_jsonl).",
            },
        },
        "required": ["action"],
    }

    db_path: str = "projects.db"

    def model_post_init(self, __context: Any) -> None:
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            # kb_notes may already exist (shared with KnowledgeTool)
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS kb_notes USING fts5(
                    note_id    UNINDEXED,
                    project_id UNINDEXED,
                    created_at UNINDEXED,
                    source     UNINDEXED,
                    title,
                    body,
                    tags
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS video_sources (
                    source_id   TEXT PRIMARY KEY,
                    project_id  TEXT NOT NULL,
                    url         TEXT NOT NULL,
                    title       TEXT DEFAULT '',
                    language    TEXT DEFAULT 'en',
                    chunk_count INTEGER DEFAULT 0,
                    status      TEXT DEFAULT 'done',
                    error_msg   TEXT DEFAULT '',
                    ingested_at TEXT NOT NULL
                )
            """)
            conn.commit()

    # ------------------------------------------------------------------
    # execute dispatcher
    # ------------------------------------------------------------------

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action")
        try:
            if action == "ingest_youtube":
                return self._ingest_youtube(kwargs)
            if action == "list_sources":
                return self._list_sources(kwargs)
            if action == "export_jsonl":
                return self._export_jsonl(kwargs)
            return ToolResult(output="", error=f"Unknown action: {action!r}")
        except Exception as exc:
            return ToolResult(output="", error=str(exc))

    # ------------------------------------------------------------------
    # ingest_youtube
    # ------------------------------------------------------------------

    def _ingest_youtube(self, kw: dict) -> ToolResult:
        url = (kw.get("url") or "").strip()
        project_id = (kw.get("project_id") or "").strip()
        language = (kw.get("language") or "en").strip()
        chunk_size = int(kw.get("chunk_size") or 400)

        if not url:
            return ToolResult(output="", error="'url' is required for ingest_youtube")
        if not project_id:
            return ToolResult(output="", error="'project_id' is required for ingest_youtube")

        video_id = _extract_video_id(url)
        if not video_id:
            return ToolResult(output="", error=f"Could not extract video ID from URL: {url!r}")

        source_id = str(uuid.uuid4())[:8]
        ingested_at = datetime.now().isoformat()

        try:
            title, full_text = _fetch_transcript(video_id, language)
        except (ImportError, ValueError) as exc:
            # Record the failed source so the user can see it in list_sources
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO video_sources "
                    "(source_id, project_id, url, title, language, chunk_count, status, error_msg, ingested_at) "
                    "VALUES (?, ?, ?, '', ?, 0, 'error', ?, ?)",
                    (source_id, project_id, url, language, str(exc), ingested_at),
                )
                conn.commit()
            return ToolResult(output="", error=str(exc))

        chunks = _chunk_text(full_text, chunk_size=chunk_size)
        total = len(chunks)

        with sqlite3.connect(self.db_path) as conn:
            for n, chunk in enumerate(chunks, start=1):
                note_id = f"vid-{source_id}-{n:03d}"
                note_title = f"{title} [chunk {n}/{total}]"
                conn.execute(
                    "INSERT INTO kb_notes "
                    "(note_id, project_id, created_at, source, title, body, tags) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (note_id, project_id, ingested_at, url, note_title, chunk, "video,youtube"),
                )
            conn.execute(
                "INSERT INTO video_sources "
                "(source_id, project_id, url, title, language, chunk_count, status, error_msg, ingested_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'done', '', ?)",
                (source_id, project_id, url, title, language, total, ingested_at),
            )
            conn.commit()

        return ToolResult(
            output=json.dumps(
                {
                    "source_id": source_id,
                    "title": title,
                    "chunk_count": total,
                    "project_id": project_id,
                    "language": language,
                }
            )
        )

    # ------------------------------------------------------------------
    # list_sources
    # ------------------------------------------------------------------

    def _list_sources(self, kw: dict) -> ToolResult:
        project_id = kw.get("project_id") or None

        sql = (
            "SELECT source_id, project_id, url, title, language, "
            "chunk_count, status, error_msg, ingested_at "
            "FROM video_sources"
        )
        params: list = []
        if project_id:
            sql += " WHERE project_id = ?"
            params.append(project_id)
        sql += " ORDER BY ingested_at DESC LIMIT 100"

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()

        sources = [dict(r) for r in rows]
        return ToolResult(output=json.dumps({"count": len(sources), "sources": sources}, indent=2))

    # ------------------------------------------------------------------
    # export_jsonl  (fault-tolerant, crash-resumable)
    # ------------------------------------------------------------------

    def _export_jsonl(self, kw: dict) -> ToolResult:
        project_id = (kw.get("project_id") or "").strip()
        output_path = (kw.get("output_path") or "").strip()

        if not project_id:
            return ToolResult(output="", error="'project_id' is required for export_jsonl")
        if not output_path:
            return ToolResult(output="", error="'output_path' is required for export_jsonl")

        # Count already-written lines so we can resume after a crash.
        skipped = 0
        if os.path.exists(output_path):
            try:
                with open(output_path, "r", encoding="utf-8") as fh:
                    skipped = sum(1 for line in fh if line.strip())
            except OSError:
                skipped = 0

        # Fetch only video-sourced chunks for this project, skip already written.
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT note_id, title, body, source FROM kb_notes "
                "WHERE project_id = ? AND tags LIKE '%video%' "
                "ORDER BY note_id",
                (project_id,),
            ).fetchall()

        to_write = [dict(r) for r in rows][skipped:]

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        exported = 0
        with open(output_path, "a", encoding="utf-8") as fh:
            for row in to_write:
                line = json.dumps(
                    {
                        "id": row["note_id"],
                        "text": row["body"],
                        "source": row["source"],
                        "title": row["title"],
                    },
                    ensure_ascii=False,
                )
                fh.write(line + "\n")
                fh.flush()  # flush every line → crash-safe
                exported += 1

        return ToolResult(
            output=json.dumps(
                {
                    "exported": exported,
                    "skipped": skipped,
                    "total": skipped + exported,
                    "path": output_path,
                }
            )
        )
