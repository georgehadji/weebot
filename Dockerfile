# syntax=docker/dockerfile:1
# Weebot — Enterprise AI Agent Framework (Python runtime)
# Multi-stage build: builder → runtime

# ── Stage 1: builder ──────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build-time deps for pip wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Cache wheel layer — only invalidated when requirements change
COPY requirements.txt .
RUN pip install --user --no-warn-script-location \
    --no-cache-dir \
    -r requirements.txt

# Install Playwright Chromium in a known path for multi-stage copy
ENV PLAYWRIGHT_BROWSERS_PATH=/build/playwright-browsers
RUN python -m playwright install chromium

# ── Stage 2: runtime ──────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

# Runtime system deps (Playwright browsers, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy Playwright browsers from builder
COPY --from=builder /build/playwright-browsers /opt/playwright-browsers
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers

# Copy application code
COPY alembic.ini .
COPY alembic/ alembic/
COPY docker-entrypoint.sh .
COPY weebot/ weebot/
COPY cli/ cli/
COPY run_mcp.py .
COPY .env.example .env.example

# Database directory
RUN mkdir -p /app/data

# Expose MCP server port (default) and optional FastAPI port
EXPOSE 8000
EXPOSE 5050

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import weebot; print('ok')" || exit 1

# docker-entrypoint.sh runs alembic migrations before the CMD process
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "run_mcp.py"]
# Override CMD: docker run weebot python -m cli.main flow run "task"
