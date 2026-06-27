# YouTube Video Download Support — Implementation Plan

**Context:** weebot currently supports YouTube *transcript* ingestion (`video_ingest_tool.py` via `youtube-transcript-api`) but cannot download actual video files (MP4). This plan adds video download via `yt-dlp`, a well-maintained, actively developed library.

---

## Architecture Analysis

### Existing tools that download external content

All download tools follow the same pattern:
- `image_gen_tool.py` — downloads images via OpenRouter/direct APIs
- `video_gen_tool.py` — downloads AI-generated videos via OpenRouter
- `video_ingest_tool.py` — ingests YouTube transcripts (text only)

Common patterns across all three:
- Extend `BaseTool` with `name`, `description`, `parameters`, `execute()`
- Guard with `_sanitize_output_path()` (path traversal protection)
- Download with `_download_image()` / `_download_video()` (HTTPS guard, streaming cap)
- Return `ToolResult` with `data={"path": str, "size_bytes": int, ...}`
- Use Pydantic params class for input validation

### Where a YouTube download tool fits

```
weebot/tools/youtube_download_tool.py   ← NEW
├── extends BaseTool
├── uses yt-dlp (subprocess or Python API)
├── follows same guard pattern (_sanitize_output_path, HTTPS check, size cap)
└── auto-discovered by tool_registry (no registration needed)
```

---

## Implementation Steps

### Step 1: Add `yt-dlp` dependency

**File:** `requirements.txt`

```
yt-dlp>=2024.0.0
```

`yt-dlp` is the maintained fork of `youtube-dl`, widely used, actively developed, and supports 1,800+ sites.

---

### Step 2: Create `YouTubeDownloadTool`

**File:** `weebot/tools/youtube_download_tool.py` (NEW)

```python
class YouTubeDownloadParams(BaseModel):
    url: str                      # YouTube URL
    output_path: str = ""          # Where to save (auto-generated if empty)
    format: str = "mp4"           # mp4, webm, mkv, or "audio" (m4a)
    quality: str = "best"          # best, 1080p, 720p, 480p, worst
    max_duration_seconds: int = 600  # Safety: reject videos longer than 10 min
    max_size_mb: int = 500         # Safety: reject downloads larger than 500 MB

class YouTubeDownloadTool(BaseTool):
    name: str = "youtube_download"
    description: str = "Download YouTube videos as MP4 files."
    default_timeout_seconds: int = 300  # Video downloads take longer
    parameters: dict = {...}       # JSON Schema matching YouTubeDownloadParams
```

**Execute method:**

1. Validate URL → extract video ID from YouTube URL patterns
2. Check video metadata (duration, size) via `yt-dlp --dump-json` → reject if exceeds limits
3. Download via `yt-dlp` subprocess with `--output`, `--format`, `--no-playlist` flags
4. Guard output with `_sanitize_output_path()`
5. Verify file exists and return `ToolResult`

**Error handling:**
- `yt-dlp` not installed → clear error message: "Install yt-dlp: pip install yt-dlp"
- URL not a valid YouTube URL → `ToolResult.error_result("Invalid YouTube URL")`
- Video too long → `ToolResult.error_result("Video exceeds {max_duration}s")`
- Download fails → `ToolResult.error_result(f"YouTube download failed: {stderr}")`
- Path traversal → `ValueError` from `_sanitize_output_path`

---

### Step 3: Integration points

None required. The tool is auto-discovered by `RoleBasedToolRegistry._build_tool_class_map()` (existing H1 autodiscovery). No DI, registry, or discovery file changes needed.

---

### Step 4: Security considerations

| Risk | Mitigation |
|------|------------|
| Path traversal (output_path = "../../etc/malware.mp4") | `_sanitize_output_path()` rejects `..` and paths outside workspace |
| Malicious URL (server-side request forgery) | URL validated against YouTube regex before `yt-dlp` is called |
| Large file exhausts disk or OOM | `max_size_mb` pre-check via `yt-dlp --dump-json`. `max_duration_seconds` caps video length |
| yt-dlp flag injection | URL is escaped — passed as `yt-dlp <url>` string, not shell-constructed |
| Infinite download | `default_timeout_seconds=300` caps total wait time |

---

### Step 5: Testing

- `test_youtube_download_rejects_invalid_url` — non-YouTube URL returns error
- `test_youtube_download_rejects_video_too_long` — mock `--dump-json` with duration > max
- `test_youtube_download_path_traversal` — `../../etc/malware.mp4` raises ValueError
- `test_youtube_download_stub` — with mock subprocess, verify correct yt-dlp args

---

### Step 6: CLI integration (optional)

Add to `cli/main.py`:
```bash
weebot youtube download "https://youtube.com/watch?v=..." --format mp4 --output Output/videos/
```

---

## Summary

| Step | File | Effort |
|------|------|--------|
| 1 | `requirements.txt` | Add 1 line |
| 2 | `weebot/tools/youtube_download_tool.py` | Create ~120 lines |
| 3 | Auto-discovered | 0 lines |
| 4 | Security guards (reuse existing) | 0 lines |
| 5 | `tests/unit/test_youtube_download.py` | ~4 tests |

**Total: 1 new file, 1 dependency, ~120 lines of code. No registration, DI, or registry changes.** The tool surfaces immediately to agents via `youtube_download(url=..., output_path=...)`.
