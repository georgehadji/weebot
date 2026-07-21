#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# check-secrets.sh — Pre-commit and CI secret scanner
#
# Scans the working tree for common API key patterns that should never
# be committed. Runs as a pre-commit hook (via .git/hooks/pre-commit) and
# in CI (via .github/workflows/architecture.yml).
#
# Usage:
#   ./scripts/check-secrets.sh        # scan tracked files
#   ./scripts/check-secrets.sh --ci   # stricter mode for CI
#
# Exit code: 0 (no leaks) / 1 (leaks detected)
# ---------------------------------------------------------------------------
set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

CI_MODE=false
if [[ "${1:-}" == "--ci" ]]; then
  CI_MODE=true
fi

# ── Patterns ──────────────────────────────────────────────────────────────
# Only match lines that look like real key assignments, not example values
PATTERNS=(
  # OpenAI / OpenRouter
  'sk-or-v1-[A-Za-z0-9]{24,}'
  'sk-proj-[A-Za-z0-9]{24,}'
  'sk-ant-[A-Za-z0-9]{24,}'
  'sk-[A-Za-z0-9]{20,}'
  # Anthropic
  'sk-ant-[A-Za-z0-9]{24,}'
  # Generic
  'api_key[[:space:]]*=[[:space:]]*['"'"'\"][A-Za-z0-9_-]{20,}['"'"'\"']'
  'API_KEY[[:space:]]*=[[:space:]]*['"'"'\"][A-Za-z0-9_-]{20,}['"'"'\"']'
  'api-key[[:space:]]*=[[:space:]]*['"'"'\"][A-Za-z0-9_-]{20,}['"'"'\"']'
  'API_KEY[[:space:]]*:[[:space:]]*['"'"'\"][A-Za-z0-9_-]{20,}['"'"'\"']'
)

# Files to exclude (gitignored files are already excluded by git ls-files)
EXCLUDE_PATTERNS=(
  '*.example'
  '*.example.*'
  '*.md'
  '.gitignore'
)

# ── Build ignore list ─────────────────────────────────────────────────────
EXCLUDE_ARGS=()
for pat in "${EXCLUDE_PATTERNS[@]}"; do
  EXCLUDE_ARGS+=( "--exclude-standard" )
done

# ── Scan ──────────────────────────────────────────────────────────────────
get_files() {
  if $CI_MODE; then
    # CI: scan everything tracked
    git ls-files
  else
    # Pre-commit: scan staged files only
    git diff --cached --name-only --diff-filter=ACMR
  fi
}

violations=0

while IFS= read -r file; do
  # Skip excluded patterns
  skip=false
  for pat in "${EXCLUDE_PATTERNS[@]}"; do
    if [[ "$file" == $pat ]]; then
      skip=true
      break
    fi
  done
  $skip && continue

  # Skip binary files
  if [[ -f "$file" ]] && ! git check-attr --cached --all "$file" 2>/dev/null | grep -q "text"; then
    continue
  fi

  for pattern in "${PATTERNS[@]}"; do
    if grep -Pn "$pattern" "$file" 2>/dev/null; then
      echo -e "${RED}[!] SECRET LEAK DETECTED${NC} in $file (matches: $pattern)"
      violations=$((violations + 1))
    fi
  done
done < <(get_files)

if [[ $violations -gt 0 ]]; then
  echo ""
  echo -e "${RED}========================================${NC}"
  echo -e "${RED}  $violations potential secret(s) found!  ${NC}"
  echo -e "${RED}  Remove them before committing.          ${NC}"
  echo -e "${RED}========================================${NC}"
  exit 1
fi

echo -e "${GREEN}[✓] No secrets detected${NC}"
exit 0
