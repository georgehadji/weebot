"""Example 02 — Data Analysis Workflow
========================================
Demonstrates weebot's sandboxed Python execution for data science tasks.

All computation runs in a child Python process (full isolation).
No external dependencies beyond the standard library are required — the
example uses only `random`, `math`, and `statistics` from stdlib.

Usage:
    python examples/02_data_analysis.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Allow running directly: python examples/02_data_analysis.py (from project root)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")  # Windows emoji support

from weebot.activity_stream import ActivityStream
from weebot.tools.file_editor import StrReplaceEditorTool
from weebot.tools.python_tool import PythonExecuteTool

REPORT_PATH = str(Path(__file__).parent / "output" / "sales_analysis.txt")


# ── Analysis code (runs in sandboxed subprocess) ──────────────────────────────

_ANALYSIS_CODE = """\
import sys
sys.stdout.reconfigure(encoding="utf-8")

import random
import math
import statistics

random.seed(42)

MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

# Simulate a seasonal sales curve with random noise
sales  = [round(1000 + 500 * math.sin(i * 0.52) + random.randint(-80, 80), 2)
          for i in range(12)]
costs  = [round(600 + random.randint(0, 180), 2) for _ in range(12)]
profit = [round(s - c, 2) for s, c in zip(sales, costs)]

total_rev    = sum(sales)
total_cost   = sum(costs)
total_profit = sum(profit)
avg_profit   = statistics.mean(profit)
best_idx     = sales.index(max(sales))
worst_idx    = sales.index(min(sales))

print("=" * 52)
print("        weebot — Annual Sales Report (demo)")
print("=" * 52)
print(f"Revenue  | Total: {total_rev:>10,.2f}  Avg: {statistics.mean(sales):>8,.2f}")
print(f"Costs    | Total: {total_cost:>10,.2f}  Avg: {statistics.mean(costs):>8,.2f}")
print(f"Profit   | Total: {total_profit:>10,.2f}  Avg: {avg_profit:>8,.2f}")
print(f"Best  month : {MONTHS[best_idx]}  ({max(sales):,.2f})")
print(f"Worst month : {MONTHS[worst_idx]}  ({min(sales):,.2f})")
print()
print("Monthly breakdown:")
print(f"  {'Month':<5}  {'Sales':>8}  {'Costs':>7}  {'Profit':>8}  Chart")
print("  " + "-" * 50)
for i, (month, sale, cost, prof) in enumerate(zip(MONTHS, sales, costs, profit)):
    bar_len = max(0, int((sale - 700) / 40))
    bar     = '█' * bar_len
    sign    = '+' if prof >= 0 else ''
    print(f"  {month:<5}  {sale:>8,.0f}  {cost:>7,.0f}  {sign}{prof:>7,.0f}  {bar}")
print("=" * 52)
"""


async def main() -> None:
    stream = ActivityStream()
    python_tool = PythonExecuteTool()
    editor_tool = StrReplaceEditorTool()

    # ── Step 1: Run analysis in sandbox ────────────────────────────────────
    print("🧮  Step 1: Running sandboxed data analysis …")
    result = await python_tool.execute(code=_ANALYSIS_CODE, timeout=15)

    if result.is_error:
        print(f"  ❌  Execution failed: {result.error}")
        return

    stream.push("example-02", "tool", "python_execute: sales analysis")
    print(result.output)

    # ── Step 2: Save report to disk ─────────────────────────────────────────
    print("💾  Step 2: Saving report …")
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    save_result = await editor_tool.execute(
        command="create", path=REPORT_PATH, file_text=result.output
    )
    if save_result.is_error:
        print(f"  ❌  Save failed: {save_result.error}")
    else:
        stream.push("example-02", "tool", f"file_editor: create {REPORT_PATH}")
        print(f"  ✅  Report saved → {REPORT_PATH}")

    # ── Summary ────────────────────────────────────────────────────────────
    print(f"\n📋  Activity log ({len(stream.recent())} events):")
    for event in stream.recent():
        print(f"    [{event.kind}] {event.message}")


if __name__ == "__main__":
    asyncio.run(main())
