---
status: reference
date: 2026-10-22
---

# ICM slice 1: reference integrity (read-only, nothing moved)

Plan: `tasks/icm_plan.md`. Inventory: `tasks/icm_slice0_inventory.md`. Slice 0 decisions applied: `reasonix.toml`, `start-next.bat`, the PDF, `Output/` and `Useful Github Projects/` stay put; `weebot/osworld` is marked leftover (map flag only, no move).

Method: for each file proposed to move, grep the whole repo (including markdown, workflows, `.gitignore`, Docker files; excluding `.git`, `node_modules`, `.next`) for its name, then check destination collisions case-folded and whether root copies are tracked.

## Verdicts

| Verdict | Meaning |
|---|---|
| MOVE | no live referrer; safe to move in slice 7 |
| MOVE-SET | move together, they reference each other |
| DEDUPE | an identical copy already exists at the destination; remove the root copy |
| HOLD | live referrers; do not move unless every referrer is updated in the same change |

## Table

| File(s) | Referrers found | Destination | Verdict |
|---|---|---|---|
| `repository_audit_report.md` | none | `docs/archive/` already holds a byte-identical copy (COLLISION on name) | DEDUPE: delete root copy |
| `implementation_plan.md` | `.gitignore:150`, comment in `pyproject.toml:22`, `docs/archive/implementation_plan.md` text, 4+ files in `tasks/audits/` and `tasks/specs/` | `docs/archive/` holds a byte-identical copy (COLLISION) | HOLD: names are cited as the root path; either keep, or delete root copy and repoint every citation |
| `implementation_audit_report.md` | `.gitignore:149`, `ARCHITECTURE.md:5` (header), `reasonix.toml`, `tasks/plans/*`, `tasks/audits/*`, `tasks/specs/*`; `docs/implementation_audit_report.md` is a DIFFERENT file | n/a | HOLD |
| `PRODUCTION_READINESS_ASSESSMENT.md` | `.gitignore:155` comment, text in `docs/archive/implementation_plan.md` | `docs/archive/` (no collision) | MOVE (update the `.gitignore` comment path) |
| `weebot/FINAL_PROJECT_SUMMARY.md` | none | `docs/archive/` (no collision) | MOVE |
| `fetch_transcript.py` | none (`video_ingest_tool.py` has its own `_fetch_transcript` function) | `scripts/` | MOVE |
| `chunk_transcript.py` + `transcript_WuOlqBsDg-w.txt` | script names the txt file | `docs/archive/transcripts/` | MOVE-SET |
| `transcript.txt`, `transcript.en.srt`, `transcript_orig.en-orig.srt`, `transcript_clean/final/merged/raw/readable.txt`, `transcript_raw.json`, `transcript_structured.json` | none | `docs/archive/transcripts/` | MOVE |
| `subs.en.vtt` | text mention in `PRODUCTION_READINESS_ASSESSMENT.md` and `tasks/specs/defect_hunt_v7_execution_plan.md` (both describe it as a stray file) | `docs/archive/transcripts/` | MOVE (mentions are historical; leave them) |
| `pricing-styles.css`, `pricing-example.html`, `pricing_external*.html` (4), `pricing_section.html`, `responsive_test.html` | the HTML files link the CSS by relative name; `docs/ARCHITECTURE_REMEDIATION_PLAN.md` and `docs/archive/RESPONSIVE_DESIGN_SUMMARY.md` mention them as text | `website_copy/pricing/` | MOVE-SET (keep CSS beside the HTML) |
| `run_dashboard_demo.py`, `run_llm_demo.py` | one spec mentions them (`tasks/specs/static_defect_audit_v3_execution_plan.md`) | `examples/` | MOVE, but first confirm they still run from there (they import `weebot` and may rely on being at the repo root) |

Why `docs/archive/transcripts/` and not `Output/`: `.gitignore` ignores generated output, and moving tracked files into an ignored folder invites confusing git state.

Case-folded collisions at destinations: only `implementation_plan.md` and `repository_audit_report.md` in `docs/archive/` (both identical to the root files). No collisions in `scripts/`, `examples/`, `website_copy/`.

## Findings that need your attention

1. **`reasonix.toml` is an external consumer.** Its allow-list hard-codes `E:\Documents\Vibe-Coding\weebot` and a command that reads `implementation_...` at the repo root. That is why `implementation_audit_report.md` and `implementation_plan.md` are HOLD. You said `reasonix.toml` stays; if those two files stay too, nothing breaks.
2. **Tracked but gitignored.** `.gitignore:149-150` ignores `/implementation_audit_report.md` and `/implementation_plan.md`, yet both are tracked. The ignore rule does nothing for tracked files; a leftover.
3. **`weebot/qmd_integration/__init__.py:9`** docstring names `E:/Documents/Vibe-Coding/weebot/Useful Github Projects/qmd-main`. `Useful Github Projects/` stays, so nothing to change.
4. External consumers not visible from inside the repo (Claude Desktop config, scheduled tasks, other checkouts such as the `E:` path above) are unverified. Only you can confirm them.

## Proposed slice 7 change set (needs approval; copy, verify hash, then remove)

- MOVE/MOVE-SET: `PRODUCTION_READINESS_ASSESSMENT.md`, `weebot/FINAL_PROJECT_SUMMARY.md`, 12 transcript files plus `chunk_transcript.py`, `subs.en.vtt`, 8 pricing/responsive files, `fetch_transcript.py`, two demos.
- DEDUPE: delete root `repository_audit_report.md`.
- HOLD: `implementation_plan.md`, `implementation_audit_report.md`.
- Edit one `.gitignore` comment path.
- Run `make check` (or the script gates) before and after.
