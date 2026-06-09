---
name: dependency-auditor
description: "Use when auditing project dependencies for security, licensing, or staleness. Trigger: dependencies, audit deps, outdated, vulnerable, license check, supply chain."
license: MIT
---
# Dependency Auditor

## When to use
Check project dependencies for security vulnerabilities, license issues, and staleness.

## Workflow
1. **Detect** — find package files (package.json, requirements.txt, go.mod, Cargo.toml).
2. **Audit each dependency:**
   - Version: current vs latest
   - Security: known CVEs (via npm audit, pip-audit, or OSV)
   - License: flag non-permissive licenses (GPL, AGPL)
   - Maintenance: last publish date, issue activity
3. **Report** — summary with severity per finding.
4. **Suggest** — upgrade path for outdated deps, alternatives for problematic ones.

## Output
A dependency audit report with security, license, and staleness findings.