---
name: youtube-download
description: Download videos and extract MP3 audio from YouTube, X/Twitter, TikTok, Instagram, Threads and 1800+ other sites with the Yoinks downloader. Falls back to transcripts when a video cannot be fetched. Triggered for any video download, save, or MP3 extraction task.
metadata:
  emoji: 📥
  trust: trusted
  provenance:
    origin: human
  requires_toolsets: ["youtube_download"]
  fallback_for_toolsets: []
---

# Video Download & MP3 Extraction

You can download a video, or extract its audio as MP3, from YouTube, Twitter/X, TikTok, Instagram, Threads and 1800+ other sites with the `youtube_download` tool. The tool runs the Yoinks downloader (`node <Yoinks>/dist/cli.js`), which brings its own yt-dlp and ffmpeg.

**CRITICAL RULES:**

1. **Always use the `youtube_download` tool.** Never run `yt-dlp` or `yoinks` yourself through bash/powershell: the tool guards the output path, the size and the time, and returns a file path you can use.

2. **Never give up after the first failure.** When `youtube_download` returns an error, read it: it says what Yoinks reported and names the next approach. Try the fallbacks below in the same step before you mark the step done.

3. **In your plan, make the download step use the `youtube_download` tool.** Example step: "Download the video using youtube_download with url=...".

---

## Tool Reference

| Goal | Tool | Key Parameters |
|---|---|---|
| Download a video (best quality, mp4) | `youtube_download` | `url` |
| Extract MP3 audio | `youtube_download` | `url`, `format="mp3"` |
| Save under a chosen name | `youtube_download` | `output_path="Output/videos/clip.mp4"` (inside the project, media file types only) |
| Transcript / subtitles | `video_ingest` | Works without auth, even on restricted videos |
| Find the same video elsewhere | `web_search` | Search for the title on other platforms |

What the tool does not offer: a resolution or container choice (always the best available), cookies, a JavaScript runtime, playlists (one video per call). A request for those cannot be met with this tool; say so rather than retrying.

When `output_path` is empty the file goes to `Output/videos/youtube_<id>.mp4` (or `.mp3`). A video over 500 MiB is deleted after download and reported as an error. The call times out after 5 minutes.

---

## Decision Tree (follow this order)

```
1. youtube_download(url, format) — normal download
   ✅ Success? Return the file path. Done.
   ❌ "Node.js ... is not on PATH" or "Yoinks is not built" → tell the user (fix below); do not retry
   ❌ Any Yoinks error (private, age-restricted, geo-blocked, unavailable) → Go to step 2

2. FALLBACKS
   a. video_ingest(url) — get transcript/subtitles
   b. web_search("<video title>") — find the same video on another site, then youtube_download that URL
   c. Report to the user what was obtained and what failed
```

---

## Setup Errors

| Error | Fix (for the user) |
|---|---|
| "Node.js (22 or newer) is not on PATH" | Install Node 22+ and restart the shell |
| "Yoinks is not built at ..." | Run `npm install && npm run build` in the Yoinks folder, or set `YOINKS_DIR` to where it is built |

Yoinks is expected in a `Yoinks` folder next to the project (`../Yoinks`); `YOINKS_DIR` overrides it.

---

## MP3 Extraction Recipe

```
youtube_download(url="https://youtu.be/VIDEO_ID", format="mp3")
```

Yoinks downloads the best audio and converts it to MP3. No further steps are needed. The result is typically 3-8 MB for a 3-5 minute video.

---

## Error Recovery Quick Reference

| Error Message | Likely Cause | Fix |
|---|---|---|
| "Sign in to confirm your age" | Age restriction | Not downloadable here; use `video_ingest` for the transcript |
| "Video unavailable" / "Private video" | Private, deleted or geo-blocked | `video_ingest` for the transcript, `web_search` for mirrors |
| "HTTP Error 403" / "429" | Rate limit or geo-block | Wait 30 s and retry once |
| "Timed out after 300s" | Very long video or slow link | Pick a shorter video |
| "over the 500 MiB limit" | Too large | Pick a shorter video |
