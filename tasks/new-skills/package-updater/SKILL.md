---
name: package-updater
description: "Use when updating system or project packages safely. Trigger: update packages, upgrade, apt, pip, npm, outdated packages."
license: MIT
---
# Package Updater

## When to use
Check for outdated packages and apply updates safely with rollback plan.

## Workflow
1. **Detect package manager** — apt, pip, npm, brew, chocolatey.
2. **List outdated** — show all packages with current vs latest versions.
3. **Check changelogs** — flag major version bumps and breaking changes.
4. **Dry-run** — simulate the update to confirm no dependency conflicts.
5. **Apply** — update packages one at a time with confirmation on major versions.
6. **Verify** — confirm services still run after update.

## Safety
- Never update production packages without confirmation
- Always provide rollback instructions

## Output
Update report with before/after versions and any issues encountered.