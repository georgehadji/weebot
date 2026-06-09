---
name: backup-workflow
description: "Use when the user asks to back up, archive, or create a snapshot of files. Trigger keywords: backup, archive, snapshot, save copy, rsync."
license: MIT
---

# Backup Workflow

## When to use
The user wants to create a backup of files or directories with verification.

## Workflow
1. **Identify source** — confirm which files/directories to back up.
2. **Choose destination** — local directory, external drive, or network path.
3. **Run backup** — use rsync/robocopy with checksum verification.
4. **Verify** — compare file counts and sizes between source and destination.
5. **Report** — summary of files copied, size, duration, any errors.

## Safety
- Never overwrite existing backups without confirmation
- Always verify before declaring success

## Output
Backup report with file count, total size, duration, and verification status.