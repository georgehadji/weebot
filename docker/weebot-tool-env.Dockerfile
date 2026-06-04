FROM python:3.12-slim

LABEL org.weebot.image="tool-environment" \
      org.weebot.version="1.0"

# ── System utilities commonly needed by agent tools ───────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    jq \
    wget \
    ca-certificates \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# ── Common Python packages ────────────────────────────────────────────
RUN pip install --no-cache-dir \
    requests \
    httpx \
    pydantic \
    pyyaml \
    lxml \
    beautifulsoup4 \
    markdown \
    python-dotenv

# ── Create a non-root user for tool execution ─────────────────────────
RUN useradd --create-home --shell /bin/bash weebot
USER weebot
WORKDIR /home/weebot

# ── Default: keep container alive for `docker exec` style usage ───────
CMD ["/bin/bash"]
