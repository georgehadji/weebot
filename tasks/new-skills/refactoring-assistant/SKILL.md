---
name: refactoring-assistant
description: "Use when refactoring or improving existing code. Trigger: refactor, improve code, clean up, simplify, extract method, reduce complexity."
license: MIT
---
# Refactoring Assistant

## When to use
Improve existing code without changing its external behavior.

## Workflow
1. **Analyze** — identify code smells: long functions, duplicated code, deep nesting, god classes.
2. **Prioritize** — rank by impact (readability, maintainability, performance).
3. **Apply refactorings:**
   - Extract method/function
   - Rename for clarity
   - Reduce nesting (early returns, guard clauses)
   - Replace magic numbers with constants
   - Simplify conditionals
4. **Verify** — run existing tests to confirm behavior is preserved.
5. **Output** — refactored code with a summary of changes.

## Output
Refactored code with change log.