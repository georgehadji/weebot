# Release v2.1.0 Checklist

## Pre-Release

- [x] All tests passing (100+)
- [x] Code review completed
- [x] Documentation updated
- [x] CHANGELOG.md created
- [x] Release notes prepared

## Version Update

- [x] VERSION file created (2.1.0)
- [x] All version references updated

## Git Operations

```bash
# 1. Check git status
git status

# 2. Add all changes
git add .

# 3. Commit with release message
git commit -m "Release v2.1.0: Template Engine

- Add YAML-based workflow template system
- 8 built-in templates (3 existing + 5 new)
- Agent system integration
- 100+ unit tests
- CLI interface
- Full documentation

Phase 3 complete!"

# 4. Create tag
git tag -a v2.1.0 -m "Release v2.1.0 - Template Engine"

# 5. Push to remote
git push origin main
git push origin v2.1.0
```

## GitHub Release

1. Go to: https://github.com/[username]/weebot/releases
2. Click "Draft a new release"
3. Choose tag: v2.1.0
4. Title: "Weebot v2.1.0 - Template Engine"
5. Copy content from `RELEASE_NOTES_v2.1.0.md`
6. Attach assets (optional):
   - Source code (zip)
   - Source code (tar.gz)
7. Publish release

## Post-Release

- [ ] Verify GitHub release created
- [ ] Verify tag pushed
- [ ] Close milestone (if using)
- [ ] Announce release (if applicable)

## Verification Commands

```bash
# Verify version
cat VERSION

# Verify tests
pytest tests/unit/test_templates/ -v

# Verify templates
python verify_phase3_complete.py

# Verify git tag
git tag -l | grep v2.1.0

# Verify commit log
git log --oneline -5
```

## Rollback Plan (if needed)

```bash
# Remove tag locally
git tag -d v2.1.0

# Remove tag remotely
git push --delete origin v2.1.0

# Revert commit
git revert HEAD

# Or reset (DANGER: destructive)
git reset --hard HEAD~1
```

---

**Release Manager:** Check each box before proceeding to next step.
