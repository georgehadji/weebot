---
name: youtube-download
description: Download videos (mp4/webm/mkv) and extract MP3 audio from YouTube, X/Twitter, TikTok, Instagram, Vimeo, Dailymotion, Facebook, Reddit, Twitch, and 1000+ sites using yt-dlp. Handles age-restricted content via browser cookies, JS-heavy sites via Deno, and falls back to transcripts. Triggered for any video download, save, or MP3 extraction task.
metadata:
  emoji: 📥
  trust: trusted
  provenance:
    origin: human
  requires_toolsets: ["youtube_download"]
  fallback_for_toolsets: []
---

# Video Download & MP3 Extraction

You can download videos and extract MP3 audio from YouTube, Twitter/X, TikTok, Instagram, Vimeo, Dailymotion, Facebook, Reddit, Twitch, and 1000+ other sites via the `youtube_download` tool (which uses yt-dlp under the hood — it handles hundreds of sites, not just YouTube).

**CRITICAL RULES:**

1. **Always use the `youtube_download` tool** — never run `yt-dlp.exe` directly via bash/powershell. The tool has built-in error handling, targeted fallback instructions, cookie support, and JS runtime support. Raw yt-dlp commands bypass all of this.

2. **Never give up after the first failure.** When `youtube_download` returns an error, the error message will tell you exactly what to try next. Follow the fallback chain WITHIN THE SAME STEP — do NOT terminate the step as "completed" until you have exhausted ALL approaches or succeeded.

3. **In your plan, make the download step use the `youtube_download` tool.** Example step: "Download the video using youtube_download tool with url=...". Do NOT plan raw PowerShell/yt-dlp commands.

If the first download attempt returns an error, READ the error message carefully — it contains explicit instructions for the next approach to try. Follow them in order.

---

## Tool Reference

| Goal | Tool / Command | Key Parameters |
|---|---|---|
| Download video (mp4) | `youtube_download` | `url`, `format="mp4"` |
| Download video (webm/mkv) | `youtube_download` | `url`, `format="webm"` or `"mkv"` |
| Extract MP3 audio | `youtube_download` | `url`, `format="mp3"` — auto-extracts 320kbps |
| Extract m4a audio | `youtube_download` | `url`, `format="audio"` |
| Age-restricted video | `youtube_download` + `advanced_browser` | `cookies="path/to/cookies.txt"` |
| JS runtime missing | Install Deno → `youtube_download` | `js_runtime="C:\\path\\to\\deno.exe"` |
| Transcript / subtitles | `video_ingest` | Works without auth, even on restricted videos |
| Find mirrors | `web_search` | Search for same video on other platforms |

---

## Decision Tree (always follow this order)

```
1. youtube_download(url, format) — normal download
   ✅ Success? Done.
   ❌ "Sign in to confirm your age" → Go to step 2
   ❌ "No supported JavaScript runtime" → Go to step 3
   ❌ Other error → Go to step 4

2. COOKIE WORKFLOW (age-restricted videos)
   a. advanced_browser → navigate to https://youtube.com
   b. Sign in if needed (use form-fill or ask user to sign in)
   c. advanced_browser → get_cookies action → receive JSON
   d. python_execute → convert JSON to Netscape cookie file
   e. youtube_download(url, cookies="path/to/cookies.txt")
   ✅ Success? Done.
   ❌ Still fails → Go to step 4

3. DENO INSTALL (JS runtime error)
   a. Run: winget install DenoLand.Deno
   b. Verify: Get-Command deno
   c. Find path: (Get-Command deno).Source
   d. youtube_download(url, js_runtime="<deno_path>")
   ✅ Success? Done.
   ❌ Still fails → Go to step 4

4. FALLBACKS
   a. video_ingest(url) — get transcript/subtitles
   b. web_search("<video title> download") — find mirrors
   c. Report to user what was obtained and what failed
```

---

## MP3 Extraction Recipe

To extract MP3 audio from any YouTube video:

```
youtube_download(url="https://youtu.be/VIDEO_ID", format="mp3")
```

This tells yt-dlp to:
- Download only the best audio stream (no video data)
- Extract the audio track
- Convert to MP3 at 320kbps (maximum quality)
- Save as `.mp3` file in `Output/videos/`

**No additional steps needed** — yt-dlp handles extraction and conversion automatically. The resulting file is typically 3-8 MB for a 3-5 minute video.

---

## Cookie Workflow (Step-by-Step)

Use this when YouTube returns "Sign in to confirm your age."

**Step 1: Open YouTube in browser**
```
advanced_browser(action="navigate", url="https://youtube.com")
```

**Step 2: Sign in** (if not already signed in)
```
advanced_browser(action="fill", selector="input[type='email']", value="user@gmail.com")
advanced_browser(action="click", selector="button[type='submit']")
```
Or ask the user: "Please sign into YouTube in the browser window, then I'll continue."

**Step 3: Export cookies**
```
advanced_browser(action="get_cookies")
```
This returns a JSON array of cookie objects.

**Step 4: Convert to Netscape format**
```python
import json
cookies = json.loads('''<cookie_json_from_step_3>''')
with open('tmp/youtube_cookies.txt', 'w') as f:
    f.write('# Netscape HTTP Cookie File\n')
    for c in cookies:
        domain = c.get('domain', '.youtube.com')
        flag = 'TRUE' if domain.startswith('.') else 'FALSE'
        path = c.get('path', '/')
        secure = 'TRUE' if c.get('secure', False) else 'FALSE'
        expires = str(int(c.get('expires', 0))) if c.get('expires') else '0'
        f.write(f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{c['name']}\t{c['value']}\n")
```
Use `python_execute` with this code.

**Step 5: Download with cookies**
```
youtube_download(url="https://youtu.be/VIDEO_ID", cookies="tmp/youtube_cookies.txt")
```

---

## Deno Install (for JS Runtime Errors)

When yt-dlp reports "No supported JavaScript runtime could be found":

```powershell
# Check if already installed
Get-Command deno -ErrorAction SilentlyContinue

# Install if missing
winget install DenoLand.Deno

# Get the full path
(Get-Command deno).Source
```

Then pass the path to the tool:
```
youtube_download(url="https://youtu.be/VIDEO_ID", js_runtime="C:\Users\<user>\AppData\Local\deno\deno.exe")
```

---

## Error Recovery Quick Reference

| Error Message | Root Cause | Fix |
|---|---|---|
| "Sign in to confirm your age" | Age restriction | Cookie workflow above |
| "No supported JavaScript runtime" | Missing Deno/Node | Install Deno (above) |
| "Failed to decrypt with DPAPI" | Chrome cookie encryption | Use Playwright get_cookies instead of --cookies-from-browser |
| "Video unavailable" | Private/deleted/geo-blocked | video_ingest for transcript, web_search for mirrors |
| "HTTP Error 403" | Rate limiting or geo-block | Wait 30s, try with cookies |
| "Requested format not available" | No stream at that quality | Retry with `quality="worst"` or `format="audio"` |
