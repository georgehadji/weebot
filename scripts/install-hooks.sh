#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# install-hooks.sh — Install git hooks for this project
#
# Run this once after cloning to enable pre-commit secret scanning.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOOKS_DIR="$REPO_ROOT/.git/hooks"

# ── pre-commit ────────────────────────────────────────────────────────────
PRE_COMMIT="$HOOKS_DIR/pre-commit"
if [[ ! -f "$PRE_COMMIT" ]]; then
  cat > "$PRE_COMMIT" << 'HOOK'
#!/usr/bin/env bash
set -euo pipefail
exec "$(git rev-parse --show-toplevel)/scripts/check-secrets.sh"
HOOK
  chmod +x "$PRE_COMMIT"
  echo "[✓] Installed pre-commit hook → scripts/check-secrets.sh"
else
  echo "[i] pre-commit hook already exists — skipping"
fi

echo ""
echo "Done. Secrets will be scanned before every commit."
