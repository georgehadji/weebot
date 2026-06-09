---
name: test-generator
description: "Use when generating tests for existing code. Trigger: test, unit test, integration test, test coverage, write tests, generate tests."
license: MIT
---
# Test Generator

## When to use
Generate unit and integration tests for existing source code.

## Workflow
1. **Read source** — parse the target file to identify functions, methods, and classes.
2. **Identify test cases:**
   - Happy path (expected input → expected output)
   - Edge cases (null, empty, boundary values)
   - Error cases (invalid input, exceptions)
3. **Generate tests** in the project's test framework (pytest, jest, go test).
4. **Include** — arrange/act/assert pattern, descriptive test names, any required fixtures.
5. **Run tests** — verify they pass against the current code.
6. **Output** — test file next to the source file.

## Output
A test file with passing unit tests.