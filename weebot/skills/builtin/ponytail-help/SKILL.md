---
name: ponytail-help
description: >
  Quick-reference card for all ponytail modes, skills, and commands.
  One-shot display, not a persistent mode. Trigger: `python -m cli.main
  ponytail-help`, "ponytail help", "what ponytail commands", "how do I use
  ponytail". Does not change mode or write files.
metadata:
  emoji: ❓
  trust: trusted
  provenance:
    origin: human
  requires_toolsets: []
  fallback_for_toolsets: []
---

# Ponytail Help

Display this reference card when invoked. One-shot, do NOT change mode,
write flag files, or persist anything.

## Levels

| Level | Trigger | What change |
|-------|---------|-------------|
| **Lite** | `python -m cli.main ponytail lite` | Build what's asked, name the lazier alternative in one line. |
| **Full** | `python -m cli.main ponytail` | The ladder enforced: YAGNI → stdlib → native → one line → minimum. Default. |
| **Ultra** | `python -m cli.main ponytail ultra` | YAGNI extremist. Deletion before addition. Challenges requirements before building. |

Level persists until changed or session end.

## Skills

| Skill | Trigger | What it does |
|-------|---------|--------------|
| **ponytail** | `python -m cli.main ponytail` | Lazy mode itself. Simplest solution that works. |
| **ponytail-review** | `python -m cli.main ponytail-review` | Over-engineering review: `L42: yagni: factory, one product. Inline.` |
| **ponytail-audit** | `python -m cli.main ponytail-audit` | Repo-wide scan for dead code and bloat. |
| **ponytail-help** | `python -m cli.main ponytail-help` | This card. |

## Deactivate

Say "stop ponytail" or "normal mode". Resume anytime with `python -m cli.main ponytail`.
`python -m cli.main ponytail off` also works.

## Environment setting

Set `WEEBOT_PONYTAIL_MODE` in `.env` to make Ponytail active by default:

```bash
WEEBOT_PONYTAIL_MODE=full
```

Valid values: `off`, `lite`, `full`, `ultra`.

## More

Full docs + examples: `docs/research/PONYTAIL_RESEARCH_AND_INTEGRATION_OPTIONS.md`
