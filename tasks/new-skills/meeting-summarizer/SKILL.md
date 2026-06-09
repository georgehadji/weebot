---
name: meeting-summarizer
description: "Use when the user asks to summarize a meeting, transcript, or conversation. Trigger keywords: summarize meeting, transcript, minutes, action items, recap."
license: MIT
---

# Meeting Summarizer

## When to use
The user has a transcript (text, .vtt, .srt, or raw notes) and wants a structured meeting summary.

## Workflow
1. **Read the transcript** — load the full text.
2. **Extract structured summary:**
   - Attendees mentioned
   - Key decisions made
   - Action items with owners and deadlines
   - Open questions
   - Topics discussed (one paragraph each)
3. **Format output** as clean markdown with sections.

## Output
A markdown file with meeting date, attendees, decisions, action items, and topic summaries.