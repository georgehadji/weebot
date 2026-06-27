# Bug Fix Plan — B4 & B5

**Audit ref:** Phase 1 inventory from 2026-06-18 audit  
**Scope:** B4 (resource leak), B5 (TOCTOU race)  
**Status:** Draft for approval — not yet executed

---

## B4 — ParquetActivitySink orphanes its background flush task

**File:** `weebot/infrastructure/analytics/parquet_sink.py`  
**Severity:** LOW / Confidence: MEDIUM

### Root Cause

`_periodic_flush()` runs an infinite `while True: await sleep(...); await flush()` loop inside `asyncio.ensure_future()`. The Task reference is stored in `self._flush_task` (line 95), but there is no `close()`/`shutdown()` method that cancels and awaits the task. If a `ParquetActivitySink` instance goes out of scope while the flush task is sleeping, the task runs orphaned forever. Exceptions in `_periodic_flush()` or `_write_batch()` are swallowed by the task's default exception handler.

### Fix Plan

**Approach:** Add a `close()` method that cancels the background task and flushes remaining buffered events. Make the sink an async context manager (`__aenter__`/`__aexit__`) so users can `async with ParquetActivitySink(...) as sink:` and get guaranteed cleanup.

**Steps:**

1. **Add `close()` method** (line ~115, after `flush()`):
   ```python
   async def close(self) -> None:
       """Cancel background flush and flush remaining events."""
       if self._flush_task and not self._flush_task.done():
           self._flush_task.cancel()
           try:
               await self._flush_task
           except asyncio.CancelledError:
               pass
       # Flush any remaining buffered events
       await self.flush()
   ```

2. **Make sink an async context manager** (add after `close()`):
   ```python
   async def __aenter__(self) -> "ParquetActivitySink":
       return self

   async def __aexit__(self, *args: object) -> None:
       await self.close()
   ```

3. **Guard `_periodic_flush` against CancelledError** (line ~105, wrap `await self.flush()`):
   ```python
   async def _periodic_flush(self) -> None:
       try:
           while True:
               await asyncio.sleep(self._flush_interval)
               await self.flush()
       except asyncio.CancelledError:
           # Normal shutdown — flush will be handled by close()
           pass
   ```

**Files touched:** `weebot/infrastructure/analytics/parquet_sink.py` (1 file)  
**Breaking change:** NO — adds methods, does not change existing signatures  
**Risk:** LOW — additive only.

### Verification

- Unit test: Create a sink, push events, call `close()`, verify flush task is done and events are written.
- Unit test: Use `async with ParquetActivitySink(...) as sink:` and verify cleanup on exit.
- Unit test: Verify `CancelledError` in `_periodic_flush` does not propagate.

---

## B5 — TOCTOU in file existence checks before open()

**Files:** `weebot/tools/video_ingest_tool.py:335-342`, `weebot/interfaces/gateways/telegram.py:301-303`  
**Severity:** LOW / Confidence: MEDIUM

### Root Cause

`os.path.exists(path)` followed by `open(path)` (video_ingest_tool) or file send (telegram gateway) creates a TOCTOU window. A concurrent process could delete or replace the file between the existence check and the file operation. In a single-process asyncio model this is unlikely, but the pattern is fragile.

### Fix Plan

**Approach:** Replace `os.path.exists()` + `open()` with a direct `open()` wrapped in `try/except FileNotFoundError`. This is atomic — the OS checks existence and opens the file in a single operation.

**Steps:**

1. **`video_ingest_tool.py`** (line 335): Replace `if os.path.exists(output_path):` / `with open(...)` with:
   ```python
   try:
       with open(output_path, "r", encoding="utf-8") as fh:
           skipped = sum(1 for line in fh if line.strip())
   except FileNotFoundError:
       skipped = 0
   except OSError:
       skipped = 0
   ```

2. **`telegram.py`** (line 301): Replace `if not _os.path.exists(path): continue` with a direct file-open attempt (already in a `try/except` block further in the loop). The simplest fix: remove the `exists` check and let the existing exception handling catch any missing files.
   ```python
   # BEFORE (line 301-303):
   if not _os.path.exists(path):
       logger.warning("Media file not found: %s", path)
       continue
   # AFTER: remove the block. The file-open at line 312 (open(path, "rb"))
   #    will raise FileNotFoundError which is caught by the
   #    except Exception at line 320-323 with its own warning.
   ```

**Files touched:** `tools/video_ingest_tool.py`, `interfaces/gateways/telegram.py` (2 files)  
**Breaking change:** NO — behavior is identical; only the error path changes from `os.path.exists` to `FileNotFoundError`.  
**Risk:** LOW — the try/except OSError in video_ingest already catches missing files; the telegram gateway will now emit "Media send failed" instead of "Media file not found" for missing files (same outcome, different log line).

### Verification

- Unit test for video_ingest: Call `export_jsonl` with a non-existent path, verify no crash.
- Unit test for telegram: Send media response with a non-existent file path, verify the `except Exception` block catches it gracefully.
- Regression test: Existing gateway and video ingest tests continue to pass.

---

## Execution Order & Dependencies

| Order | Bug | Files | Depends on |
|---|---|---|---|
| 1 | B4 | `parquet_sink.py` | Nothing |
| 2 | B5 | `video_ingest_tool.py`, `telegram.py` | Nothing |

Both are independent. Can be implemented in a single commit or separately.

## Estimated Effort

| Bug | Effort | Risk |
|---|---|---|
| B4 | 30 min (3 methods added) | LOW |
| B5 | 15 min (2 replacements) | LOW |
| **Total** | **45 min** | |
