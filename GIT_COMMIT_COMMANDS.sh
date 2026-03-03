#!/bin/bash
# Git Commit Commands for Phase 2 Complete
# Run this script to commit all Phase 2 changes

set -e  # Exit on error

echo "==================================="
echo "🚀 Phase 2 Git Commit Script"
echo "==================================="
echo ""

# Check if we're in the right directory
if [ ! -f "run.py" ] || [ ! -d "weebot" ]; then
    echo "❌ Error: Not in weebot project root directory"
    exit 1
fi

echo "📁 Adding Phase 2 implementation files..."

# Core implementation
git add weebot/core/workflow_orchestrator.py \
        weebot/core/circuit_breaker.py \
        weebot/core/dependency_graph.py \
        weebot/tools/base.py \
        weebot/core/__init__.py

echo "✅ Core components added"

echo "📁 Adding security hardening files..."

# Security files
git add weebot/tools/bash_security.py \
        weebot/tools/bash_tool.py

echo "✅ Security components added"

echo "📁 Adding test files..."

# Tests
git add tests/unit/test_workflow_orchestrator.py \
        tests/unit/test_circuit_breaker.py \
        tests/unit/test_dependency_graph.py \
        tests/unit/test_tool_result_enhanced.py \
        tests/unit/test_bash_security_falsifying.py

echo "✅ Test files added"

echo "📁 Adding documentation..."

# Documentation
git add docs/PHASE2_IMPLEMENTATION_SUMMARY.md \
        docs/PHASE2_IMPLEMENTATION_CHECKLIST.md \
        docs/BASH_SECURITY_FIX_ANALYSIS.md \
        docs/BASH_SECURITY_FIX_SUMMARY.md \
        docs/UPDATED_DOCUMENTATION_INDEX.md \
        docs/DOCUMENTATION_UPDATE_LOG.md \
        docs/ROADMAP.md \
        docs/SYSTEM_KNOWLEDGE_MAP.md \
        docs/FINAL_PRODUCTION_SUMMARY.md \
        docs/PRIORITY_ISSUES_ANALYSIS.md

echo "✅ Documentation added"

echo "📁 Adding root files..."

# Root files
git add README.md \
        PROJECT_STATUS.md \
        DEPLOYMENT_CHECKLIST.md \
        GIT_COMMIT_COMMANDS.sh

echo "✅ Root files added"

echo ""
echo "📊 Git Status:"
git status --short

echo ""
echo "==================================="
echo "📝 Ready to commit!"
echo "==================================="
echo ""
echo "Commit message:"
echo "-----------------------------------"
cat << 'EOF'
feat: Phase 2 — Multi-Agent Orchestration Engine + Security Hardening

🎯 Core Components:
- CircuitBreaker: CLOSED/OPEN/HALF_OPEN state machine (22 tests)
- DependencyGraph: DAG validation, cycle detection, topological sort (17+ tests)
- WorkflowOrchestrator: Multi-agent execution with parallel control (15+ tests)
- ToolResult Enhancement: Structured metadata (15 tests)

🛡️ Security:
- BashTool multi-layer defense (4 layers)
- Blocks curl|bash, base64 here-string, process substitution
- 25+ falsifying security tests

🐛 Bug Fixes:
- asyncio.CancelledError handling fixed
- Budget enforcement enabled
- Tool name validation strict
- Duplicate role detection

📚 Documentation:
- 7 new documents, 4 updated
- 100+ pages total
- Complete API coverage

📈 Test Coverage: 94+ tests, all passing

Closes: Phase 2 implementation
Closes: Security hardening
EOF
echo "-----------------------------------"
echo ""

# Ask for confirmation
read -p "Proceed with commit? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    git commit -m "feat: Phase 2 — Multi-Agent Orchestration Engine + Security Hardening

🎯 Core Components:
- CircuitBreaker: CLOSED/OPEN/HALF_OPEN state machine (22 tests)
- DependencyGraph: DAG validation, cycle detection, topological sort (17+ tests)
- WorkflowOrchestrator: Multi-agent execution with parallel control (15+ tests)
- ToolResult Enhancement: Structured metadata (15 tests)

🛡️ Security:
- BashTool multi-layer defense (4 layers)
- Blocks curl|bash, base64 here-string, process substitution
- 25+ falsifying security tests

🐛 Bug Fixes:
- asyncio.CancelledError handling fixed
- Budget enforcement enabled
- Tool name validation strict
- Duplicate role detection

📚 Documentation:
- 7 new documents, 4 updated
- 100+ pages total
- Complete API coverage

📈 Test Coverage: 94+ tests, all passing

Closes: Phase 2 implementation
Closes: Security hardening"

    echo ""
    echo "✅ Commit successful!"
    echo ""
    echo "🏷️  Creating tag v2.0.0..."
    git tag -a v2.0.0 -m "Phase 2 Complete — Multi-Agent Orchestration Engine"
    echo "✅ Tag created!"
    echo ""
    echo "📤 Push commands:"
    echo "   git push origin main"
    echo "   git push origin v2.0.0"
    echo ""
    echo "🎉 Phase 2 deployment ready!"
else
    echo "❌ Commit cancelled"
    git reset HEAD  # Unstage files
    exit 1
fi
