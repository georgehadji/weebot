# Contributing to Weebot

Thank you for your interest! Weebot is an early-stage project and contribution
guidelines are actively being defined.

## Quick start

```bash
git clone https://github.com/georgehadji/weebot.git
cd weebot
python -m venv .venv && source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
python -m cli.main health
```

## Before submitting a PR

1. **Run the tests:** `pytest tests/ -m "not external"`
2. **Check architecture contracts:** `make lint-imports`
3. **Lint:** `ruff check weebot/ cli/`
4. **Verify undefined names:** `ruff check weebot/ cli/ --select F,E9`

## Commit conventions

We use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` — a new feature
- `fix:` — a bug fix
- `docs:` — documentation only
- `refactor:` — code change that neither fixes nor adds
- `test:` — adding or fixing tests
- `chore:` — maintenance, dependencies, tooling
- `security:` — a security fix

## Code review

- Every PR requires at least one approving review.
- Security-relevant changes require a second reviewer.
- Keep PRs under ~400 lines where practical.
- Every PR must state its testing evidence.

## Architecture

See `ARCHITECTURE.md` and `docs/adr/` for architecture decision records.
The project follows Clean Architecture with four layers:

```
Domain → Application → Infrastructure → Interfaces
```

Import-linter enforces the dependency direction. Domain must remain pure —
no I/O, no framework imports, no infrastructure references.
