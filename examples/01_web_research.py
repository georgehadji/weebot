"""Example 01 — Web Research Workflow
======================================
Demonstrates a 3-step automated research pipeline:

  Step 1  WebSearchTool   → query DuckDuckGo, collect snippets
  Step 2  PythonExecuteTool → keyword-frequency analysis (sandboxed subprocess)
  Step 3  StrReplaceEditorTool → save a Markdown report to disk

Requirements: network access (DuckDuckGo, or Bing via BING_API_KEY env var)

Usage:
    python examples/01_web_research.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Allow running directly: python examples/01_web_research.py (from project root)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from weebot.activity_stream import ActivityStream
from weebot.tools.file_editor import StrReplaceEditorTool
from weebot.tools.python_tool import PythonExecuteTool
from weebot.tools.web_search import WebSearchTool

TOPIC = "Model Context Protocol MCP 2025"
REPORT_PATH = str(Path(__file__).parent / "output" / "research_report.md")


async def main() -> None:
    stream = ActivityStream()
    search_tool = WebSearchTool()
    python_tool = PythonExecuteTool()
    editor_tool = StrReplaceEditorTool()

    # ── Step 1: Web search ─────────────────────────────────────────────────
    print(f"🔍  Step 1: Searching for {TOPIC!r} …")
    search_result = await search_tool.execute(query=TOPIC, num_results=5)

    if search_result.is_error:
        print(f"  ❌  Search failed: {search_result.error}")
        print("  (Is network available?  Is aiohttp installed?)")
        return

    stream.push("example-01", "tool", f"web_search: {TOPIC}")
    preview = search_result.output[:400].replace("\n", " ")
    print(f"  ✅  {len(search_result.output)} chars returned")
    print(f"  Preview: {preview}…\n")

    # ── Step 2: Keyword analysis in sandboxed Python ───────────────────────
    print("📊  Step 2: Keyword-frequency analysis …")

    # Write raw results to a temp file so the subprocess can read them
    # safely — avoids any quote-escaping issues when embedding in code.
    tmp_path = str(Path(__file__).parent / "output" / "_search_raw.txt")
    os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
    Path(tmp_path).write_text(search_result.output, encoding="utf-8")

    analysis_code = f"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import re
from collections import Counter
from pathlib import Path

text = Path({repr(tmp_path)}).read_text(encoding='utf-8')
words = re.findall(r'\\b[A-Za-z]{{4,}}\\b', text.lower())
# Filter out very common English stop-words
STOP = {{'that', 'this', 'with', 'from', 'have', 'your', 'more', 'will',
         'about', 'their', 'what', 'been', 'into', 'when', 'also', 'which'}}
filtered = [w for w in words if w not in STOP]
top = Counter(filtered).most_common(12)

print("Top keywords:")
for rank, (word, count) in enumerate(top, 1):
    bar = '█' * count
    print(f"  {{rank:>2}}. {{word:<18}} {{bar}} ({{count}})")
"""

    py_result = await python_tool.execute(code=analysis_code, timeout=15)
    if py_result.is_error:
        print(f"  ❌  Analysis error: {py_result.error}")
        analysis_text = "(analysis unavailable)"
    else:
        analysis_text = py_result.output
        stream.push("example-01", "tool", "python_execute: keyword analysis")
        print(f"  ✅  Analysis complete\n{py_result.output}")

    # ── Step 3: Save Markdown report ───────────────────────────────────────
    print("📄  Step 3: Saving report …")

    report_md = (
        f"# Research Report: {TOPIC}\n\n"
        f"## Search Results\n\n```\n{search_result.output[:1500]}\n```\n\n"
        f"## Keyword Analysis\n\n```\n{analysis_text}\n```\n"
    )

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    save_result = await editor_tool.execute(
        command="create", path=REPORT_PATH, file_text=report_md
    )
    if save_result.is_error:
        print(f"  ❌  Save failed: {save_result.error}")
    else:
        stream.push("example-01", "tool", f"file_editor: create {REPORT_PATH}")
        print(f"  ✅  Report saved → {REPORT_PATH}")

    # ── Summary ────────────────────────────────────────────────────────────
    print(f"\n📋  Activity log ({len(stream.recent())} events):")
    for event in stream.recent():
        print(f"    [{event.kind}] {event.message}")


if __name__ == "__main__":
    asyncio.run(main())
