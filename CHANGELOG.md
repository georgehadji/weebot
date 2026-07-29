# Changelog

All notable changes to Weebot are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Production Readiness (Phases 0–2)

#### Added
- **Rate limiting**: tiered token-bucket middleware (5 tiers: health, read, mutating, webhook, expensive), configurable via `WEEBOT_RATE_LIMIT_ENABLED`, with `Retry-After` and `X-RateLimit-*` headers (#WI-12)
- **Per-principal API keys**: `ApiKeyPort` + SQLite adapter, CLI key management (`weebot auth create-key`), backward-compatible with `WEEBOT_API_KEY` (#WI-11)
- **Database backup**: online SQLite backup via `sqlite3.Connection.backup()`, integrity verification, 30-day retention, daily cron at 03:00 UTC (#WI-16)
- **Container hardening**: non-root user, `cap_drop: ALL`, `read_only` filesystem, `tmpfs` mounts, resource limits, Valkey password authentication (#WI-13)
- **Frontend quality gates**: CI job running `npm ci`, `npm run lint`, `tsc --noEmit`, `npm run build` (#WI-15)
- **Supply-chain scanning**: dedicated `security-scan` CI job with `pip-audit`, `bandit` SAST, and `npm audit` (#WI-10)
- **Model catalog validation**: 60 models cross-validated at startup against `_ROLE_MODEL_CASCADE` (#WI-04)
- **Build system**: `pyproject.toml` with `[build-system]`, dynamic version from `VERSION` file (#WI-05)

#### Changed
- **Dockerfile**: `CMD` changed from `python run_mcp.py` to `uvicorn weebot.interfaces.web.main:app` with `/api/live` health probe (#WI-08)
- **Persistence**: `_SessionQueries` now returns `dict` not `aiosqlite.Row` — fixes the type contract violation at the boundary (#WI-02)
- **Logging**: `WEEBOT_LOG_LEVEL` env var support; all 6 `datetime.utcnow()` calls replaced with `datetime.now(timezone.utc)` (#WI-09)
- **pytest config**: consolidated from `pytest.ini` into `pyproject.toml` `[tool.pytest.ini_options]` (#WI-06)
- **Schema governance**: 8 core tables moved under Alembic; runtime DDL removed from `checkpoint_store.py` (#WI-17)
- **Scheduler service**: removed from Docker Compose (was a silent no-op; scheduler runs inside API lifespan)
- **Correlation IDs**: middleware adding `X-Correlation-Id` on every HTTP response
- **Async blocking I/O**: reduced violations from 94 to 87 in hot-path tools (`ocr`, `reasoner`, `image_gen`, `video_ingest`) (#WI-14)

#### Fixed
- **Session persistence**: `load_session()` / `list_sessions()` no longer raise `AttributeError` — fixes silent data-availability failure (#WI-02)
- **Model catalog drift**: 8 orphaned model IDs replaced with catalog-valid alternatives (#WI-04)
- **`assert` in production**: replaced with explicit `TypeError` (survives `python -O`) in `_row_to_session`
- **`Dockerfile.api` migration gap**: added `docker-entrypoint.sh` entrypoint so Alembic runs on container start
- **`datetime.utcnow`**: fully eradicated (6 sites across 5 files)
- **Dead code**: removed unreferenced `Dockerfile.web`
- **`pytest.ini`**: properly deleted (was shadowing `pyproject.toml` config)

#### Removed
- `pytest.ini` (config merged into `pyproject.toml`)
- `weebot/tests/` shadow tree (27 stale test files moved to `tests/*/stale/`)
- `Dockerfile.web` (unreferenced; UI uses `weebot-ui/Dockerfile`)
- In-app Alembic migration from FastAPI lifespan (entrypoint handles it with `set -e`)
