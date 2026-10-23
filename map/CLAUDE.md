# map/ — catalog for editing Weebot

Read this before changing code you did not write. The map is an index of nouns and movements. The source tree is the truth; every card cites it. If a card and the code disagree, the code wins and the card is stale.

## Where do I go

| Task | Open |
|---|---|
| What is X (a type, class or file kind)? | `objects/_index.md`, then the card |
| What else moves if I change X? | the card's "If you change this", then `effects/` once it exists |
| How does a turn / guard / cascade run? | `processes/` once it exists |
| How do I walk this map, what do names mean? | `CONTEXT.md` |
| Card rules | `_meta/schema.md`, `_templates/` |
| Commands, build, test | root `CLAUDE.md` |

## Status of this map

Every noun in `objects/_index.md` has a card (Wave G of `tasks/remaining_fix_plan.md` finished the domain, interfaces, browser and tools clusters on 2026-10-23). Defects the cards found are planned in `tasks/icm_fix_plan.md` (F38 onward for Wave G). `processes/` and `effects/` are not created until real cards exist.

## Rules for editing the map

- One home per fact. Link, do not copy.
- `status: verified` needs a date, a commit hash and `path:line` citations. Otherwise `stub` or `stale`.
- Never restate as-built behavior; point at the file that owns it.
- This file is hand-edited. Keep it under 60 lines.
