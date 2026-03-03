#!/bin/bash
# Release v2.1.0 - Template Engine
# Usage: ./release_v2.1.0.sh

echo "=========================================="
echo "Weebot v2.1.0 Release Script"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check git status
echo -e "${YELLOW}Checking git status...${NC}"
git status --short
if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Not a git repository${NC}"
    exit 1
fi

echo ""
read -p "Continue with release? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Release cancelled${NC}"
    exit 0
fi

# Step 1: Run tests
echo ""
echo -e "${YELLOW}Step 1: Running tests...${NC}"
python -m pytest tests/unit/test_templates/ -v --tb=short
if [ $? -ne 0 ]; then
    echo -e "${RED}Tests failed! Fix before releasing.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Tests passed${NC}"

# Step 2: Verify version
echo ""
echo -e "${YELLOW}Step 2: Verifying version...${NC}"
if [ -f VERSION ]; then
    VERSION=$(cat VERSION)
    echo "Version: $VERSION"
    if [ "$VERSION" != "2.1.0" ]; then
        echo -e "${RED}Warning: VERSION file doesn't match 2.1.0${NC}"
        read -p "Continue anyway? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 0
        fi
    fi
else
    echo -e "${RED}VERSION file not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Version verified${NC}"

# Step 3: Add all changes
echo ""
echo -e "${YELLOW}Step 3: Adding changes to git...${NC}"
git add -A
echo -e "${GREEN}✓ Changes added${NC}"

# Step 4: Commit
echo ""
echo -e "${YELLOW}Step 4: Creating commit...${NC}"
git commit -m "Release v2.1.0: Template Engine

- Add YAML-based workflow template system
- 8 built-in templates:
  * Research Analysis
  * Competitive Analysis  
  * Data Processing
  * Code Review (NEW)
  * Documentation (NEW)
  * Bug Analysis (NEW)
  * Meeting Summary (NEW)
  * Learning Path (NEW)
- Agent system integration with role-based agents
- 100+ unit tests (all passing)
- CLI interface for template execution
- Full documentation and examples

Phase 3 complete! 🎉"

if [ $? -ne 0 ]; then
    echo -e "${RED}Commit failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Commit created${NC}"

# Step 5: Create tag
echo ""
echo -e "${YELLOW}Step 5: Creating git tag v2.1.0...${NC}"
git tag -a v2.1.0 -m "Release v2.1.0 - Template Engine

Major features:
- YAML Template Engine
- 8 built-in templates
- Agent system integration
- 100+ tests

See RELEASE_NOTES_v2.1.0.md for details."

if [ $? -ne 0 ]; then
    echo -e "${RED}Tag creation failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Tag v2.1.0 created${NC}"

# Step 6: Push
echo ""
echo -e "${YELLOW}Step 6: Pushing to remote...${NC}"
echo "Commands to execute:"
echo "  git push origin main"
echo "  git push origin v2.1.0"
echo ""
read -p "Push to remote? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    git push origin main
    git push origin v2.1.0
    echo -e "${GREEN}✓ Pushed to remote${NC}"
else
    echo -e "${YELLOW}Push skipped. Run manually:${NC}"
    echo "  git push origin main"
    echo "  git push origin v2.1.0"
fi

# Done
echo ""
echo "=========================================="
echo -e "${GREEN}Release v2.1.0 Complete!${NC}"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Go to GitHub: https://github.com/[username]/weebot/releases"
echo "2. Click 'Draft a new release'"
echo "3. Choose tag: v2.1.0"
echo "4. Title: 'Weebot v2.1.0 - Template Engine'"
echo "5. Copy content from RELEASE_NOTES_v2.1.0.md"
echo "6. Publish release"
echo ""
echo "🎉 Phase 3 is now live!"
