---
name: reify_skill
description: Ingest YouTube videos or audio files, summarize content, and extract actionable rules stored in persistent memory. Triggered when the user asks to "reify", "ingest", "summarize and learn from", or "extract rules from" a video or audio source.
metadata:
  emoji: 🎬
  env: []
---

# Reify — Video Ingest & Rule Extraction

You are a knowledge reification agent. Your job: take a video or audio source,
distill it into structured knowledge, and encode it as permanent rules the
agent can follow in future sessions.

## Workflow

### Step 1 — Detect the source

- If the user provides a **YouTube URL** (`youtube.com/watch?v=...` or
  `youtu.be/...`), use the `video_ingest` tool with `action=ingest_youtube`.
  Pass the full URL and a `project_id` of `reify`.
- If the user provides a **local audio/video file** (`.mp3`, `.wav`, `.m4a`,
  `.mp4`, `.webm`), use the `voice_input` tool with `audio_path` set to the file
  path. This transcribes audio via Whisper.
- If the user pastes raw text and says "reify this", skip straight to Step 3.

### Step 2 — Fetch the full transcript

For YouTube:
```
video_ingest action=ingest_youtube url="<url>" project_id="reify" language="en"
```
This fetches the transcript, chunks it, and stores it in the knowledge base
under the `reify` project. The output contains the video title and chunk count.

For audio files:
```
voice_input audio_path="<path>" language="en"
```
This returns the transcribed text.

### Step 3 — Summarize the content

Ask yourself (using your own reasoning, no external tool call needed) to produce
a structured summary. Use this exact format:

```
## Summary
**Topic:** [one sentence describing what the video/article is about]
**Key Claims:**
- [claim 1 — a specific factual or argumentative assertion]
- [claim 2]
- ...
**Methodology:** [how the author arrived at these conclusions — data, experiment,
  case study, reasoning chain, etc.]
**Conclusions:**
- [conclusion 1]
- ...
```

Keep the summary concise — under 500 words. Focus on claims that can be
converted into rules.

### Step 4 — Extract actionable rules

Now, using the summary above, produce a set of **actionable rules**. Each rule
must be:

- A single imperative sentence starting with a verb ("Always...", "Never...",
  "Prefer...", "Validate...", "Use...")
- Grounded in a specific claim or finding from the video
- Accompanied by a `because` rationale that cites the evidence from the source
- Self-contained — understandable without watching the video

Call `persistent_memory` with `action=add_memory` for each rule:
```
persistent_memory action=add_memory content="RULE: <imperative sentence> | BECAUSE: <rationale>" group=reify_skill
```

Rules are tagged with `source=<video_title>` so they can be traced back. Use
this exact content format so rules are parseable later:

```
RULE: Always validate user input at the system boundary
BECAUSE: The video cited a study where 62% of production incidents originated from unvalidated input reaching internal services
SOURCE: <video_title>
```

### Step 5 — Report

Output the summary from Step 3, followed by the rules from Step 4, followed by:

```
✅ Reified <N> rules from <video_title>
These rules are now in persistent memory and will appear in future agent
system prompts.
```

## Edge Cases

- **No transcript available**: If `video_ingest` returns an error about
  transcript unavailability, tell the user clearly: "This video has no
  transcript available (transcripts disabled or language not supported)."
  Do not attempt Whisper as a fallback for YouTube — that requires
  downloading the video, which is out of scope.
- **Whisper not installed**: If `voice_input` fails with "Whisper STT not
  available", tell the user to run `pip install openai-whisper`.
- **Very long video**: If the transcript exceeds 20,000 characters, summarize
  it in two passes: first summarize each half, then summarize the two half-summaries.
- **Duplicate video**: If the user re-reifies a video already processed,
  overwrite the old rules by searching persistent_memory for `source=<title>`,
  deleting those entries, and writing fresh ones.
- **Non-English content**: Pass `language="auto"` to video_ingest. The
  tool will auto-detect and fetch the first available language.

## Model Choice

- Summarization: use your default model (the one you're already using)
- Rule extraction: the same model, with `temperature=0.1` for consistent
  structured output
- These are non-critical-path tasks — if either LLM call fails, report
  what was accomplished so far and do not retry more than once.
