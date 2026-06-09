---
name: file-organizer
description: "Use when the user asks to organize, sort, tidy, or clean up files and folders. Trigger keywords: organize, sort, tidy, cleanup, arrange, folder structure, file management."
license: MIT
---

# File Organizer

## When to use
The user wants to organize a directory by sorting files into categorized subfolders, removing junk, or creating a clean folder structure.

## Workflow

1. **Scan the target directory** — use `bash` to list all files with extensions, sizes, and dates.
2. **Identify categories** — group files by type (documents, images, archives, code, media, installers, other) based on extensions.
3. **Create category folders** — use `bash` to `mkdir` subdirectories. Skip if they exist.
4. **Move files** — use `bash` to `mv` each file into its category folder. Log every move.
5. **Handle edge cases:**
   - Files without extensions → `other/`
   - Duplicate names → append `_1`, `_2` or skip if identical content
   - Hidden files (`.` prefix) → keep in place unless explicitly requested
   - Symlinks → preserve, don't follow
6. **Report** — print counts per category and list any files that couldn't be moved.

## Tool guidance
- `bash`: Use `Get-ChildItem` (PowerShell) or `ls`/`find` (Unix) for listing. Use `Move-Item` or `mv` for moving. Always use `-ErrorAction SilentlyContinue` or `2>/dev/null` to avoid halting on permission errors.
- `file_editor`: Not needed for this skill — bash is faster for bulk operations.

## Safety rules
- NEVER delete files unless explicitly asked
- NEVER move files outside the target directory
- NEVER follow symlinks outside the target directory
- Always preview the operation (list what will be moved) before executing
- Always confirm with the user before moving more than 100 files

## Output
A summary table showing:
- Files moved per category
- Total files processed
- Any errors or skipped files
