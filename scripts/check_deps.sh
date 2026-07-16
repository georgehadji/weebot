#!/usr/bin/env bash
# Supply-chain quarantine check (WS-A P0)
# Usage: bash scripts/check_deps.sh
#
# Runs pip-audit against requirements.txt for known CVEs, then verifies
# that no dependency in requirements.txt uses an open range (>=) for
# security-critical packages. Open ranges are a supply-chain risk because
# a compromised new release can be pulled automatically.
#
# Install once: pip install pip-audit

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REQS="$REPO_ROOT/requirements.txt"

echo "=== [check_deps] Running pip-audit ==="
pip-audit --requirement "$REQS" --progress-spinner off

echo ""
echo "=== [check_deps] Checking for open-range (>=) on critical packages ==="
CRITICAL=(anthropic openai cryptography mcp pydantic fastapi uvicorn)
FAIL=0
for pkg in "${CRITICAL[@]}"; do
  line=$(grep -i "^${pkg}[=><!]" "$REQS" || true)
  if [[ "$line" == *">="* ]]; then
    echo "WARN: $pkg uses open range: $line  (pin to == for security)"
    FAIL=1
  else
    echo "OK:   $pkg  →  $line"
  fi
done

if [[ "$FAIL" -eq 1 ]]; then
  echo ""
  echo "Supply-chain WARNING: one or more critical packages use open ranges."
  echo "Run 'pip freeze > requirements.txt' and audit before upgrading."
  exit 1
fi

echo ""
echo "Supply-chain check passed."
