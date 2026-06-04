#!/bin/bash
# Post-commit hook: update graphify knowledge graph on every commit.
# Installed automatically by `scripts/install-hooks.sh`.
# Runs incremental AST extraction on changed Python files.

set -e

echo "[graphify] Post-commit hook running..."

# Detect the Python interpreter used by graphify
GRAPHIFY_PYTHON="python3"
if [ -f "graphify-out/.graphify_python" ]; then
    GRAPHIFY_PYTHON=$(cat graphify-out/.graphify_python)
fi

# Get the list of changed Python files in the last commit
CHANGED_FILES=$(git diff-tree --no-commit-id -r --name-only HEAD | grep '\.py$' || true)

if [ -z "$CHANGED_FILES" ]; then
    echo "[graphify] No Python files changed — skipping."
    exit 0
fi

echo "[graphify] ${CHANGED_FILES}"
echo "$CHANGED_FILES" | while read -r file; do
    if [ -f "$file" ]; then
        PYFILES="$PYFILES $(realpath "$file")"
    fi
done

# Run incremental graphify extraction on the changed files
if [ -n "$PYFILES" ]; then
    mkdir -p graphify-out
    $GRAPHIFY_PYTHON -c "
import json, sys
from pathlib import Path
from graphify.extract import extract

files = [Path(f) for f in '''$CHANGED_FILES'''.strip().split('\n') if Path(f).suffix == '.py']
if files:
    result = extract(files, cache_root=Path('.'))
    # Merge with existing graph
    graph_path = Path('graphify-out/graph.json')
    if graph_path.exists():
        existing = json.loads(graph_path.read_text())
        existing_nodes = {n['id']: n for n in existing.get('nodes', [])}
        existing_edges = {(e['source'], e['target'], e.get('relation', '')): e for e in existing.get('edges', [])}
        for n in result.get('nodes', []):
            existing_nodes[n['id']] = n
        for e in result.get('edges', []):
            existing_edges[(e['source'], e['target'], e.get('relation', ''))] = e
        merged = {
            'nodes': list(existing_nodes.values()),
            'edges': list(existing_edges.values()),
            'hyperedges': existing.get('hyperedges', []) + result.get('hyperedges', []),
        }
        graph_path.write_text(json.dumps(merged, indent=2))
    else:
        graph_path.write_text(json.dumps(result, indent=2))
    print(f'[graphify] Updated graph: {len(result.get(\"nodes\", []))} new nodes')
else:
    print('[graphify] No Python files to process')
" 2>&1 | tail -5
fi

echo "[graphify] Post-commit hook complete."
