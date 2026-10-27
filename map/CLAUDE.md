# map/ — catalog for editing Weebot

Read this before changing code you did not write. The map is an index of nouns and movements. The source tree is the truth; every card cites it. If a card and the code disagree, the code wins and the card is stale.

## Where do I go

| Task | Open |
|---|---|
| What is X (a type, class or file kind)? | `objects/_index.md`, then the card |
| What else moves if I change X? | the card's "If you change this", then `effects/CONTEXT.md` |
| What outside the repo breaks if I move X? | `effects/inbound.md` |
| How does a turn / guard / cascade run? | `processes/CONTEXT.md` |
| How do I walk this map, what do names mean? | `CONTEXT.md` |
| Card rules | `_meta/schema.md`, `_templates/` |
| Commands, build, test | root `CLAUDE.md` |

## Status of this map

Every noun in `objects/_index.md` has a card (Wave G of `tasks/remaining_fix_plan.md` finished the domain, interfaces, browser and tools clusters on 2026-10-23). Defects the cards found are planned in `tasks/icm_fix_plan.md` (F38 onward for Wave G). `processes/` holds five process cards and `effects/CONTEXT.md` the change-impact table (both 2026-10-23). The citation check covers process cards since 2026-10-26; all five were re-read against source on 2026-10-27.

## Rules for editing the map

- One home per fact. Link, do not copy.
- `status: verified` needs a date, a commit hash and `path:line` citations. Otherwise `stub` or `stale`.
- **Editing a citation means moving the card's `commit:` too.** `check_map_citations.py --drift` reads the cited lines *at that commit* and relocates the same text if it moved; it assumes the citation was correct there. Rewrite a citation without advancing `commit:` and the tool will happily "relocate" an unrelated block into a plausible-looking place -- which is how a wrong citation survives a green gate (`FlowRouter.md` declared `50a5d748` while citing lines that only held at `12624041`). After a heavy refactor, review `--fix`'s moves instead of trusting them.
- Never restate as-built behavior; point at the file that owns it.
- After moving code a card cites, run `python scripts/check_map_citations.py --fix`, then re-read any card it marks `stale`. `make check` enforces this (`lint-map-drift`); CI only warns.
- This file is hand-edited. Keep it under 60 lines.
