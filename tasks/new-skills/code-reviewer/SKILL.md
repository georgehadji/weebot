---
name: code-reviewer
description: "Use when the user asks for a code review, security audit, or code quality check. Trigger keywords: review, audit, check, analyze, quality, security, bug, vulnerability, refactor, improve."
license: MIT
---

# Code Reviewer

## When to use
The user wants a thorough code review covering security, performance, style, and correctness. Works with any language.

## Workflow

1. **Inventory the codebase** — use `bash` to list files and `file_editor` to read key files.
2. **Analyze by category:**
   - **Security:** Hardcoded secrets, SQL injection, XSS, path traversal, unsafe eval/exec, missing input validation
   - **Performance:** N+1 queries, unnecessary allocations, blocking I/O, missing indexes
   - **Correctness:** Edge cases, null handling, error propagation, race conditions
   - **Style:** Naming conventions, function length, complexity, documentation
3. **For each issue found**, record:
   - File:line reference
   - Severity (BLOCKER / HIGH / MEDIUM / LOW)
   - Description of the problem
   - Suggested fix with code example
4. **Produce a review report** — write to the specified output file in markdown format.

## Tool guidance
- `file_editor`: Use `view` to read files, `str_replace` to apply fixes if asked.
- `bash`: Use `grep` for pattern searching across files.
- `python_execute`: Can run static analysis tools if available.

## Output
A markdown report with summary, detailed findings, and optional applied fixes.
