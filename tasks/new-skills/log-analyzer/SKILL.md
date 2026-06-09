---
name: log-analyzer
description: "Use when the user asks to analyze, parse, or investigate log files. Trigger keywords: log, error log, analyze logs, parse logs, troubleshoot from logs."
license: MIT
---

# Log Analyzer

## When to use
The user wants to extract insights from log files — error patterns, trends, anomalies.

## Workflow
1. **Identify log files** — find all relevant log files by path or pattern.
2. **Parse format** — detect log format (syslog, JSON, Apache, custom).
3. **Extract metrics:**
   - Error counts by type and time
   - Top error messages
   - Request volume over time
   - Slowest operations
4. **Visualize** — generate a summary table and optional ASCII chart.
5. **Report** — findings with recommendations.

## Output
A markdown report with error summary, timeline, and recommendations.