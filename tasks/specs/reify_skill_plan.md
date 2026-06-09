# Video Ingestion & Rule Extraction Skill — Implementation Plan

**Status:** Draft  
**Feature:** `reify_skill` skill — ingest YouTube video, summarize, extract actionable rules  
**Target branch:** `feature/video-reify-skill`  
**Effort:** ~80 lines of new code (1 new file), ~0 lines of edits to existing files

---

## 1. Motivation

The weebot codebase already has `video_ingest_tool.py` (fetches YouTube transcripts + chunks into knowledge base) and `VoiceInputTool` (Whisper transcription for generic audio). But there's no end-to-end "watch this video, tell me what I should do differently" workflow.

This skill fills that gap: a single invocation ingests a YouTube video (or video file), summarizes it, and distills the content into a set of *actionable rules* the user can follow — stored in `persistent_memory` so future agents see them.

## 2. Design

### Workflow

```
User: "Reify this video: https://youtube.com/watch?v=..."
                                                           │
                                                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  reify_skill skill                                              │
│                                                                 │
│  1. Detect source: YouTube URL → video_ingest tool              │
│                    File path    → VoiceInputTool (Whisper)       │
│                                                                 │
│  2. Fetch transcript (YouTube) or transcribe (file)             │
│                                                                 │
│  3. Summarize via LLM (budget model, cheap)                     │
│     - Topic, key claims, methodology, conclusions               │
│                                                                 │
│  4. Extract rules via LLM (structured output, TEMP=0.1)         │
│     Each rule is a single actionable imperative with a          │
│     "because" rationale drawn from the video.                   │
│                                                                 │
│  5. Store rules in persistent_memory (survives session restarts)│
│     Rules appear in future agent system prompts via memory       │
│     snapshot injection.                                         │
│                                                                 │
│  6. Return a ThoughtEvent with summary + rule count             │
└─────────────────────────────────────────────────────────────────┘
```

### Skill file location

```
weebot/skills/builtin/reify_skill/SKILL.md
```

## 3. Implementation

### File: `weebot/skills/builtin/reify_skill/SKILL.md`

A ~80-line skill prompt that tells the agent how to perform the reification workflow.

The skill prompt will instruct the agent to:

1. **Detect the source** — if the user provides a URL containing `youtube.com` or `youtu.be`, use `video_ingest` with action `ingest_youtube`. If a file path (`.mp4`, `.wav`, `.mp3`, `.m4a`), use `voice_input` to transcribe.

2. **Fetch the full transcript** — via the appropriate tool. Chunk into the knowledge base for future search.

3. **Summarize** — ask the LLM to produce a structured summary:
   ```
   TOPIC: [one sentence]
   KEY CLAIMS:
   - ...
   METHODOLOGY: [how the author reaches conclusions]
   CONCLUSIONS:
   - ...
   ```

4. **Extract rules** — ask the LLM to convert the summary into actionable rules. Each rule must be:
   - A single imperative sentence (start with a verb)
   - Grounded in the video (cite the claim)
   - Qualified with a "because" rationale

   Output format (JSON):
   ```json
   {
     "rules": [
       {"rule": "Always validate input at the boundary", "because": "unvalidated input caused 60% of exploits in the study"},
       ...
     ]
   }
   ```

5. **Store** — call `persistent_memory` with `action=add_memory`, passing each rule as a memory entry tagged `video_rule` and `source=<video_title>`.

6. **Report** — output the summary and rule count.

### Model choice

- Summarization: budget model (`x-ai/grok-build-0.1`) — fast, cheap
- Rule extraction: same budget model with `TEMP=0.1` — structured output

Both are non-critical-path tasks. Timeout = 30s for each LLM call.

### Invalidation / freshness

Rules are stamped with the video URL and date. If the user re-ingests the same video, old rules tagged with that URL are overwritten. This is handled by the skill prompt instructing the agent to `delete_note` before `add_note`.

---

## 4. Tests

Add one test file: `tests/unit/test_reify_skill.py`

| Test | What it verifies |
|------|-----------------|
| `test_prompt_includes_detect_source_step` | SKILL.md contains "youtube" and "voice_input" |
| `test_prompt_includes_summarize_step` | SKILL.md contains summarization instruction |
| `test_prompt_includes_rule_extraction` | SKILL.md contains JSON schema for rules |
| `test_prompt_includes_persistent_memory_store` | SKILL.md references `persistent_memory` tool |

These are structural tests — verifying the prompt contains the required workflow steps without actually running the skill (which would require long-running integration tests).

---

## 5. Estimated Scope

| Category | Lines |
|----------|-------|
| SKILL.md (new) | ~80 |
| Test file (new) | ~30 |
| **Total** | **~110** |

---

## 6. No existing-file edits needed

The skill is self-contained. It does NOT add new tools — it composes existing ones (`video_ingest`, `voice_input`, `persistent_memory`). It does NOT modify any Python files. The `RoleBasedToolRegistry` already includes `video_ingest`, `voice_input`, and `persistent_memory` for the `admin` role.

## 7. Activation

```bash
# With the skill loaded
python run.py --interactive --skill reify_skill

# Then prompt:
"Reify this video: https://www.youtube.com/watch?v=..."
```
