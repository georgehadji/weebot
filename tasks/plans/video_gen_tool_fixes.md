# Fix Plan — VideoGenTool Audit Defects (D1–D3) + Improvements (I1–I4)

**Source:** `implementation_audit_report.md`
**Target:** `weebot/tools/video_gen_tool.py` (all changes in one file)
**Architecture constraint:** Follow the same patterns used by `ImageGenTool` and existing download guards in `weebot/infrastructure/adapters/`.

---

## Step 1 — Fix D1: hardcoded model name in xAI direct path

**File:** `weebot/tools/video_gen_tool.py`, lines 106–155

**Problem:** `_execute_xai_direct()` hardcodes `"model": "grok-imagine-video"` (line 131). If the caller routes any other `x-ai/*` model through the direct path, the xAI API receives the wrong model name.

**Fix:**
- Add a `model` parameter to `_execute_xai_direct(self, ..., model: str)` — the full OpenRouter model ID (e.g. `"x-ai/grok-imagine-video"`).
- Strip the `x-ai/` prefix to get the bare xAI model name: `model.split("/", 1)[-1]`.
- Use that stripped name in the payload and the result label.
- Update the call site in `_execute_openrouter()` (line ~248) to pass `model` to `_execute_xai_direct(...)`.

```python
# Before (line 107):
async def _execute_xai_direct(
    self,
    prompt: str,
    output_path: str,
    xai_key: str,
) -> ToolResult | None:

# After:
async def _execute_xai_direct(
    self,
    model: str,
    prompt: str,
    output_path: str,
    xai_key: str,
) -> ToolResult | None:
    xai_model = model.split("/", 1)[-1]  # "x-ai/grok-imagine-video" → "grok-imagine-video"
    ...
    payload["model"] = xai_model
    ...
    return await self._download_video(video_url, output_path, model, prompt)
                                      # ^ uses full model name for result label
```

**Call site update** (line ~248):
```python
# Before:
xai_result = await self._execute_xai_direct(
    prompt=prompt, output_path=output_path, xai_key=xai_key,
)
# After:
xai_result = await self._execute_xai_direct(
    model=model,  # <-- added
    prompt=prompt, output_path=output_path, xai_key=xai_key,
)
```

**Risk:** Low — single-method signature change, no callers outside this file.

---

## Step 2 — Fix D2: remove dead `duration_seconds` field

**File:** `weebot/tools/video_gen_tool.py`, lines 42–44 (model) and lines 98–100 (schema)

**Problem:** `duration_seconds` is declared in `VideoGenParams` and the JSON parameters schema but is never read in `_execute_openrouter()` or `_execute_xai_direct()`. The description says "model-dependent, not all models support exact duration" — no current video API in the cascade consumes it.

**Fix:** Remove the field from `VideoGenParams` and the corresponding entry in `self.parameters["properties"]`. It can be re-added later when an API that accepts it is integrated.

**Risk:** Low — dead code removal; no callers can be using it since it was never plumbed.

---

## Step 3 — Fix D3: add download size limit in `_download_video()`

**File:** `weebot/tools/video_gen_tool.py`, lines 188–216

**Problem:** `_download_video()` calls `resp.read()` unbounded — a multi-GB file exhausts memory.

**Fix:** Add a module-level constant `_MAX_VIDEO_BYTES = 512 * 1024 * 1024` (512 MiB, generous for short AI-generated videos). Stream the download in 64 KiB chunks; abort and return `None` if the cumulative total exceeds the cap. Follow the same pattern as `weebot/infrastructure/adapters/skill_index_github.py:44-148`.

```python
_MAX_VIDEO_BYTES: int = 512 * 1024 * 1024  # 512 MiB — generous for AI-generated clips

async def _download_video(self, ...) -> ToolResult | None:
    ...
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(video_url, ...) as resp:
                if resp.status != 200:
                    return None
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    total += len(chunk)
                    if total > _MAX_VIDEO_BYTES:
                        return None
                    chunks.append(chunk)
                path.write_bytes(b"".join(chunks))
    except Exception:
        return None
```

**Risk:** Low — fully contained within `_download_video`. The cap of 512 MiB is far above any realistic AI-generated short video. Streaming in chunks also reduces peak memory.

---

## Step 4 — Fix I1: replace regex with `str.startswith`

**File:** `weebot/tools/video_gen_tool.py`, line 50

**Problem:** `_XAI_VIDEO_PATTERN = re.compile(r"^x-ai/")` — a compiled regex for a simple 5-character prefix check.

**Fix:** Delete the module-level `_XAI_VIDEO_PATTERN`. Replace `_XAI_VIDEO_PATTERN.match(model)` with `model.startswith("x-ai/")` at line ~247 (the only call site, in `_execute_openrouter`). Remove the `import re` at the top if `re` is no longer used elsewhere — but keep it because `_extract_video_url` still calls `re.search()` for the fallback URL regex.

**Risk:** None — functionally identical, simpler, faster.

---

## Step 5 — Fix I2: log regex-based URL extraction

**File:** `weebot/tools/video_gen_tool.py`, line ~183

**Problem:** The last-resort regex URL extraction in `_extract_video_url()` matches silently — if OpenRouter adds a new response format and the regex is the only match, there's no observability.

**Fix:** Add a `logger.warning(...)` call when the regex successfully matches, so operators can detect that the structured extraction paths are not working for a particular model.

```python
if url_match:
    logger.warning("Video URL extracted via regex fallback for model response: %s", url_match.group(0))
    return url_match.group(0)
```

Add `import logging; logger = logging.getLogger(__name__)` at the top of the file (currently `logging` is only imported inline in `_execute_xai_direct`).

**Risk:** None — additive log statement only.

---

## Step 6 — Fix I3: path traversal guard on `output_path`

**File:** `weebot/tools/video_gen_tool.py`, lines 195–197 (`_download_video`) and 230 (`_execute_openrouter` fallback path)

**Problem:** `output_path` from user input is passed directly to `Path(...).write_bytes(...)`. A prompt like `"output_path": "../../etc/malware.mp4"` writes outside the intended directory.

**Fix:** Add a `_sanitize_output_path()` helper that resolves the path, checks for `..` components, and rejects unsafe paths. Call it at the top of `execute()` and `_execute_openrouter()` where the fallback path is generated.

```python
import os as _os

_SAFE_BASE = Path.cwd()  # or a configured workspace root

@staticmethod
def _sanitize_output_path(output_path: str) -> Path:
    """Resolve and validate output_path — reject paths escaping the workspace."""
    path = Path(output_path).resolve()
    if ".." in output_path.split("/") or not str(path).startswith(str(_SAFE_BASE)):
        raise ValueError(f"Unsafe output_path: {output_path}")
    return path
```

Integrate into `execute()` and `_execute_openrouter()`:
```python
# In execute():
path = self._sanitize_output_path(params.output_path)
params.output_path = str(path)

# In _execute_openrouter() fallback:
output_path = str(self._sanitize_output_path(output_path))
```

**Risk:** Low — validation is fail-closed. If the workspace root detection is wrong it could reject legitimate paths, but `Path.cwd()` matches the project root convention. Follow the same approach `ImageGenTool` would use (both tools share the same gap — this fix establishes the pattern).

---

## Step 7 — Fix I4: URL scheme validation before download

**File:** `weebot/tools/video_gen_tool.py`, lines 199 (`_download_video`)

**Problem:** `_download_video()` calls `session.get(video_url)` without checking the URL scheme. A compromised API response could return `file:///etc/passwd` which `aiohttp` would reject, but it's better to fail explicitly.

**Fix:** Add a scheme check at the top of `_download_video()`:

```python
from urllib.parse import urlparse

async def _download_video(self, video_url: str, ...) -> ToolResult | None:
    if not video_url.startswith("https://"):
        return None
    ...
```

**Risk:** None — `aiohttp` already rejects non-http schemes; this just makes the guard explicit and avoids a pointless `session.get()`.

---

## Verification

After all changes:
```
python -B -c "
import asyncio
from weebot.tools.video_gen_tool import VideoGenTool, VideoGenParams

# 1. Import ok
t = VideoGenTool()
assert t.name == 'video_gen'

# 2. duration_seconds removed
p = VideoGenParams(prompt='test', output_path='out.mp4')
assert not hasattr(p, 'duration_seconds')

# 3. xAI model name is dynamic (check signature)
import inspect
sig = inspect.signature(t._execute_xai_direct)
assert 'model' in sig.parameters

# 4. Path traversal guard
try:
    t._sanitize_output_path('../../etc/bad.mp4')
    assert False, 'should have raised'
except (ValueError, OSError):
    pass

# 5. _MAX_VIDEO_BYTES constant exists
from weebot.tools.video_gen_tool import _MAX_VIDEO_BYTES
assert _MAX_VIDEO_BYTES > 0

# 6. No regex import for prefix check
import weebot.tools.video_gen_tool as vgt
assert not hasattr(vgt, '_XAI_VIDEO_PATTERN')  # removed

print('All checks passed')
"
```

**Risk:** Low — all changes are in one file, no DI or registration changes.

---

## Summary

| Step | Finding | Change | LOC impact |
|------|---------|--------|------------|
| 1 | D1 | Add `model` param to `_execute_xai_direct` + update call site | ~8 changed |
| 2 | D2 | Remove `duration_seconds` from params + schema | ~5 deleted |
| 3 | D3 | Stream download with 512 MiB cap | ~12 added |
| 4 | I1 | Replace regex with `str.startswith` | ~2 changed |
| 5 | I2 | Add `logger.warning` on regex URL extraction | ~3 added |
| 6 | I3 | Add `_sanitize_output_path()` helper + integrate | ~15 added |
| 7 | I4 | Add `https://` scheme guard in `_download_video` | ~3 added |

**Total:** ~48 lines net change, single file, no registration or DI changes. All fixes are backward-compatible — the public `execute()` signature is unchanged.
