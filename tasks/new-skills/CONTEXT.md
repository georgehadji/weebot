# tasks/new-skills/ — skill drafts (not records, not loaded)

36 folders, each with one `SKILL.md` (frontmatter `name`, `description`, `license`, then the workflow). Added once, 2026-06-10. These are drafts of skills, not plans, specs or audits, so they are not in `tasks/_index.md` and have no `status` or `date`.

## Reads / loaded by

Nothing reads this folder: no loader, script or config refers to `tasks/new-skills` (grep 2026-10-27). Skills that weebot loads live in `weebot/skills/builtin/<skill>/`; imported community skills go in `skills/import/` (root `CLAUDE.md`).

## Human check

To use a draft, review it, then move its folder to `weebot/skills/builtin/` (or `skills/import/`) and register it as the other skills there are. Moving a draft makes it live, so that is a decision, not a tidy-up.
