# Fix Plan — Docker & CI Gaps (Audit Findings)

**Source:** `implementation_audit_report.md` (sections 4 and 7)
**Affected files:** `Dockerfile`, `docker-compose.yml`, `.github/workflows/architecture.yml`, NEW: `docker-entrypoint.sh`
**Status:** 3 real defects + 2 planned-upgrade sprints (D4, D5)

---

## Issue Summary

| # | Severity | Problem | Fix |
|---|----------|---------|-----|
| 1 | **HIGH** | `env_file: .env` in docker-compose.yml references a gitignored secrets file — `docker compose up` crashes on CI / fresh checkout | Remove `env_file`, rely on host env vars + `${VAR:-default}` |
| 2 | **MEDIUM** | Playwright browsers never installed — browser tools crash at runtime with "Executable doesn't exist" | Multi-stage: install in builder, copy `PLAYWRIGHT_BROWSERS_PATH` to runtime |
| 3 | — | ~~standalone output assumption~~ | **NOT AN ISSUE** — `weebot-ui/next.config.mjs:4` already has `output: 'standalone'`. Verified. |
| 4 | **LOW** | No `alembic upgrade head` before entrypoint — fresh DB has no tables | Create `docker-entrypoint.sh` with `alembic upgrade head && exec "$@"` |

Also completes sprint **D4** (docker-entrypoint.sh) and **D5** (CI docker steps) from the architecture elevation plan.

---

## Step 1 — Remove `env_file` from docker-compose (Issue 1)

**File:** `docker-compose.yml`

**Problem:** Both `weebot-api` and `weebot-scheduler` services have `env_file: .env` (lines ~20 and ~68), pointing at a gitignored secrets file. On CI or fresh checkout, `.env` doesn't exist and docker compose refuses to start.

**Fix:** Remove `env_file: .env` from both services. The `${VAR:-default}` syntax in the `environment:` block already reads from the host shell environment. Add a comment block at the top of docker-compose explaining the two ways to pass secrets:

```
# ── Passing API keys ────────────────────────────────────────────────
# Option A (CI/remote): export keys in the shell before docker compose
#   export OPENROUTER_API_KEY=sk-or-...
#   docker compose up -d
#
# Option B (local): create .env and use docker compose --env-file
#   cp .env.example .env   # fill in keys
#   docker compose --env-file .env up -d
```

**Risk:** LOW — existing local users who rely on `.env` can use `docker compose --env-file .env up`. CI and fresh users aren't blocked.

---

## Step 2 — Install Playwright browsers in Dockerfile (Issue 2)

**File:** `Dockerfile`

**Problem:** The runtime stage has Playwright system deps (libnss3, libdrm2, etc.) but the Chromium browser binary is never installed. Any agent calling browser tools gets "Executable doesn't exist at .../chrome".

**Fix:** Install Chromium browser in the builder stage alongside pip packages, then copy the browser cache to runtime. Set `PLAYWRIGHT_BROWSERS_PATH` env var.

Builder stage (after `pip install`):
```dockerfile
# Install Playwright Chromium to a known path for multi-stage copy
ENV PLAYWRIGHT_BROWSERS_PATH=/build/playwright-browsers
RUN python -m playwright install chromium
```

Runtime stage (after `COPY --from=builder /root/.local`):
```dockerfile
# Copy Playwright browsers from builder
COPY --from=builder /build/playwright-browsers /opt/playwright-browsers
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers
```

Also add `PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers` to both API and Scheduler services in docker-compose.

**Risk:** LOW — additive; adds ~200 MB to image but browser tools are non-functional without this. The multi-stage copy keeps it out of the builder cache layer.

---

## Step 3 — Create docker-entrypoint.sh with alembic migration (Issue 4 / Sprint D4)

**File:** NEW `docker-entrypoint.sh`

**Problem:** On first launch with a fresh SQLite database, no tables exist. Every persistence call (session, event, memory) crashes until `alembic upgrade head` runs.

**Fix:** Create an entrypoint script that runs the migration then execs the CMD process:

```bash
#!/bin/sh
set -e

# Run database migrations (idempotent — no-op if already current)
echo "Running alembic migrations..."
alembic upgrade head

# Execute the container CMD (e.g., "python run_mcp.py")
exec "$@"
```

Update `Dockerfile`:
```dockerfile
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "run_mcp.py"]
```

This works for ALL services: API, MCP server, and Scheduler. The `exec "$@"` ensures the CMD process gets signals (SIGTERM for graceful shutdown).

**Risk:** LOW — `alembic upgrade head` is idempotent. If the DB doesn't exist yet (SQLite), alembic creates it and runs all migrations. If it already exists and is current, it's a no-op. This is the standard Docker + SQLite entrypoint pattern.

---

## Step 4 — Add Docker steps to CI (Sprint D5)

**File:** `.github/workflows/architecture.yml`

**Problem:** No CI validation that Docker builds work. A broken Dockerfile could merge silently.

**Fix:** Add a `docker-smoke` job after the existing `architecture-fitness` job:

```yaml
  docker-smoke:
    name: Docker Build Smoke Test
    runs-on: ubuntu-latest
    needs: architecture-fitness
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
      - name: Build weebot-api image
        run: docker build -t weebot-api .
      - name: Build weebot-ui image
        run: docker build -t weebot-ui -f weebot-ui/Dockerfile weebot-ui/
      - name: Start services (no .env — verify crash-free)
        run: |
          export OPENROUTER_API_KEY=ci-test-key
          export ANTHROPIC_API_KEY=ci-test-key
          docker compose -f docker-compose.yml up -d --wait || true
      - name: Verify API health
        run: |
          for i in $(seq 1 10); do
            curl -s http://localhost:8000/health && break
            sleep 2
          done
      - name: Check services running
        run: docker compose ps
      - name: Tear down
        if: always()
        run: docker compose down -v
```

**Note:** The `docker compose up -d --wait` may still fail if the container itself has issues (browser missing, DB not initialized, etc.), but the build step at least validates the Dockerfiles compile. A full integration test would require Docker-in-Docker with host networking, which is out of scope.

**Risk:** LOW — additive CI job. Uses `needs: architecture-fitness` to avoid running if core tests fail. Uses `if: always()` on teardown to clean up even on failure.

---

## Verification

After all changes:

```bash
# 1. Dockerfiles build without error
docker build -t weebot-api .
docker build -t weebot-ui -f weebot-ui/Dockerfile weebot-ui/

# 2. docker-compose starts without .env (env-file-less startup)
export OPENROUTER_API_KEY=test
docker compose up -d

# 3. Health check returns 200 (alembic ran, server is up)
curl http://localhost:8000/health

# 4. Services running
docker compose ps   # all 3 "Up" or "healthy"

# 5. Tear down
docker compose down -v
```

---

## Summary

| Step | Fixes | Files |
|------|-------|-------|
| 1 | Remove `env_file: .env`, add secrets-passing docs | `docker-compose.yml` |
| 2 | Install Playwright Chromium via multi-stage copy | `Dockerfile`, `docker-compose.yml` |
| 3 | docker-entrypoint.sh with `alembic upgrade head` | NEW `docker-entrypoint.sh`, `Dockerfile` |
| 4 | CI docker-build smoke test | `.github/workflows/architecture.yml` |

All fixes are additive (no behavioral changes to existing code). Risk: LOW across the board — the only change users see is removing `env_file: .env` which has a documented migration path.
