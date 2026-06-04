#!/bin/bash
# Install git hooks for the weebot project.
# Run from the project root: ./scripts/install-hooks.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
GIT_DIR="$(cd "$PROJECT_ROOT" && git rev-parse --git-dir)"

echo "Installing weebot git hooks..."

# Post-commit: update graphify knowledge graph
cp "$SCRIPT_DIR/post-commit-graphify.sh" "$GIT_DIR/hooks/post-commit"
chmod +x "$GIT_DIR/hooks/post-commit"
echo "  ✓ post-commit → graphify knowledge graph update"

echo "Done. Hooks installed at $GIT_DIR/hooks/"
