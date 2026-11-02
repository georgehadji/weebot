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

Every noun in `objects/_index.md` has a card (Wave G of `tasks/remaining_fix_plan.md` finished the domain, interfaces, browser and tools clusters on 2026-10-23). Defects the cards found are planned in `tasks/icm_fix_plan.md` (F38 onward for Wave G). `processes/` holds five process cards and `effects/CONTEXT.md` the change-impact table (both 2026-10-23). The citation check covers process cards since 2026-10-26 and the effects cards since 2026-10-28; all five process cards were re-read against source on 2026-10-27.

## Rules for editing the map

- One home per fact. Link, do not copy.
- `status: verified` needs a date, a commit hash and `path:line` citations. Otherwise `stub` or `stale`. Every citation writes its file path: a bare `:N` ("the file before") cannot be checked, and `check_map_citations.py` rejects it.
- **Editing a citation means moving the card's `commit:` too.** `check_map_citations.py --drift` reads the cited lines *at that commit* and relocates the same text if it moved; it assumes the citation was correct there. Rewrite a citation without advancing `commit:` and the tool will happily "relocate" an unrelated block into a plausible-looking place -- which is how a wrong citation survives a green gate (`FlowRouter.md` declared `50a5d748` while citing lines that only held at `12624041`). After a heavy refactor, review `--fix`'s moves instead of trusting them.
- Never restate as-built behavior; point at the file that owns it.
- After moving code a card cites, run `python scripts/check_map_citations.py --fix`, then re-read any card it marks `stale` and replace its `[stale N]` markers (`make lint-map` fails while a verified card has one). `make check` and the Map Drift workflow (main, weekly) enforce this; a PR only gets a warning.
- This file is hand-edited. Keep it under 60 lines.
