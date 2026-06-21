# Vendored: Atomic Mail Agentic (Python client)

- **Source:** https://github.com/Atomic-Mail/atomic-mail-agentic
- **Vendored from:** `atomic-mail-agentic-main/py/src/atomicmail/`
- **Sync date:** 2026-06-21
- **License:** MIT (see LICENSE)
- **Status at sync:** Open Alpha

## How to re-sync

```bash
cp -r atomic-mail-agentic-main/py/src/atomicmail/ weebot/infrastructure/adapters/atomicmail/
cp atomic-mail-agentic-main/LICENSE weebot/infrastructure/adapters/atomicmail/LICENSE
# Then update this file's sync date
```

## Why vendored (not pip-installed)

The Python client is not published to PyPI at this time. It is pure stdlib
(no third-party dependencies), making vendoring clean and safe.
