---
name: scheduled-reporter
description: "Use when setting up recurring reports or scheduled tasks. Trigger: schedule, recurring, daily report, weekly digest, cron report, automated report."
license: MIT
---
# Scheduled Reporter

## When to use
Create a script or configuration for recurring automated reports.

## Workflow
1. **Define the report** — what data, what format, what frequency.
2. **Write the collection script** — Python or bash script to gather data.
3. **Add scheduling** — cron job (Unix) or Task Scheduler (Windows) entry.
4. **Output handling** — write to file, send via email, or post to webhook.
5. **Test** — run once to verify output.
6. **Install** — add the cron/scheduled task.

## Output
A working scheduled report with installation instructions.